# monitoreo/services.py — Recepción idempotente de lo que sincroniza la app (§15.2, §15.5 y §15.8 del maestro móvil).
#
# Upsert por ID: repetir una llamada no duplica y responde lo mismo. Se aceptan actualizaciones de pasadas y
# secuencias ya recibidas (fotos tardías, 8.13). Una sesión CLOSED nunca vuelve a un estado anterior.
# Solo la API escribe estas tablas; la web las lee (RN-W08).
import logging

from django.db import transaction

from api.errors import ApiError
from auditoria import services as audit
from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from cuentas.models import Device, User
from monitoreo.models import (
    CaptureSequence,
    Incident,
    MarkerChange,
    MonitoringPass,
    MonitoringSession,
    SessionDevice,
    SessionStatus,
)

log = logging.getLogger("riachuelo.sincronizacion")


def _campo(field, message):
    return {"field": field, "message": message}


def _ensure_device(device_id, platform="android", model="", os_version="", app_version="", user=None):
    """Un celular que aparece en una sesión pero que nunca inició sesión con internet se registra igual
    (sin revocar), para no perder la trazabilidad de la foto."""
    device = Device.objects.filter(pk=device_id).first()
    if device is None:
        device = Device.objects.create(device_id=device_id, platform=platform or "android", model=model[:80],
                                       os_version=os_version[:40], app_version=app_version[:40], user=user)
        log.warning("Celular %s registrado desde la sincronización (no había iniciado sesión con internet)",
                    str(device_id)[:8])
    return device


def get_session(session_id):
    session = MonitoringSession.objects.filter(pk=session_id).first()
    if session is None:
        raise ApiError("SESSION_NOT_FOUND", 404)
    return session


def upsert_session(data, request_device_id=None):
    errors = []
    operator = User.objects.filter(pk=data["operatorUserId"]).first()
    if operator is None:
        errors.append(_campo("operatorUserId", "El operador no existe en el servidor."))
    camera_users = {}
    for i, cam in enumerate(data.get("cameras", [])):
        u = User.objects.filter(pk=cam["userId"]).first()
        if u is None:
            errors.append(_campo(f"cameras[{i}].userId", "El usuario de la cámara no existe en el servidor."))
        camera_users[i] = u
    if errors:
        raise ApiError("VALIDATION_ERROR", 400, field_errors=errors)

    sid = data["sessionId"]
    with transaction.atomic():
        controller = _ensure_device(data["controllerDeviceId"], user=operator)
        session = MonitoringSession.objects.select_for_update().filter(pk=sid).first()
        created = session is None
        before_status = None if created else session.status
        if created:
            session = MonitoringSession(session_id=sid)
        new_status = data["status"]
        if session.status == SessionStatus.CLOSED and new_status != SessionStatus.CLOSED:
            new_status = SessionStatus.CLOSED  # nunca se reabre una sesión cerrada
        session.operator = operator
        session.controller_device = controller
        session.status = new_status
        session.mode = data["mode"]
        session.interval_ms = data.get("intervalMs") or 0
        session.started_at = data.get("startedAt")
        if new_status == SessionStatus.CLOSED:
            session.ended_at = data.get("endedAt") or session.ended_at
        else:
            session.ended_at = data.get("endedAt")
        session.app_version = data["appVersion"]
        session.config_version = data["configVersion"]
        session.quality_profile_version = data["qualityProfileVersion"]
        session.short_test_passed_at = data.get("shortTestPassedAt")
        session.save()
        for i, cam in enumerate(data.get("cameras", [])):
            device = _ensure_device(cam["deviceId"], cam.get("platform"), cam.get("model", ""),
                                    cam.get("osVersion", ""), cam.get("appVersion", ""), camera_users[i])
            SessionDevice.objects.update_or_create(
                session=session, role=cam["role"], device=device,
                defaults={"user": camera_users[i], "platform": cam.get("platform") or device.platform,
                          "model": (cam.get("model") or "")[:80], "os_version": (cam.get("osVersion") or "")[:40],
                          "app_version": (cam.get("appVersion") or "")[:40], "paired_at": cam["pairedAt"],
                          "released": bool(cam.get("released"))})
        if created:
            audit.record("session", session.pk, "SESION_RECIBIDA", operator, None,
                         {"status": session.status, "mode": session.mode,
                          "cameras": len(data.get("cameras", [])), "appVersion": session.app_version})
        elif before_status != SessionStatus.CLOSED and session.status == SessionStatus.CLOSED:
            audit.record("session", session.pk, "SESION_CERRADA", operator, {"status": before_status},
                         {"status": session.status})
    if created:
        log.info("Nueva sesión de monitoreo %s de %s (%s, %s)", str(sid)[:8], operator.full_name,
                 session.get_mode_display(), session.get_status_display())
    return session, created


