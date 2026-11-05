# notificaciones/services.py — Avisos posteriores a la confirmación (CU8, RF10 del curso). Desde la v1.3
# (ADR-W-007) también se avisa cuando la IA confirma sola un caso de alta confianza (enqueue_for_ai_case).
# v1.5 (ADR-W-011): los avisos van por Telegram (foto con las cajas + texto + botones).
# La web solo ENCOLA (filas en `notifications` dentro de la transacción de la decisión); el worker envía.
import html
import io
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from auditoria import services as audit
from notificaciones.models import Notification, NotificationRecipient, NotificationStatus
from notificaciones.errores import AvisoError
from revision.models import Case, CaseNotificationStatus

log = logging.getLogger("riachuelo.avisos")

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=2)
TELEGRAM = "TELEGRAM"


def _datos_destinatario(r):
    return {"channel": TELEGRAM, "recipient_name": r.full_name, "recipient_phone": r.phone_e164 or "",
            "recipient_chat": r.telegram_chat_id}


def recipients_for_case(case):
    """Destinatarios activos, con consentimiento registrado, con el lote del caso en su alcance (vacío = todos) y con
    chat de Telegram."""
    return (NotificationRecipient.objects.filter(active=True, opt_in_at__isnull=False)
            .exclude(telegram_chat_id="")
            .filter(Q(lots__isnull=True) | Q(lots=case.lot_id)).distinct().order_by("pk"))


def enqueue_for_review(review):
    case = review.case
    recipients = list(recipients_for_case(case))
    for r in recipients:
        Notification.objects.get_or_create(
            review=review, recipient=r, defaults={"case": case, **_datos_destinatario(r)})
    if not recipients:
        audit.record("case", case.pk, "AVISO_SIN_DESTINATARIOS", None, None, {"lot": case.lot_id})
    return len(recipients)


def enqueue_for_ai_case(case):
    """v1.3 (ADR-W-007): avisos de un caso «Confirmado por IA» (sin decisión humana: review vacío). Idempotente."""
    recipients = list(recipients_for_case(case))
    for r in recipients:
        Notification.objects.get_or_create(
            case=case, recipient=r, review=None,
            defaults={"kind": Notification.Kind.CASO_CONFIRMADO_IA, **_datos_destinatario(r)})
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
        qs = Notification.objects.select_for_update(skip_locked=True).filter(channel=TELEGRAM)
        n = (qs.filter(status=NotificationStatus.PENDIENTE_ENVIO, available_at__lte=now)
             .filter(Q(locked_until__isnull=True) | Q(locked_until__lte=now))
             .order_by("created_at").first())
        if n is None:
            return None
        n.locked_by, n.locked_until, n.attempts = worker_id, now + LEASE, n.attempts + 1
        n.save(update_fields=["locked_by", "locked_until", "attempts"])
        return n


# ------------------------------------------------------------------ Telegram (v1.5, ADR-W-011)
def _num(x):
    return f"{x:.2f}".replace(".", ",")  # texto para personas: coma decimal (W-16)


def _lugar(case):
    partes = [f"segmento {case.segment.code}" if case.segment_id else "", f"marcador {case.marker.code}"
              if case.marker_id else ""]
    return " · ".join(p for p in partes if p) or "sin segmento ni marcador"


def _cajas_visibles(case):
    from ia.models import DetectionReview

    if not case.ai_task_id:
        return []
    return list(case.ai_task.detections.exclude(review_status=DetectionReview.DESCARTADO)
                .values_list("x_min", "y_min", "x_max", "y_max", "confidence"))


