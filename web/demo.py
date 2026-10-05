# web/demo.py — Datos de demostración para desarrollar la web sin la app (T-W02). NUNCA en el entorno piloto.
# Catálogos: lotes del piloto del Anexo D del maestro móvil. Segmentos, marcadores y coordenadas son FICTICIOS (Q-01).
# Base: Anexo G.2 del Maestro Web. v1.0+: cuentas iguales a las del backend simulado de la app (§15.6), decisiones,
# destinatarios y avisos de ejemplo para que el panel, el mapa y los avisos tengan contenido.
import hashlib
import random
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from auditoria import services as audit
from auditoria.models import AuditEvent
from campo.models import FieldLot, FieldRow, FieldSegment, Marker, QualityProfile
from cuentas.models import AccountStatus, Device, PasswordResetRequest, Role, User
from evidencias.models import Capture, QualityResult, QualityStatus
from ia import services as ia
from ia.models import AiStatus, AiTask, ModelConfig
from monitoreo.models import CaptureSequence, Incident, MonitoringPass, MonitoringSession, SessionDevice
from notificaciones.models import Notification, NotificationRecipient, NotificationStatus
from revision import services as revision
from revision.models import Case, HumanReview, ReviewStatus

PILOT_PLANTS_PER_ROW = {
    "SWG1": [383, 384, 381, 384, 385, 386, 384, 385, 386, 384, 388, 388, 391, 382, 275, 275, 274, 273, 273, 273, 272,
             270, 268, 270, 269, 269, 268, 268, 267, 266, 265],
    "SWG2": [251, 260, 267, 273, 279, 286, 292, 299, 307, 313, 319, 326, 332, 339, 347, 351],
    "SWG5": [11, 19, 25, 33, 40, 47, 54, 62, 68, 75, 84, 91, 97, 104, 111, 118, 126, 132, 138, 146, 154, 161, 168,
             174, 181, 188, 194, 200, 207, 213, 220, 223, 233, 239, 246, 250],
}
PILOT_LOTS = [("SWG1", "SWG 1", "Lote 1 (Piscina)"), ("SWG2", "SWG 2", "Lote 2 (Maíz)"),
              ("SWG5", "SWG 5", "Lote 5 (Triángulo)")]
DEMO_ORIGIN = {"SWG1": (-14.0600, -75.7300), "SWG2": (-14.0640, -75.7300), "SWG5": (-14.0680, -75.7300)}  # FICTICIAS
ROW_SPACING_DEG, PLANT_SPACING_DEG = 0.000027, 0.000013  # ~3 m entre hileras, ~1,4 m entre plantas (ficticio)
DEMO_PASSWORD = "Demo2026"  # misma contraseña que el backend simulado de la app (§15.6 del maestro móvil)


def _plant_point(lot_id, row_number, plant):
    lat0, lon0 = DEMO_ORIGIN[lot_id]
    return lat0 - row_number * ROW_SPACING_DEG, lon0 + plant * PLANT_SPACING_DEG


