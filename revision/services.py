# revision/services.py — Reglas de la revisión (RN-W01 a RN-W07). La web, Django Admin y cualquier script usan
# SOLO estas funciones para abrir, decidir o corregir un caso: así la regla se aplica igual en todas partes.
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from auditoria import services as audit
from campo.models import Marker
from cuentas.models import Role
from evidencias.models import Capture
from ia.models import AiStatus, DetectionReview
from notificaciones import services as notif
from revision.models import (
    DECISIONS,
    Case,
    CaseNotificationStatus,
    HumanReview,
    LocationSource,
    ReviewStatus,
)

OBSERVATION_REQUIRED = {ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, ReviewStatus.EVIDENCIA_INSUFICIENTE}


class CaseAlreadyDecided(Exception):
    """Otro especialista decidió el caso mientras este tenía la pantalla abierta (HTTP 409 en la web)."""

    def __init__(self, case):
        super().__init__("El caso ya tiene una decisión")
        self.case = case


class StaleReview(Exception):
    """La decisión vigente cambió desde que se abrió el formulario de corrección (HTTP 409)."""

    def __init__(self, current):
        super().__init__("La decisión vigente cambió")
        self.current = current


def _require_specialist(user):
    # RN-W01 (RN-01 del curso): solo el ESPECIALISTA_FITOSANITARIO confirma, descarta o corrige.
    if not (user and user.is_authenticated and user.is_active and user.has_role(Role.ESPECIALISTA_FITOSANITARIO)):
        raise PermissionDenied("Solo el especialista fitosanitario puede decidir un caso")


def case_location(capture):
    """Ubicación del caso: contexto de la repetición (RN-07 del maestro móvil) o de la secuencia.
    Prioridad de coordenadas: GPS de la secuencia → coordenadas del marcador (aproximada) → ninguna."""
    ctx = capture.retake_context
    if ctx:  # se guarda tal como llega de la app (camelCase)
        segment_id, marker_id = ctx.get("segmentId"), ctx.get("markerId")
        lat, lon, acc = ctx.get("lat"), ctx.get("lon"), ctx.get("gpsAccuracyM")
    else:
        seq = capture.sequence
        segment_id, marker_id = seq.segment_id, seq.marker_id
        lat, lon, acc = seq.lat, seq.lon, seq.gps_accuracy_m
    source = LocationSource.GPS
    if lat is None or lon is None:
        marker = Marker.objects.filter(pk=marker_id).only("lat", "lon").first() if marker_id else None
        if marker is not None and marker.lat is not None and marker.lon is not None:
            lat, lon, acc, source = marker.lat, marker.lon, None, LocationSource.MARCADOR
        else:
            lat = lon = acc = None
            source = LocationSource.NINGUNA
    return {"segment_id": segment_id, "marker_id": marker_id, "lat": lat, "lon": lon,
            "gps_accuracy_m": acc, "location_source": source}


def _new_case(capture, task, origin, stats):
    p = capture.monitoring_pass
    return Case.objects.create(
        capture=capture, ai_task=task, origin=origin,
        session_id=capture.session_id, monitoring_pass_id=p.pk, sequence_id=capture.sequence_id,
        lot_id=p.lot_id, row_id=p.row_id, lateral_code=capture.lateral_code,
        captured_at=capture.captured_at,
        **stats, **case_location(capture),
    )


def _stats(task):
    confidences = list(task.detections.values_list("confidence", flat=True)) if task else []
    return {"detections_count": len(confidences), "max_confidence": max(confidences) if confidences else None}


def open_case_from_analysis(task):
    """La llama el worker dentro de la transacción que guarda las cajas (ia.services.save_analysis_result)."""
    capture = Capture.objects.select_related("sequence", "monitoring_pass").get(pk=task.capture_id)
    case = Case.objects.select_for_update().filter(capture=capture).first()
    stats = _stats(task)
    if case is None:
        case = _new_case(capture, task, Case.Origin.IA, stats)
        audit.record("case", case.pk, "CASO_ABIERTO", None, None, {"origin": "IA", "aiTask": str(task.pk)})
    elif case.status == ReviewStatus.PENDIENTE_REVISION:
        case.ai_task = task
        case.detections_count, case.max_confidence = stats["detections_count"], stats["max_confidence"]
        case.save(update_fields=["ai_task", "detections_count", "max_confidence"])
        audit.record("case", case.pk, "CASO_NUEVO_ANALISIS", None, None, {"aiTask": str(task.pk)})
    else:  # un análisis nuevo nunca cambia una decisión tomada (RN-W06)
        audit.record("case", case.pk, "ANALISIS_POSTERIOR_A_DECISION", None, None, {"aiTask": str(task.pk)})
    return case


def open_manual_case(capture_id, user):
    """El especialista abre un caso sobre una foto SIN_INDICIOS_IA o ERROR_DE_ANALISIS (falso negativo posible)."""
    _require_specialist(user)
    with transaction.atomic():
        capture = Capture.objects.select_related("sequence", "monitoring_pass").select_for_update().get(pk=capture_id)
        existing = Case.objects.filter(capture=capture).first()
        if existing is not None:
            return existing, False
        task = (capture.ai_tasks.filter(status__in=[AiStatus.SIN_INDICIOS_IA, AiStatus.ERROR_DE_ANALISIS])
                .order_by("-finished_at").first())
        if task is None:
            raise ValidationError("Solo se abre un caso sobre fotos aceptadas por calidad y con el análisis terminado.")
        case = _new_case(capture, task, Case.Origin.MANUAL, {"detections_count": 0, "max_confidence": None})
        audit.record("case", case.pk, "CASO_ABIERTO", user, None, {"origin": "MANUAL", "aiTask": str(task.pk)})
    return case, True