def upsert_pass(session_id, data):
    session = get_session(session_id)
    errors = []
    lot = FieldLot.objects.filter(pk=data["lotId"]).first()
    if lot is None:
        errors.append(_campo("lotId", "Lote desconocido: descarga los catálogos de nuevo."))
    row = FieldRow.objects.filter(pk=data["rowId"]).first()
    if row is None or (lot is not None and row.lot_id != lot.pk):
        errors.append(_campo("rowId", "Hilera desconocida o de otro lote."))
    marker_ids = {data.get("startMarkerId"), data.get("endMarkerId")}
    marker_ids |= {mc.get("markerId") for mc in data.get("markerChanges", [])}
    marker_ids.discard(None)
    found = set(Marker.objects.filter(pk__in=marker_ids).values_list("pk", flat=True))
    for m in sorted(marker_ids - found):
        errors.append(_campo("markerId", f"Marcador desconocido: {m}."))
    seg_ids = {mc.get("segmentId") for mc in data.get("markerChanges", [])} - {None}
    found_seg = set(FieldSegment.objects.filter(pk__in=seg_ids).values_list("pk", flat=True))
    for s in sorted(seg_ids - found_seg):
        errors.append(_campo("segmentId", f"Segmento desconocido: {s}."))
    existing = MonitoringPass.objects.filter(pk=data["passId"]).first()
    if existing is not None and existing.session_id != session.pk:
        errors.append(_campo("passId", "La pasada pertenece a otra sesión."))
    if errors:
        raise ApiError("VALIDATION_ERROR", 400, field_errors=errors)

    with transaction.atomic():
        obj, created = MonitoringPass.objects.update_or_create(
            pass_id=data["passId"],
            defaults={
                "session": session, "lot": lot, "row": row, "lateral_code": data["lateralCode"],
                "pass_order": data["passOrder"], "direction": data["direction"],
                "start_marker_id": data.get("startMarkerId"), "end_marker_id": data.get("endMarkerId"),
                "status": data["status"], "started_at": data.get("startedAt"), "ended_at": data.get("endedAt"),
                "sequences_total": data.get("sequencesTotal", 0),
                "sequences_complete": data.get("sequencesComplete", 0),
                "sequences_incomplete": data.get("sequencesIncomplete", 0),
            })
        for mc in data.get("markerChanges", []):
            MarkerChange.objects.update_or_create(
                marker_change_id=mc["markerChangeId"],
                defaults={"monitoring_pass": obj, "marker_id": mc.get("markerId"), "segment_id": mc.get("segmentId"),
                          "changed_at": mc["changedAt"], "lat": mc.get("lat"), "lon": mc.get("lon"),
                          "gps_accuracy_m": mc.get("gpsAccuracyM"), "gps_timestamp": mc.get("gpsTimestamp")})
        if created:
            audit.record("pass", obj.pk, "PASADA_RECIBIDA", None, None,
                         {"session": str(session.pk), "row": row.pk, "lateral": obj.lateral_code,
                          "status": obj.status})
    return obj, created


