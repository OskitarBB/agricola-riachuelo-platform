# web/tests/factories.py — Datos mínimos y deterministas para las pruebas (sin depender de web/demo.py).
import hashlib
import uuid
from datetime import timedelta

from django.utils import timezone

from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from cuentas.models import AccountStatus, Device, Role, User
from evidencias.models import Capture, QualityResult, QualityStatus
from ia import services as ia
from ia.models import ModelConfig
from monitoreo.models import CaptureSequence, MonitoringPass, MonitoringSession
from notificaciones.models import NotificationRecipient

PASSWORD = "Clave-segura-2026"


def user(email, *roles, status=AccountStatus.ACTIVO, **extra):
    return User.objects.create_user(email, PASSWORD, roles=roles, full_name=email.split("@")[0].title(),
                                    status=status, **extra)


def world():
    """Catálogo pequeño (2 lotes), usuarios de cada rol, una sesión con una pasada y un modelo activo."""
    w = type("World", (), {})()
    w.lot = FieldLot.objects.create(id="SWG1", code="SWG 1", name="Lote 1 (Piscina)")
    w.lot2 = FieldLot.objects.create(id="SWG2", code="SWG 2", name="Lote 2 (Maíz)")
    w.row = FieldRow.objects.create(id="SWG1-H05", lot=w.lot, number=5, plant_count=385)
    w.row_b = FieldRow.objects.create(id="SWG1-H06", lot=w.lot, number=6, plant_count=386)
    w.row2 = FieldRow.objects.create(id="SWG2-H01", lot=w.lot2, number=1, plant_count=251)
    w.segment = FieldSegment.objects.create(id="SWG1-S1", row=w.row, code="SWG 1-S1", start_plant=180,
                                            end_plant=204, is_pilot=True)
    w.marker = Marker.objects.create(id="SWG1-M1", row=w.row, segment=w.segment, code="M1", position="INICIO",
                                     lat=-14.06, lon=-75.73)
    w.model = ModelConfig.objects.create(name="det", version="v1", weights_uri="x", classes=["chanchito_blanco"],
                                         active=True)
    w.admin = user("admin@x.pe", Role.ADMINISTRADOR, is_staff=True)
    w.esp = user("esp@x.pe", Role.ESPECIALISTA_FITOSANITARIO)
    w.esp2 = user("esp2@x.pe", Role.ESPECIALISTA_FITOSANITARIO)
    w.sup = user("sup@x.pe", Role.SUPERVISOR)
    w.op = user("op@x.pe", Role.OPERADOR_CAMPO)
    w.device = Device.objects.create(device_id=uuid.uuid4(), platform="android", model="Moto", user=w.op)
    now = timezone.now()
    w.session = MonitoringSession.objects.create(
        session_id=uuid.uuid4(), operator=w.op, controller_device=w.device, status="CLOSED", mode="MANUAL",
        started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=1), app_version="0.3.0",
        config_version="CFG-4", quality_profile_version="Q0")
    w.pass_a = make_pass(w, w.row, "LATERAL_A")
    w.seq_n = 0
    return w


def make_pass(w, row, lateral, status="COMPLETED"):
    return MonitoringPass.objects.create(
        pass_id=uuid.uuid4(), session=w.session, lot=row.lot, row=row, lateral_code=lateral, pass_order=1,
        direction="ASCENDENTE", status=status, started_at=timezone.now() - timedelta(minutes=90))


def capture(w, gps=True, marker=True, quality=QualityStatus.UTILIZABLE, monitoring_pass=None, retake_context=None,
            role="CAMERA_1", sequence=None):
    p = monitoring_pass or w.pass_a
    if sequence is None:
        w.seq_n += 1
        sequence = CaptureSequence.objects.create(
            sequence_id=uuid.uuid4(), monitoring_pass=p, session=w.session, sequence_number=w.seq_n, mode="MANUAL",
            status="COMPLETE", segment=w.segment if marker else None, marker=w.marker if marker else None,
            lat=-14.0601 if gps else None, lon=-75.7302 if gps else None, gps_accuracy_m=4.0 if gps else None,
            issued_at=timezone.now() - timedelta(minutes=80))
    cid = uuid.uuid4()
    cap = Capture.objects.create(
        capture_id=cid, sequence=sequence, session=w.session, monitoring_pass=p, lateral_code=p.lateral_code,
        device=w.device, camera_role=role, camera_user=w.op, operator_user=w.op,
        captured_at=timezone.now() - timedelta(minutes=80), width=3000, height=4000, size_bytes=3_900_000,
        md5=hashlib.md5(str(cid).encode()).hexdigest(), quality_status=quality, app_version="0.3.0",
        retake_context=retake_context, cloudinary_public_id=f"riachuelo/dev/{w.session.pk}/{p.pk}/{cid}",
        cloudinary_version=1759500000, cloudinary_bytes=3_900_000, cloudinary_format="jpg")
    QualityResult.objects.create(capture=cap, status=quality, profile_version="Q0")
    return cap


BOX = {"class_name": "chanchito_blanco", "confidence": 0.81, "x_min": 100, "y_min": 200, "x_max": 400, "y_max": 520}


def analyzed(w, boxes=(BOX,), **kw):
    """Captura confirmada → tarea encolada → worker la toma → guarda resultado (abre caso si hay cajas)."""
    cap = capture(w, **kw)
    ia.enqueue_analysis(cap)
    task = ia.claim_next_task("test")
    task, case = ia.save_analysis_result(task, list(boxes), 3000, 4000, 120, "v1", {"ok": True})
    return cap, task, case


def recipient(name="Jefe", phone="+51987654321", lots=(), opt_in=True, active=True, **extra):
    r = NotificationRecipient.objects.create(full_name=name, phone_e164=phone, role_label="JEFE_FUNDO",
                                             opt_in_at=timezone.now() if opt_in else None, active=active, **extra)
    if lots:
        r.lots.set(lots)
    return r
