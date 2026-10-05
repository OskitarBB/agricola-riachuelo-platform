# notificaciones/services.py — Avisos de WhatsApp posteriores a la confirmación (CU8, RF10 del curso).
# La web solo ENCOLA (filas en `notifications` dentro de la transacción de la decisión); el worker envía.
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from auditoria import services as audit
from notificaciones.models import Notification, NotificationRecipient, NotificationStatus
from notificaciones.whatsapp import WhatsAppError
from revision.models import Case, CaseNotificationStatus

log = logging.getLogger("riachuelo.avisos")

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=2)


def recipients_for_case(case):
    """Destinatarios activos, con consentimiento registrado y con el lote del caso en su alcance (vacío = todos)."""
    return (NotificationRecipient.objects.filter(active=True, opt_in_at__isnull=False)
            .filter(Q(lots__isnull=True) | Q(lots=case.lot_id)).distinct().order_by("pk"))


def enqueue_for_review(review):
    case = review.case
    recipients = list(recipients_for_case(case))
    for r in recipients:
        Notification.objects.get_or_create(
            review=review, recipient=r,
            defaults={"case": case, "recipient_name": r.full_name, "recipient_phone": r.phone_e164})
    if not recipients:
        audit.record("case", case.pk, "AVISO_SIN_DESTINATARIOS", None, None, {"lot": case.lot_id})
    return len(recipients)


def case_has_effective_notifications(case):
    return Notification.objects.filter(case=case).exclude(status=NotificationStatus.NO_APLICA).exists()


def case_notification_summary(case):
    statuses = set(Notification.objects.filter(case=case).exclude(status=NotificationStatus.NO_APLICA)
                   .values_list("status", flat=True))
    if not statuses:
        return CaseNotificationStatus.NO_APLICA
    if NotificationStatus.PENDIENTE_ENVIO in statuses:
        return CaseNotificationStatus.PENDIENTE_ENVIO
    if NotificationStatus.ERROR_ENVIO in statuses:
        return CaseNotificationStatus.ERROR_ENVIO
    return CaseNotificationStatus.ENVIADO


def cancel_pending_for_case(case):
    return (Notification.objects.filter(case=case, status=NotificationStatus.PENDIENTE_ENVIO)
            .update(status=NotificationStatus.NO_APLICA, error="Anulado: la decisión se corrigió antes del envío."))


def _refresh_case(case_id):
    case = Case.objects.select_for_update().get(pk=case_id)
    case.notification_status = case_notification_summary(case)
    case.save(update_fields=["notification_status"])


# ------------------------------------------------------------------ worker (python manage.py worker_ia)
def claim_next_notification(worker_id):
    now = timezone.now()
    with transaction.atomic():
        n = (Notification.objects.select_for_update(skip_locked=True)
             .filter(status=NotificationStatus.PENDIENTE_ENVIO, available_at__lte=now)
             .filter(Q(locked_until__isnull=True) | Q(locked_until__lte=now))
             .order_by("created_at").first())
        if n is None:
            return None
        n.locked_by, n.locked_until, n.attempts = worker_id, now + LEASE, n.attempts + 1
        n.save(update_fields=["locked_by", "locked_until", "attempts"])
        return n


def _one_line(text):
    # Los parámetros de una plantilla de WhatsApp no admiten saltos de línea ni tabulaciones.
    return " ".join(str(text).split())


def build_whatsapp_payload(n):
    case = (Case.objects.select_related("lot", "row", "segment", "marker").get(pk=n.case_id))
    where = " · ".join(x for x in [
        f"segmento {case.segment.code}" if case.segment_id else "",
        f"marcador {case.marker.code}" if case.marker_id else "",
    ] if x) or "sin segmento ni marcador"
    captured = timezone.localtime(case.captured_at).strftime("%d/%m/%Y %H:%M")
    link = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("web:caso", args=[case.pk])
    params = [case.lot.code, str(case.row.number), case.get_lateral_code_display(), where, captured, link]
    return {
        "messaging_product": "whatsapp",
        "to": n.recipient_phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_TEMPLATE,
            "language": {"code": settings.WHATSAPP_TEMPLATE_LANG},
            "components": [{"type": "body",
                            "parameters": [{"type": "text", "text": _one_line(p)} for p in params]}],
        },
    }


def mark_sent(n, provider_message_id):
    with transaction.atomic():
        n = Notification.objects.select_for_update().get(pk=n.pk)
        n.status, n.provider_message_id, n.sent_at = NotificationStatus.ENVIADO, provider_message_id, timezone.now()
        n.locked_until, n.error = None, ""
        n.save()
        _refresh_case(n.case_id)
    return n


def mark_failed(n, error, retryable=True):
    with transaction.atomic():
        n = Notification.objects.select_for_update().get(pk=n.pk)
        n.error, n.locked_until = str(error)[:2000], None
        if retryable and n.attempts < MAX_ATTEMPTS:
            n.available_at = timezone.now() + timedelta(minutes=2 ** n.attempts)  # 2, 4, 8, 16 min
        else:
            n.status = NotificationStatus.ERROR_ENVIO  # no toca la decisión del especialista
        n.save()
        _refresh_case(n.case_id)
    return n


def process_pending_notifications(client, worker_id, limit=20):
    sent = 0
    for _ in range(limit):
        n = claim_next_notification(worker_id)
        if n is None:
            break
        try:
            message_id = client.send(build_whatsapp_payload(n))
        except WhatsAppError as exc:
            n = mark_failed(n, exc, retryable=exc.retryable)
            if n.status == NotificationStatus.ERROR_ENVIO:
                log.error("Aviso %s a %s: ERROR_ENVIO tras %s intento(s): %s", str(n.pk)[:8], n.recipient_name,
                          n.attempts, exc)
            else:
                log.warning("Aviso %s a %s falló (intento %s); se reintenta a las %s: %s", str(n.pk)[:8],
                            n.recipient_name, n.attempts, timezone.localtime(n.available_at).strftime("%H:%M"), exc)
        else:
            mark_sent(n, message_id)
            log.info("Aviso %s enviado a %s (%s)", str(n.pk)[:8], n.recipient_name, message_id)
            sent += 1
    return sent
