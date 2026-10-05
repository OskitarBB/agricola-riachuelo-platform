# evidencias/services.py — Ticket de subida y confirmación de capturas (§15.7 y §28.7 del maestro móvil).
#
#   1. upload_ticket: valida padres (sesión, pasada, secuencia), md5 y tamaño; si la captura ya está confirmada igual
#      responde alreadyConfirmed; si no, firma los parámetros de Cloudinary. No escribe nada.
#   2. (la app sube el JPEG directo a Cloudinary con esos parámetros)
#   3. confirm_capture: verifica la firma de Cloudinary (public_id + version), el publicId y los bytes; en UNA
#      transacción inserta captures + quality_results + su ai_task PENDIENTE_DE_ANALISIS. No espera a la IA.
#   v1 (compatibilidad): confirm_multipart recibe el JPEG por multipart (la app actual), comprueba tamaño y md5,
#      lo sube a Cloudinary desde el servidor y sigue por confirm_capture (misma verificación de firma).
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from api.errors import ApiError
from auditoria import services as audit
from cuentas.models import User
from cuentas.services import iso
from evidencias import nube
from evidencias.models import Capture, QualityResult
from ia import services as ia
from monitoreo.models import CaptureSequence, MonitoringPass, MonitoringSession
from monitoreo.services import _ensure_device

log = logging.getLogger("riachuelo.capturas")


def _parents(session_id, pass_id, sequence_id):
    session = MonitoringSession.objects.filter(pk=session_id).first()
    if session is None:
        raise ApiError("SESSION_NOT_FOUND", 404)
    mpass = MonitoringPass.objects.filter(pk=pass_id, session=session).first()
    if mpass is None:
        raise ApiError("PASS_NOT_FOUND", 404)
    seq = CaptureSequence.objects.filter(pk=sequence_id, monitoring_pass=mpass).first()
    if seq is None:
        raise ApiError("SEQUENCE_NOT_FOUND", 404)
    return session, mpass, seq


def _same_file(capture, md5, size_bytes):
    return capture.md5.lower() == str(md5).lower() and int(capture.size_bytes) == int(size_bytes)


def upload_ticket(capture_id, data, base_url=""):
    if str(data["captureId"]) != str(capture_id):
        raise ApiError("VALIDATION_ERROR", 400, field_errors=[
            {"field": "captureId", "message": "No coincide con el captureId de la ruta."}])
    session, mpass, seq = _parents(data["sessionId"], data["passId"], data["sequenceId"])
    existing = Capture.objects.filter(pk=capture_id).first()
    if existing is not None:
        if _same_file(existing, data["md5"], data["sizeBytes"]):
            return {"captureId": str(capture_id), "alreadyConfirmed": True, "upload": None,
                    "serverTime": iso(timezone.now())}
        raise ApiError("CAPTURE_CONFLICT", 409)
    if int(data["sizeBytes"]) > settings.CLOUDINARY_MAX_UPLOAD_BYTES:
        raise ApiError("PAYLOAD_TOO_LARGE", 413)
    try:
        ticket = nube.build_upload_ticket(nube.public_id_for(session.pk, mpass.pk, capture_id), base_url)
    except nube.NubeNoConfigurada as exc:
        log.error("No se pudo firmar el ticket de %s: %s", str(capture_id)[:8], exc)
        raise ApiError("INTERNAL_ERROR", 500, "Cloudinary no está configurado en el servidor.") from exc
    server_time = ticket.pop("serverTime")
    return {"captureId": str(capture_id), "alreadyConfirmed": False, "upload": ticket, "serverTime": server_time}


def _validar_metadata(meta, mpass, prefijo="metadata."):
    """Lateral de la pasada y usuarios existentes. Devuelve {user_id: User}."""
    errors = []
    if meta["lateralCode"] != mpass.lateral_code:
        errors.append({"field": f"{prefijo}lateralCode", "message": "No coincide con el lateral de la pasada."})
    users = {u.pk: u for u in User.objects.filter(pk__in=[meta["cameraUserId"], meta["operatorUserId"]])}
    if meta["cameraUserId"] not in users:
        errors.append({"field": f"{prefijo}cameraUserId", "message": "El usuario de la cámara no existe."})
    if meta["operatorUserId"] not in users:
        errors.append({"field": f"{prefijo}operatorUserId", "message": "El operador no existe."})
    if errors:
        raise ApiError("VALIDATION_ERROR", 400, field_errors=errors)
    return users