def _clean_inputs(case, decision, observation, confirmed_class, rejected_detection_ids):
    if decision not in DECISIONS:
        raise ValidationError({"decision": "Decisión no válida."})
    observation = (observation or "").strip()
    max_len = settings.WEB["OBSERVATION_MAX_LENGTH"]
    errors = {}
    if len(observation) > max_len:
        errors["observation"] = f"Máximo {max_len} caracteres."
    elif decision in OBSERVATION_REQUIRED and not observation:
        errors["observation"] = ("Registra la observación fitosanitaria."
                                 if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA
                                 else "Indica qué falta en la evidencia para decidir.")
    task = case.ai_task
    valid_ids = set(task.detections.values_list("id", flat=True)) if task else set()
    try:
        rejected = {int(x) for x in (rejected_detection_ids or [])}
    except (TypeError, ValueError):
        rejected = {-1}
    if not rejected <= valid_ids:
        errors["rejected_detection_ids"] = "Hay cajas que no pertenecen a este caso."
    if decision != ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        confirmed_class = ""
    elif confirmed_class and task and confirmed_class not in (task.model_config.classes or []):
        errors["confirmed_class"] = "Clase no válida para el modelo de este análisis."
    if errors:
        raise ValidationError(errors)
    return observation, confirmed_class or "", sorted(rejected)


def _apply_detection_status(case, decision, rejected):
    if case.ai_task_id is None:
        return
    dets = case.ai_task.detections
    if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        dets.exclude(id__in=rejected).update(review_status=DetectionReview.CONFIRMADO_POR_ESPECIALISTA)
        dets.filter(id__in=rejected).update(review_status=DetectionReview.DESCARTADO)
    else:
        dets.update(review_status=decision)


def decide_case(case_id, user, decision, observation="", confirmed_class="", rejected_detection_ids=()):
    """CU6/CU7: decisión del especialista. Una sola transacción: decisión + cajas + caso + avisos + auditoría."""
    _require_specialist(user)
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("ai_task__model_config").get(pk=case_id)
        if case.status != ReviewStatus.PENDIENTE_REVISION:
            raise CaseAlreadyDecided(case)
        observation, confirmed_class, rejected = _clean_inputs(
            case, decision, observation, confirmed_class, rejected_detection_ids)
        review = HumanReview.objects.create(
            case=case, ai_task=case.ai_task, decision=decision, observation=observation,
            confirmed_class=confirmed_class, rejected_detection_ids=rejected, reviewer=user)
        _apply_detection_status(case, decision, rejected)
        before = {"status": case.status}
        case.status = decision
        case.decided_at = review.reviewed_at
        case.decided_by = user
        if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
            notif.enqueue_for_review(review)  # RN-W03: el aviso nace solo de una confirmación
        case.notification_status = notif.case_notification_summary(case)
        case.save(update_fields=["status", "decided_at", "decided_by", "notification_status"])
        audit.record("case", case.pk, "CASO_DECIDIDO", user, before,
                     {"status": decision, "review": str(review.pk), "rejectedDetections": rejected})
    return review


def correct_decision(case_id, user, decision, observation, correction_reason, expected_review_id,
                     confirmed_class="", rejected_detection_ids=()):
    """Corrección (8.5): nueva decisión que reemplaza a la vigente; la anterior se conserva en el historial."""
    _require_specialist(user)
    correction_reason = (correction_reason or "").strip()
    if not correction_reason:
        raise ValidationError({"correction_reason": "Explica por qué corriges la decisión."})
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("ai_task__model_config").get(pk=case_id)
        if case.status == ReviewStatus.PENDIENTE_REVISION:
            raise ValidationError("El caso todavía no tiene una decisión que corregir.")
        current = case.reviews.get(is_current=True)
        if str(current.pk) != str(expected_review_id):
            raise StaleReview(current)
        observation, confirmed_class, rejected = _clean_inputs(
            case, decision, observation, confirmed_class, rejected_detection_ids)
        current.is_current = False
        current.save(update_fields=["is_current"])
        review = HumanReview.objects.create(
            case=case, ai_task=case.ai_task, decision=decision, observation=observation,
            confirmed_class=confirmed_class, rejected_detection_ids=rejected, reviewer=user,
            supersedes=current, correction_reason=correction_reason)
        _apply_detection_status(case, decision, rejected)
        before = {"status": case.status, "review": str(current.pk)}
        if current.decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA and decision != current.decision:
            notif.cancel_pending_for_case(case)  # lo ya ENVIADO no se puede retirar (Q-W07)
        if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA and not notif.case_has_effective_notifications(case):
            notif.enqueue_for_review(review)
        case.status = decision
        case.decided_at = review.reviewed_at
        case.decided_by = user
        case.notification_status = notif.case_notification_summary(case)
        case.save(update_fields=["status", "decided_at", "decided_by", "notification_status"])
        audit.record("case", case.pk, "CASO_CORREGIDO", user, before,
                     {"status": decision, "review": str(review.pk), "reason": correction_reason})
    return review


__all__ = ["CaseAlreadyDecided", "StaleReview", "CaseNotificationStatus", "case_location", "open_case_from_analysis",
           "open_manual_case", "decide_case", "correct_decision"]
