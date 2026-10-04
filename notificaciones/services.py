"""Notification queue rules."""
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from notificaciones.models import Notification, NotificationRecipient, NotificationStatus
from revision.models import CaseNotificationStatus


def build_whatsapp_payload(notification):
    """Build a template payload with a link to Django, not to Cloudinary."""
    case = notification.case
    case_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{case.get_absolute_url()}"
    lot = case.lot.code if case.lot else "Sin lote"
    body_values = [case.disease or "Indicio", lot, case.row_label, case_url]
    return {
        "messaging_product": "whatsapp",
        "to": notification.recipient.phone_e164,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_TEMPLATE,
            "language": {"code": settings.WHATSAPP_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": value} for value in body_values],
                }
            ],
        },
    }


@transaction.atomic
def enqueue_case_notification(case):
    """Create one pending notification per active matching recipient."""
    lot = case.lot
    recipients = NotificationRecipient.objects.filter(is_active=True)
    if lot:
        recipients = recipients.filter(Q(lot__isnull=True) | Q(lot=lot))
    created = []
    for recipient in recipients.distinct():
        notif, _ = Notification.objects.get_or_create(
            case=case,
            recipient=recipient,
            defaults={"status": NotificationStatus.PENDIENTE},
        )
        notif.payload = build_whatsapp_payload(notif)
        notif.status = NotificationStatus.PENDIENTE
        notif.save(update_fields=["payload", "status"])
        created.append(notif)
    return created


def cancel_pending_case_notifications(case):
    return case.notifications.filter(status__in=[NotificationStatus.PENDIENTE, NotificationStatus.ERROR_REINTENTABLE]).update(
        status=NotificationStatus.ANULADA
    )


@transaction.atomic
def claim_next_notification(worker_id):
    now = timezone.now()
    qs = Notification.objects.select_for_update(skip_locked=True).filter(
        status__in=[NotificationStatus.PENDIENTE, NotificationStatus.ERROR_REINTENTABLE]
    )
    qs = qs.filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
    notification = qs.order_by("created_at").first()
    if not notification:
        return None
    notification.status = NotificationStatus.TOMADA
    notification.claimed_at = now
    notification.claimed_by = worker_id
    notification.attempts += 1
    notification.save(update_fields=["status", "claimed_at", "claimed_by", "attempts"])
    return notification


def process_pending_notifications(client, worker_id, limit=10):
    """Send pending WhatsApp messages outside request/response time."""
    sent = 0
    for _ in range(limit):
        notification = claim_next_notification(worker_id)
        if not notification:
            break
        try:
            response = client.send_template(notification.payload or build_whatsapp_payload(notification))
        except Exception as exc:
            notification.status = NotificationStatus.ERROR_REINTENTABLE if getattr(exc, "retryable", True) else NotificationStatus.ERROR_FINAL
            notification.error = str(exc)[:2000]
            notification.save(update_fields=["status", "error"])
            continue
        notification.status = NotificationStatus.ENVIADA
        notification.provider_message_id = (response.get("messages") or [{}])[0].get("id", "")
        notification.sent_at = timezone.now()
        notification.error = ""
        notification.save(update_fields=["status", "provider_message_id", "sent_at", "error"])
        notification.case.notification_status = CaseNotificationStatus.ENVIADO
        notification.case.save(update_fields=["notification_status"])
        sent += 1
    return sent