@transaction.atomic
def crear_catalogos_piloto():
    for lot_id, code, name in PILOT_LOTS:
        rows = PILOT_PLANTS_PER_ROW[lot_id]
        lat0, lon0 = DEMO_ORIGIN[lot_id]
        lat1, lon1 = _plant_point(lot_id, len(rows) + 1, max(rows) + 1)
        geometry = {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1],
                                                        [lon0, lat0]]]}
        lot, _ = FieldLot.objects.update_or_create(id=lot_id, defaults={"code": code, "name": name,
                                                                         "geometry": geometry})
        for i, plants in enumerate(rows, 1):
            FieldRow.objects.update_or_create(id=f"{lot_id}-H{i:02d}",
                                              defaults={"lot": lot, "number": i, "plant_count": plants})
        # 4 segmentos piloto de 25 plantas por lote (FICTICIOS hasta Q-01)
        candidates = [n for n, p in enumerate(rows, 1) if p >= 60]
        for k, row_number in enumerate(candidates[:: max(1, len(candidates) // 4)][:4], 1):
            row = FieldRow.objects.get(id=f"{lot_id}-H{row_number:02d}")
            start = row.plant_count // 2 - 12
            seg, _ = FieldSegment.objects.update_or_create(
                id=f"{lot_id}-S{k}", defaults={"row": row, "code": f"{code}-S{k}", "start_plant": start,
                                               "end_plant": start + 24, "is_pilot": True})
            lat, lon = _plant_point(lot_id, row_number, start)
            Marker.objects.update_or_create(
                id=f"{lot_id}-M{k}", defaults={"row": row, "segment": seg, "code": f"M{k}-{lot_id}",
                                               "description": f"Inicio del segmento {k} (ficticio)",
                                               "position": "INICIO", "lat": lat, "lon": lon})
    QualityProfile.objects.get_or_create(version="Q0", defaults={"params": {}, "published_at": timezone.now()})
    ModelConfig.objects.get_or_create(version="demo-0", defaults={
        "name": "detector-demo", "weights_uri": "demo://sin-pesos", "classes": ["chanchito_blanco"], "active": True})


def crear_usuarios_demo(password=DEMO_PASSWORD):
    gente = [("admin@demo.pe", "Ana Administradora", [Role.ADMINISTRADOR], True, AccountStatus.ACTIVO, False),
             ("especialista@demo.pe", "Eduardo Especialista", [Role.ESPECIALISTA_FITOSANITARIO], False,
              AccountStatus.ACTIVO, False),
             ("supervisor@demo.pe", "Sofía Supervisora", [Role.SUPERVISOR], False, AccountStatus.ACTIVO, False),
             ("operador@demo.pe", "Óscar Operador", [Role.OPERADOR_CAMPO], False, AccountStatus.ACTIVO, False),
             ("temporal@demo.pe", "Tomás Temporal", [Role.OPERADOR_CAMPO], False, AccountStatus.ACTIVO, True),
             ("bloqueado@demo.pe", "Bruno Bloqueado", [Role.OPERADOR_CAMPO], False, AccountStatus.BLOQUEADO, False)]
    out = {}
    for email, name, roles, staff, status, temporal in gente:
        user = User.objects.filter(email=email).first()
        if user is None:
            clave = "Temp2026" if temporal else password
            user = User.objects.create_user(email, clave, roles=roles, full_name=name, is_staff=staff,
                                            status=status, must_change_password=temporal,
                                            approved_at=timezone.now() if status == AccountStatus.ACTIVO else None)
        out[email.split("@")[0]] = user
    User.objects.get_or_create(email="pendiente@demo.pe", defaults={
        "full_name": "Pedro Pendiente", "employee_code": "OP-031", "phone": "987654321",
        "accepted_privacy_notice_at": timezone.now()})
    if not PasswordResetRequest.objects.exists():
        PasswordResetRequest.objects.create(email="operador@demo.pe", user=out["operador"])
    return out


@transaction.atomic
def crear_evidencia_demo(operador, secuencias_por_pasada=12, semilla=7):
    """Una sesión por lote, pasadas A y B en las hileras con segmento, fotos «subidas» y análisis simulado."""
    rnd = random.Random(semilla)
    ahora = timezone.now()
    devices = {}
    for role, modelo in (("CONTROLADOR", "Galaxy A35"), ("CAMERA_1", "Redmi Note 13"), ("CAMERA_2", "Redmi Note 13")):
        devices[role], _ = Device.objects.get_or_create(
            device_id=uuid.uuid5(uuid.NAMESPACE_URL, f"demo-{role}"),
            defaults={"platform": "android", "model": modelo, "os_version": "14", "app_version": "0.3.0",
                      "user": operador})
    for d, (lot_id, _, _) in enumerate(PILOT_LOTS):
        inicio = ahora - timedelta(days=d + 1, hours=3)
        s = MonitoringSession.objects.create(
            session_id=uuid.uuid4(), operator=operador, controller_device=devices["CONTROLADOR"], status="CLOSED",
            mode="MANUAL", started_at=inicio, ended_at=inicio + timedelta(hours=2), app_version="0.3.0",
            config_version="CFG-4", quality_profile_version="Q0", short_test_passed_at=inicio)
        for role in ("CAMERA_1", "CAMERA_2"):
            SessionDevice.objects.create(session=s, role=role, device=devices[role], user=operador, platform="android",
                                         model=devices[role].model, os_version="14", app_version="0.3.0",
                                         paired_at=inicio)
        t = inicio
        for seg in FieldSegment.objects.filter(row__lot_id=lot_id).select_related("row"):
            for lateral in ("LATERAL_A", "LATERAL_B"):
                p = MonitoringPass.objects.create(
                    pass_id=uuid.uuid4(), session=s, lot_id=lot_id, row=seg.row, lateral_code=lateral, pass_order=1,
                    direction="ASCENDENTE" if lateral == "LATERAL_A" else "DESCENDENTE", status="COMPLETED",
                    started_at=t, ended_at=t + timedelta(minutes=10), sequences_total=secuencias_por_pasada,
                    sequences_complete=secuencias_por_pasada)
                for n in range(1, secuencias_por_pasada + 1):
                    t += timedelta(seconds=20)
                    planta = seg.start_plant + (n * 2) % 25
                    lat, lon = _plant_point(lot_id, seg.row.number, planta)
                    ids = {r: uuid.uuid4() for r in ("CAMERA_1", "CAMERA_2")}
                    seq = CaptureSequence.objects.create(
                        sequence_id=uuid.uuid4(), monitoring_pass=p, session=s, sequence_number=n, mode="MANUAL",
                        status="COMPLETE", segment=seg, marker=seg.markers.first(),
                        lat=lat if n % 5 else None, lon=lon if n % 5 else None,  # 1 de cada 5 sin GPS
                        gps_accuracy_m=rnd.choice([3.0, 5.0, 8.0]) if n % 5 else None, issued_at=t,
                        expected_capture_ids={k: str(v) for k, v in ids.items()},
                        slot_outcomes={"CAMERA_1": "OK_RECIBIDA", "CAMERA_2": "OK_RECIBIDA"})
                    for role, cid in ids.items():
                        q = QualityStatus.REPETIR_NITIDEZ if rnd.random() < 0.06 else QualityStatus.UTILIZABLE
                        cap = Capture.objects.create(
                            capture_id=cid, sequence=seq, session=s, monitoring_pass=p, lateral_code=lateral,
                            device=devices[role], camera_role=role, camera_user=operador, operator_user=operador,
                            captured_at=t, width=3000, height=4000, size_bytes=3_900_000,
                            md5=hashlib.md5(str(cid).encode()).hexdigest(), quality_status=q, app_version="0.3.0",
                            cloudinary_public_id=f"riachuelo/dev/{s.pk}/{p.pk}/{cid}", cloudinary_version=1700000000,
                            cloudinary_bytes=3_900_000, cloudinary_format="jpg")
                        QualityResult.objects.create(capture=cap, status=q, profile_version="Q0",
                                                     reasons=[] if q == QualityStatus.UTILIZABLE else ["NITIDEZ_BAJA"])
                        task = ia.enqueue_analysis(cap)
                        if task is None:
                            continue
                        task = ia.claim_next_task("demo")
                        boxes = []
                        if rnd.random() < 0.15:
                            for _ in range(rnd.randint(1, 3)):
                                x, y = rnd.uniform(200, 2500), rnd.uniform(1200, 3400)
                                boxes.append({"class_name": "chanchito_blanco",
                                              "confidence": round(rnd.uniform(0.3, 0.95), 3),
                                              "x_min": x, "y_min": y, "x_max": x + rnd.uniform(90, 320),
                                              "y_max": y + rnd.uniform(80, 260)})
                        ia.save_analysis_result(task, boxes, 3000, 4000, rnd.randint(80, 400), "demo-0",
                                                {"demo": True})
                t += timedelta(minutes=2)
        _retemporizar_sesion(s, operador, rnd)
        if d == 0:  # una incidencia de ejemplo
            Incident.objects.create(incident_id=uuid.uuid4(), session=s, monitoring_pass=p, type="GPS", severity="AVISO",
                                    detail="Señal GPS débil bajo el parrón; se usaron marcadores.",
                                    occurred_at=inicio + timedelta(minutes=40), created_by="SISTEMA")


def _auditoria_editable():
    """Solo demo (dev): permite ajustar la hora de eventos de auditoría dentro de la transacción en curso; el trigger
    de auditoria/migrations/0004 la bloquea en cualquier otro caso."""
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SET LOCAL riachuelo.auditoria_mantenimiento = 'on'")


def _retemporizar_sesion(s, operador, rnd):
    """La sesión «llega» por sincronización poco después de terminar (al volver a la red): fotos confirmadas, análisis
    y casos abiertos en ese momento, y sus eventos de auditoría con esa hora (actividad y tiempos del panel creíbles)."""
    llegada = s.ended_at + timedelta(minutes=rnd.randint(6, 20))
    _auditoria_editable()
    Capture.objects.filter(session=s).update(confirmed_at=llegada)
    for i, task in enumerate(AiTask.objects.filter(capture__session=s).order_by("capture__captured_at")):
        fin = llegada + timedelta(seconds=4 + i * 2)
        AiTask.objects.filter(pk=task.pk).update(requested_at=llegada, available_at=llegada, started_at=fin,
                                                 finished_at=fin)
    for case in Case.objects.filter(capture__session=s).select_related("ai_task"):
        abierto = case.ai_task.finished_at if case.ai_task_id else llegada
        Case.objects.filter(pk=case.pk).update(opened_at=abierto)
        AuditEvent.objects.filter(entity_type="case", entity_id=str(case.pk), action="CASO_ABIERTO").update(timestamp=abierto)
    audit.record("session", s.pk, "SESION_RECIBIDA", operador, None, {"status": "ACTIVE", "mode": s.mode, "cameras": 2,
                                                                       "appVersion": s.app_version})
    audit.record("session", s.pk, "SESION_CERRADA", operador, {"status": "ACTIVE"}, {"status": "CLOSED"})
    AuditEvent.objects.filter(entity_type="session", entity_id=str(s.pk)).update(timestamp=llegada)


@transaction.atomic
def crear_revision_demo(especialista, semilla=11):
    """v1.0+: destinatarios con consentimiento, ~35 % de casos decididos, avisos enviados/con error y una tarea con
    error de análisis, para que el panel, el mapa, el plano y los avisos muestren todos los estados."""
    rnd = random.Random(semilla)
    if not NotificationRecipient.objects.exists():
        jefe = NotificationRecipient.objects.create(full_name="Jefe de fundo (demo)", phone_e164="+51987000001",
                                                    role_label="JEFE_FUNDO", opt_in_at=timezone.now())
        sup = NotificationRecipient.objects.create(full_name="Supervisor zona SWG 1 (demo)",
                                                   phone_e164="+51987000002", role_label="SUPERVISOR_ZONA",
                                                   opt_in_at=timezone.now(),
                                                   user=User.objects.filter(email="supervisor@demo.pe").first())
        sup.lots.set(FieldLot.objects.filter(pk="SWG1"))
        NotificationRecipient.objects.create(full_name="Sin consentimiento (demo)", phone_e164="+51987000003",
                                             role_label="OTRO")
        _ = jefe
    observaciones = {
        ReviewStatus.CONFIRMADO_POR_ESPECIALISTA: ["Colonias algodonosas en el envés y en el racimo.",
                                                   "Ninfas y masas cerosas en la base del racimo.",
                                                   "Presencia clara de chanchito blanco en el cordón."],
        ReviewStatus.DESCARTADO: ["Restos de polvo y telaraña, no corresponde a plaga.", ""],
        ReviewStatus.EVIDENCIA_INSUFICIENTE: ["Foto desenfocada en la zona marcada; volver a mirar en campo.",
                                              "Ángulo no permite ver el envés; revisar el segmento."],
    }
    casos = list(Case.objects.filter(status=ReviewStatus.PENDIENTE_REVISION).order_by("opened_at"))
    rnd.shuffle(casos)
    ahora = timezone.now()
    _auditoria_editable()
    for case in casos[: int(len(casos) * 0.35)]:
        decision = rnd.choices(list(observaciones), weights=[5, 3, 2])[0]
        review = revision.decide_case(case.pk, especialista, decision, rnd.choice(observaciones[decision]),
                                      "chanchito_blanco" if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA else "")
        # Tiempos creíbles para el panel y la actividad: decidido entre 20 min y 5 h después de abrirse el caso.
        cuando = min(ahora - timedelta(minutes=rnd.randint(2, 30)),
                     case.opened_at + timedelta(minutes=rnd.randint(20, 300)))
        HumanReview.objects.filter(pk=review.pk).update(reviewed_at=cuando)
        Case.objects.filter(pk=case.pk).update(decided_at=cuando)
        AuditEvent.objects.filter(entity_type="case", entity_id=str(case.pk), action="CASO_DECIDIDO").update(timestamp=cuando)
        Notification.objects.filter(review=review).update(created_at=cuando, available_at=cuando)
    for i, n in enumerate(Notification.objects.order_by("created_at")):
        if i % 4 == 3:
            n.status, n.attempts, n.error = NotificationStatus.ERROR_ENVIO, 1, "HTTP 400: número no válido (demo)"
        else:
            n.status, n.attempts = NotificationStatus.ENVIADO, 1
            n.sent_at = n.created_at + timedelta(seconds=rnd.randint(3, 40))
            n.provider_message_id = f"wamid.demo{i}"
        n.save()
        case = n.case
        from notificaciones.services import case_notification_summary

        case.notification_status = case_notification_summary(case)
        case.save(update_fields=["notification_status"])
    t = AiTask.objects.filter(status=AiStatus.SIN_INDICIOS_IA).order_by("requested_at").first()
    if t is not None:
        t.status, t.attempts, t.error_message = AiStatus.ERROR_DE_ANALISIS, 3, "TimeoutError('descarga del original')"
        t.save()