def confirm_capture(meta, cloud):
    """POST /captures/upload (JSON). Devuelve (capture, created)."""
    session, mpass, seq = _parents(meta["sessionId"], meta["passId"], meta["sequenceId"])
    capture_id = meta["captureId"]
    existing = Capture.objects.filter(pk=capture_id).first()
    if existing is not None:
        if _same_file(existing, meta["md5"], meta["sizeBytes"]):
            return existing, False  # reintento: 200 duplicate=true
        raise ApiError("CAPTURE_CONFLICT", 409)
    users = _validar_metadata(meta, mpass)
    expected = nube.public_id_for(session.pk, mpass.pk, capture_id)
    try:
        problem = nube.verify_cloudinary_result(expected, meta["sizeBytes"], cloud)
    except nube.NubeNoConfigurada as exc:
        raise ApiError("INTERNAL_ERROR", 500, "Cloudinary no está configurado en el servidor.") from exc
    if problem == "UPLOAD_MISMATCH":
        log.warning("Confirmación de %s rechazada: el recurso de Cloudinary no coincide (publicId o bytes)",
                    str(capture_id)[:8])
        raise ApiError("UPLOAD_MISMATCH", 409)
    if problem == "UPLOAD_SIGNATURE_INVALID":
        log.warning("Confirmación de %s rechazada: firma de Cloudinary inválida", str(capture_id)[:8])
        raise ApiError("UPLOAD_SIGNATURE_INVALID", 422)

    quality = meta["quality"]
    try:
        with transaction.atomic():
            device = _ensure_device(meta["deviceId"], user=users[meta["cameraUserId"]])
            capture = Capture.objects.create(
                capture_id=capture_id, sequence=seq, session=session, monitoring_pass=mpass,
                lateral_code=meta["lateralCode"], device=device, camera_role=meta["cameraRole"],
                camera_user=users[meta["cameraUserId"]], operator_user=users[meta["operatorUserId"]],
                captured_at=meta["capturedAt"], width=meta["width"], height=meta["height"],
                size_bytes=meta["sizeBytes"], md5=meta["md5"].lower(), quality_status=quality["status"],
                replaces_capture_id=meta.get("replacesCaptureId"), retake_context=meta.get("retakeContext"),
                app_version=meta["appVersion"], cloudinary_public_id=cloud["publicId"],
                cloudinary_version=cloud["version"], cloudinary_bytes=cloud["bytes"],
                cloudinary_format=(cloud.get("format") or "")[:10], cloudinary_width=cloud.get("width"),
                cloudinary_height=cloud.get("height"))
            metrics = quality.get("metrics")
            QualityResult.objects.create(
                capture=capture, status=quality["status"], reasons=list(quality.get("reasons") or []),
                metrics=metrics, profile_version=quality["profileVersion"],
                duration_ms=int(metrics["durationMs"]) if metrics and metrics.get("durationMs") is not None else None)
            try:
                task = ia.enqueue_analysis(capture)  # misma transacción (D-29): nunca «foto sin tarea»
            except ia.NoActiveModel:
                task = None
                log.error("No hay modelo de IA activo: la foto %s quedó sin análisis. Activa un modelo en "
                          "/gestion/ (el worker la encolará después).", str(capture_id)[:8])
            audit.record("capture", capture.pk, "CAPTURA_CONFIRMADA", None, None,
                         {"session": str(session.pk), "quality": capture.quality_status,
                          "aiTask": str(task.pk) if task else None})
    except IntegrityError:
        # Carrera entre dos confirmaciones de la misma foto: la segunda ve la primera y responde duplicate.
        existing = Capture.objects.filter(pk=capture_id).first()
        if existing is not None and _same_file(existing, meta["md5"], meta["sizeBytes"]):
            return existing, False
        raise ApiError("CAPTURE_CONFLICT", 409)
    log.info("Foto %s confirmada (%s · %s) — %s", str(capture_id)[:8], capture.get_camera_role_display(),
             capture.get_quality_status_display(), "en cola de IA" if task else "sin análisis (calidad o sin modelo)")
    return capture, True


def confirm_multipart(meta, archivo):
    """POST /captures/upload multipart (file + metadata), contrato v1 de la app. Devuelve (capture, created)."""
    import hashlib

    session, mpass, _seq = _parents(meta["sessionId"], meta["passId"], meta["sequenceId"])
    capture_id = meta["captureId"]
    existing = Capture.objects.filter(pk=capture_id).first()
    if existing is not None:
        if _same_file(existing, meta["md5"], meta["sizeBytes"]):
            return existing, False  # reintento de la app: no se vuelve a subir
        raise ApiError("CAPTURE_CONFLICT", 409)
    if archivo.size > settings.CLOUDINARY_MAX_UPLOAD_BYTES:
        raise ApiError("PAYLOAD_TOO_LARGE", 413)
    _validar_metadata(meta, mpass)  # antes de subir: no dejar fotos huérfanas en Cloudinary
    data = archivo.read()
    errors = []
    if len(data) != int(meta["sizeBytes"]):
        errors.append({"field": "file", "message": f"El archivo pesa {len(data)} bytes y la metadata dice "
                                                   f"{meta['sizeBytes']}."})
    if hashlib.md5(data).hexdigest() != str(meta["md5"]).lower():
        errors.append({"field": "file", "message": "El md5 del archivo no coincide con metadata.md5."})
    if errors:
        log.warning("Foto %s rechazada: el archivo no coincide con su metadata", str(capture_id)[:8])
        raise ApiError("VALIDATION_ERROR", 400, field_errors=errors)
    public_id = nube.public_id_for(session.pk, mpass.pk, capture_id)
    try:
        cloud = nube.subir_desde_servidor(public_id, data)
    except nube.NubeNoConfigurada as exc:
        raise ApiError("INTERNAL_ERROR", 500, "Cloudinary no está configurado en el servidor.") from exc
    except nube.SubidaFallida as exc:
        log.error("No se pudo subir la foto %s a Cloudinary: %s", str(capture_id)[:8], exc)
        raise ApiError("INTERNAL_ERROR", 502, "No se pudo guardar la foto en Cloudinary; la app reintentará.") from exc
    return confirm_capture(meta, cloud)