def upsert_sequences(session_id, sequences):
    session = get_session(session_id)
    pass_ids = {s["passId"] for s in sequences}
    passes = {p.pk: p for p in MonitoringPass.objects.filter(pk__in=pass_ids, session=session)}
    missing = [str(p) for p in pass_ids if p not in passes]
    if missing:
        raise ApiError("PASS_NOT_FOUND", 404, f"Pasadas desconocidas: {', '.join(sorted(missing)[:5])}.")
    seg_ids = {s.get("segmentId") for s in sequences} - {None}
    marker_ids = {s.get("markerId") for s in sequences} - {None}
    found_seg = set(FieldSegment.objects.filter(pk__in=seg_ids).values_list("pk", flat=True))
    found_mk = set(Marker.objects.filter(pk__in=marker_ids).values_list("pk", flat=True))
    errors = []
    existing = {s.pk: s for s in CaptureSequence.objects.filter(pk__in=[x["sequenceId"] for x in sequences])}
    numbers = {(s.monitoring_pass_id, s.sequence_number): s.pk
               for s in CaptureSequence.objects.filter(monitoring_pass_id__in=pass_ids)}
    for i, s in enumerate(sequences):
        if s.get("segmentId") and s["segmentId"] not in found_seg:
            errors.append(_campo(f"sequences[{i}].segmentId", f"Segmento desconocido: {s['segmentId']}."))
        if s.get("markerId") and s["markerId"] not in found_mk:
            errors.append(_campo(f"sequences[{i}].markerId", f"Marcador desconocido: {s['markerId']}."))
        prev = existing.get(s["sequenceId"])
        if prev is not None and prev.session_id != session.pk:
            errors.append(_campo(f"sequences[{i}].sequenceId", "La secuencia pertenece a otra sesión."))
        other = numbers.get((s["passId"], s["sequenceNumber"]))
        if other is not None and other != s["sequenceId"]:
            errors.append(_campo(f"sequences[{i}].sequenceNumber", "Ese número ya existe en la pasada con otro ID."))
    if errors:
        raise ApiError("VALIDATION_ERROR", 400, field_errors=errors)

    accepted = duplicates = 0
    with transaction.atomic():
        for s in sequences:
            _, created = CaptureSequence.objects.update_or_create(
                sequence_id=s["sequenceId"],
                defaults={
                    "monitoring_pass": passes[s["passId"]], "session": session,
                    "sequence_number": s["sequenceNumber"], "mode": s["mode"], "status": s["status"],
                    "segment_id": s.get("segmentId"), "marker_id": s.get("markerId"),
                    "lat": s.get("lat"), "lon": s.get("lon"), "gps_accuracy_m": s.get("gpsAccuracyM"),
                    "gps_timestamp": s.get("gpsTimestamp"), "issued_at": s["issuedAt"],
                    "completed_at": s.get("completedAt"),
                    "expected_capture_ids": {k: str(v) for k, v in (s.get("expectedCaptureIds") or {}).items()},
                    "slot_outcomes": dict(s.get("slotOutcomes") or {}),
                })
            if created:
                accepted += 1
            else:
                duplicates += 1
    return {"accepted": accepted, "duplicates": duplicates}


def upsert_incidents(session_id, incidents):
    session = get_session(session_id)
    pass_ids = {i.get("passId") for i in incidents} - {None}
    seq_ids = {i.get("sequenceId") for i in incidents} - {None}
    passes = set(MonitoringPass.objects.filter(pk__in=pass_ids, session=session).values_list("pk", flat=True))
    if pass_ids - passes:
        raise ApiError("PASS_NOT_FOUND", 404)
    seqs = set(CaptureSequence.objects.filter(pk__in=seq_ids, session=session).values_list("pk", flat=True))
    if seq_ids - seqs:
        raise ApiError("SEQUENCE_NOT_FOUND", 404)
    accepted = duplicates = 0
    with transaction.atomic():
        for inc in incidents:
            _, created = Incident.objects.update_or_create(
                incident_id=inc["incidentId"],
                defaults={"session": session, "monitoring_pass_id": inc.get("passId"),
                          "sequence_id": inc.get("sequenceId"), "capture_id": inc.get("captureId"),
                          "device_id": inc.get("deviceId"), "type": inc["type"], "severity": inc["severity"],
                          "detail": inc["detail"], "occurred_at": inc["occurredAt"], "created_by": inc["createdBy"]})
            if created:
                accepted += 1
            else:
                duplicates += 1
    if accepted:
        log.info("Sesión %s: %s incidencia(s) nueva(s)", str(session.pk)[:8], accepted)
    return {"accepted": accepted, "duplicates": duplicates}
