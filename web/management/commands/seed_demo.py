"""Seed local demo data for a quick responsive UI check."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from cuentas.models import AccountStatus, MobileDevice, Role, User, UserRole
from evidencias.models import Capture, QualityStatus
from ia.models import AITask, Detection, ModelConfig, TaskStatus
from monitoreo.models import CropRow, Farm, FieldPass, Lot, MonitoringSession, SessionStatus
from notificaciones.models import NotificationRecipient
from revision.models import ReviewStatus
from revision.services import decide_case, open_case_for_capture


class Command(BaseCommand):
    help = "Creates a small local dataset and demo users for runserver."

    def handle(self, *args, **options):
        admin, _ = User.objects.get_or_create(
            email="admin@riachuelo.local",
            defaults={
                "username": "admin@riachuelo.local",
                "full_name": "Admin Riachuelo",
                "status": AccountStatus.ACTIVO,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin.set_password("Admin12345!")
        admin.save()
        for role in [Role.ADMINISTRADOR, Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR]:
            UserRole.objects.get_or_create(user=admin, role=role)

        specialist, _ = User.objects.get_or_create(
            email="especialista@riachuelo.local",
            defaults={"username": "especialista@riachuelo.local", "full_name": "Paula Reyes", "status": AccountStatus.ACTIVO},
        )
        specialist.set_password("Demo12345!")
        specialist.save()
        UserRole.objects.get_or_create(user=specialist, role=Role.ESPECIALISTA_FITOSANITARIO)

        farm, _ = Farm.objects.get_or_create(name="Fundo Los Angeles", defaults={"location": "Ica"})
        lot_d, _ = Lot.objects.get_or_create(farm=farm, code="Lote D", defaults={"crop": "Vid", "area_ha": Decimal("4.50")})
        lot_f, _ = Lot.objects.get_or_create(farm=farm, code="Lote F", defaults={"crop": "Vid", "area_ha": Decimal("3.80")})
        row_d18, _ = CropRow.objects.get_or_create(lot=lot_d, number=18, defaults={"label": "Hilera 18"})
        row_f03, _ = CropRow.objects.get_or_create(lot=lot_f, number=3, defaults={"label": "Hilera 3"})

        device, _ = MobileDevice.objects.get_or_create(
            code="VW-L-001",
            defaults={"owner": specialist, "label": "Camara izquierda", "platform": "iPhone", "battery_percent": 84, "last_sync_at": timezone.now()},
        )
        session, _ = MonitoringSession.objects.get_or_create(
            code="2026-10-04-001",
            defaults={"operator": specialist, "lot": lot_d, "started_at": timezone.now(), "status": SessionStatus.SINCRONIZADA},
        )
        field_pass, _ = FieldPass.objects.get_or_create(
            session=session,
            row=row_d18,
            defaults={"started_at": timezone.now(), "direction": "Norte-Sur"},
        )
        model, _ = ModelConfig.objects.get_or_create(name="YOLO Fito", version="demo", defaults={"is_active": True})
        NotificationRecipient.objects.get_or_create(name="Jefe de fundo", phone_e164="+51999999999", defaults={"lot": lot_d})

        samples = [
            ("oidio", lot_d, row_d18, "-14.0711000", "-75.7331000", ReviewStatus.PENDIENTE_REVISION),
            ("botrytis", lot_d, row_d18, "-14.0720000", "-75.7342000", ReviewStatus.CONFIRMADO_POR_ESPECIALISTA),
            ("oidio", lot_f, row_f03, "-14.0684000", "-75.7309000", ReviewStatus.DESCARTADO),
        ]
        for idx, (disease, lot, row, lat, lon, status) in enumerate(samples, start=1):
            capture, _ = Capture.objects.get_or_create(
                cloudinary_public_id=f"riachuelo/demo/capture-{idx}",
                defaults={
                    "session": session,
                    "pass_record": field_pass,
                    "row": row,
                    "device": device,
                    "captured_at": timezone.now(),
                    "latitude": Decimal(lat),
                    "longitude": Decimal(lon),
                    "quality_status": QualityStatus.UTILIZABLE,
                    "cloudinary_bytes": 3900000,
                    "cloudinary_format": "jpg",
                },
            )
            task, _ = AITask.objects.get_or_create(capture=capture, defaults={"model_config": model, "status": TaskStatus.INDICIO_SUGERIDO_POR_IA})
            Detection.objects.get_or_create(task=task, label=disease, defaults={"confidence": Decimal("0.92"), "bbox": {"x": 40, "y": 28, "w": 18, "h": 22}})
            case = open_case_for_capture(capture, disease=disease, confidence=Decimal("0.92"))
            if case.status == ReviewStatus.PENDIENTE_REVISION and status != ReviewStatus.PENDIENTE_REVISION:
                decide_case(case.pk, specialist, status, "Dato demo")

        self.stdout.write(self.style.SUCCESS("Demo ready: admin@riachuelo.local / Admin12345!"))