def foto_para_aviso(case, ancho=None):
    """JPEG de la foto del caso con las cajas de la IA dibujadas (amarillo, como en el visor), a lo sumo `ancho`
    píxeles por lado. La foto se descarga del original firmado y no se guarda en ninguna parte (W-10)."""
    from PIL import Image, ImageDraw, ImageOps

    from evidencias import nube

    ancho = ancho or settings.TELEGRAM_FOTO_ANCHO
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(nube.download_original(case.capture)))).convert("RGB")
    base = (case.ai_task.image_width if case.ai_task_id else None) or img.width
    escala, grosor = img.width / base, max(3, img.width // 260)
    dibujo = ImageDraw.Draw(img)
    for x0, y0, x1, y1, _conf in _cajas_visibles(case):
        dibujo.rectangle([x0 * escala, y0 * escala, x1 * escala, y1 * escala], outline=(253, 224, 71), width=grosor)
    img.thumbnail((ancho, ancho))
    salida = io.BytesIO()
    img.save(salida, "JPEG", quality=85, optimize=True)
    return salida.getvalue()


def build_telegram_message(n, foto=None):
    from notificaciones.telegram import MAX_CAPTION, Mensaje

    case = Case.objects.select_related("lot", "row", "segment", "marker", "ai_task").get(pk=n.case_id)
    e = html.escape
    es_ia = n.kind == Notification.Kind.CASO_CONFIRMADO_IA
    lineas = (["🚨 <b>Alerta: la IA sugiere indicios de plaga</b>",
               "<i>Alta confianza · falta la revisión del especialista</i>"] if es_ia
              else ["✅ <b>Caso confirmado por el especialista</b>"])
    lineas += ["", f"📍 Lote <b>{e(case.lot.code)}</b> · hilera <b>{case.row.number}</b> · "
                   f"{e(case.get_lateral_code_display())}",
               f"🧭 {e(_lugar(case))}",
               f"🕒 Foto del {timezone.localtime(case.captured_at).strftime('%d/%m/%Y %H:%M')}"]
    cajas = _cajas_visibles(case)
    if cajas:
        lineas.append(f"🔎 IA: {len(cajas)} caja(s) · máx. {_num(max(c[4] for c in cajas))}")
    if n.review_id and n.review.observation.strip():
        lineas.append(f"📝 {e(' '.join(n.review.observation.split())[:300])}")
    link = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("web:caso", args=[case.pk])
    botones = []
    if link.startswith("https://"):  # Telegram solo acepta botones con enlaces públicos https
        botones.append(("Ver caso", link))
        if case.lat is not None and case.lon is not None:
            botones.append(("Cómo llegar", f"https://www.google.com/maps/dir/?api=1&destination={case.lat:.6f},"
                                           f"{case.lon:.6f}"))
    else:
        lineas.append(f"🔗 {e(link)}")
    lineas += ["", "<i>Aviso automático de la plataforma Riachuelo. Para ver el caso inicia sesión.</i>"]
    texto = "\n".join(lineas)
    if foto and len(texto) > MAX_CAPTION:
        foto = None  # el texto no entra como pie de foto: se manda solo el texto
    return Mensaje(chat_id=n.recipient_chat, texto=texto, botones=botones, foto=foto,
                   nombre_foto=f"caso-{str(case.pk)[:8]}.jpg")


def _enviar(n, cliente):
    foto = None
    if settings.TELEGRAM_CON_FOTO:
        try:
            foto = foto_para_aviso(Case.objects.select_related("capture", "ai_task").get(pk=n.case_id))
        except Exception as exc:  # noqa: BLE001 — sin foto igual sale el aviso (texto y enlace)
            log.warning("Aviso %s: no se pudo preparar la foto (%s: %s); se envía sin foto", str(n.pk)[:8],
                        exc.__class__.__name__, str(exc)[:200])
    return cliente.send(build_telegram_message(n, foto))


def cliente_de_aviso():
    """Cliente de Telegram del worker, o None si falta configuración (los avisos esperan en la cola)."""
    from notificaciones import telegram

    try:
        return telegram.get_client()
    except AvisoError as exc:
        log.error("Cliente de Telegram no disponible: %s. Los avisos quedarán pendientes.", exc)
        return None


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


def process_pending_notifications(cliente, worker_id, limit=20):
    sent = 0
    for _ in range(limit):
        n = claim_next_notification(worker_id)
        if n is None:
            break
        try:
            message_id = _enviar(n, cliente)
        except AvisoError as exc:
            n = mark_failed(n, exc, retryable=exc.retryable)
            if n.status == NotificationStatus.ERROR_ENVIO:
                log.error("Aviso %s a %s: ERROR_ENVIO tras %s intento(s): %s", str(n.pk)[:8], n.recipient_name,
                          n.attempts, exc)
            else:
                log.warning("Aviso %s a %s falló (intento %s); se reintenta a las %s: %s", str(n.pk)[:8],
                            n.recipient_name, n.attempts, timezone.localtime(n.available_at).strftime("%H:%M"), exc)
        else:
            mark_sent(n, message_id)
            log.info("Aviso %s enviado por Telegram a %s (%s)", str(n.pk)[:8], n.recipient_name, message_id)
            sent += 1
    return sent
