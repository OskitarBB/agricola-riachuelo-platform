"""Review rules.

Views call these functions instead of mutating cases directly. That keeps
state transitions, audit and notification side effects in one place.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from auditoria.services import log_event
from cuentas.models import Role
from revision.models import Case, CaseNotificationStatus, HumanReview, LocationSource, ReviewStatus


FINAL_STATUSES = {
    ReviewStatus.CONFIRMADO_POR_ESPECIALISTA,
    ReviewStatus.DESCARTADO,
    ReviewStatus.EVIDENCIA_INSUFICIENTE,
}


def can_review(user):
    return bool(user and user.is_authenticated and user.has_role(Role.ESPECIALISTA_FITOSANITARIO, Role.ADMINISTRADOR))


@transaction.atomic
def open_case_for_capture(capture, disease="", confidence=None):
    """Create or update the review case for an accepted capture."""
    lat = capture.latitude
    lon = capture.longitude
    source = LocationSource.GPS if capture.has_location else LocationSource.SIN_UBICACION
    case, created = Case.objects.get_or_create(
        capture=capture,
        defaults={
            "disease": disease,
            "confidence": Decimal(str(confidence)) if confidence is not None else None,
            "latitude": lat,
            "longitude": lon,
            "location_source": source,
        },
    )
    if not created and disease and not case.disease:
        case.disease = disease
        case.confidence = Decimal(str(confidence)) if confidence is not None else case.confidence
        case.save(update_fields=["disease", "confidence"])
    return case


@transaction.atomic
def decide_case(case_id, reviewer, new_status, observation=""):
    """Apply a human decision and enqueue/cancel WhatsApp notifications."""
    if not can_review(reviewer):
        raise PermissionDenied("El usuario no puede revisar casos")
    if new_status not in FINAL_STATUSES:
        raise ValidationError("Decision no valida")

    case = Case.objects.select_for_update().select_related("capture").get(pk=case_id)
    previous = case.status
    case.status = new_status
    case.decided_by = reviewer
    case.decided_at = timezone.now()
    case.decision_note = observation

    if new_status == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        case.notification_status = CaseNotificationStatus.PENDIENTE
    elif previous == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        case.notification_status = CaseNotificationStatus.ANULADO

    case.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "notification_status"])
    HumanReview.objects.create(
        case=case,
        reviewer=reviewer,
        from_status=previous,
        to_status=new_status,
        observation=observation,
    )
    log_event(reviewer, "CASO_DECIDIDO", target=case, payload={"from": previous, "to": new_status})

    from notificaciones.services import cancel_pending_case_notifications, enqueue_case_notification

    if new_status == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        enqueue_case_notification(case)
    else:
        cancel_pending_case_notifications(case)
    return case
