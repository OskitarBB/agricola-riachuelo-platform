# evidencias/models.py — Capturas confirmadas y su calidad (tablas captures, quality_results).
# Una fila en `captures` significa: foto en Cloudinary + confirmación aceptada por Django (RN-23 del maestro móvil).
from django.db import models
from django.utils import timezone

from cuentas.models import Device, User
from monitoreo.models import CameraRole, CaptureSequence, LateralCode, MonitoringPass, MonitoringSession
from config.restricciones import checks_de_opciones


class QualityStatus(models.TextChoices):
    UTILIZABLE = "UTILIZABLE", "Utilizable"
    REPETIR_NITIDEZ = "REPETIR_NITIDEZ", "Repetir por nitidez"
    REPETIR_EXPOSICION = "REPETIR_EXPOSICION", "Repetir por exposición"
    ERROR_CAMARA = "ERROR_CAMARA", "Error de cámara"
    PENDIENTE_REVISION_TECNICA = "PENDIENTE_REVISION_TECNICA", "Pendiente de revisión técnica"


# Solo estas capturas se analizan con IA (RN-W11). Las rechazadas se guardan para auditoría y calibración.
ANALYZABLE_QUALITY = (QualityStatus.UTILIZABLE, QualityStatus.PENDIENTE_REVISION_TECNICA)


@checks_de_opciones
class Capture(models.Model):
    capture_id = models.UUIDField(primary_key=True)
    sequence = models.ForeignKey(CaptureSequence, on_delete=models.PROTECT, related_name="captures")
    session = models.ForeignKey(MonitoringSession, on_delete=models.PROTECT, related_name="captures")
    monitoring_pass = models.ForeignKey(MonitoringPass, on_delete=models.PROTECT, related_name="captures",
                                        db_column="pass_id")
    lateral_code = models.CharField(max_length=10, choices=LateralCode.choices)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="+")
    camera_role = models.CharField(max_length=10, choices=CameraRole.choices)
    camera_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    operator_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    captured_at = models.DateTimeField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    size_bytes = models.PositiveBigIntegerField()
    md5 = models.CharField(max_length=32)
    quality_status = models.CharField(max_length=28, choices=QualityStatus.choices)
    # Sin restricción de clave foránea: la repetición puede confirmarse antes que la foto que reemplaza.
    replaces_capture = models.ForeignKey("self", null=True, blank=True, on_delete=models.DO_NOTHING,
                                         db_constraint=False, related_name="replaced_by")
    retake_context = models.JSONField(null=True, blank=True)
    app_version = models.CharField(max_length=40)
    cloudinary_public_id = models.CharField(max_length=255, unique=True)
    cloudinary_version = models.BigIntegerField()
    cloudinary_bytes = models.PositiveBigIntegerField()
    cloudinary_format = models.CharField(max_length=10, blank=True)
    cloudinary_width = models.PositiveIntegerField(null=True, blank=True)
    cloudinary_height = models.PositiveIntegerField(null=True, blank=True)
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "captures"
        indexes = [models.Index(fields=["captured_at"], name="captura_fecha_idx")]
        verbose_name = "captura"

    def __str__(self):
        return str(self.capture_id)


@checks_de_opciones
class QualityResult(models.Model):
    capture = models.OneToOneField(Capture, primary_key=True, on_delete=models.CASCADE, related_name="quality")
    status = models.CharField(max_length=28, choices=QualityStatus.choices)
    reasons = models.JSONField(default=list)
    metrics = models.JSONField(null=True, blank=True)
    profile_version = models.CharField(max_length=20)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "quality_results"
