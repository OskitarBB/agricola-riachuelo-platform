# revision/models.py — Casos y decisiones del especialista (tablas review_cases, human_reviews).
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from cuentas.models import User
from evidencias.models import Capture
from ia.models import AiTask
from monitoreo.models import CaptureSequence, LateralCode, MonitoringPass, MonitoringSession
from config.restricciones import checks_de_opciones


class ReviewStatus(models.TextChoices):
    PENDIENTE_REVISION = "PENDIENTE_REVISION", "Pendiente de revisión"
    CONFIRMADO_POR_ESPECIALISTA = "CONFIRMADO_POR_ESPECIALISTA", "Confirmado por especialista"
    DESCARTADO = "DESCARTADO", "Descartado"
    EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE", "Evidencia insuficiente"
    # v1.3 (ADR-W-007): la IA confirma sola cuando la confianza supera model_configs.auto_confirm_threshold (se avisa
    # por WhatsApp sin esperar al especialista, que igual puede corregirlo); el especialista puede dejar un caso como
    # «posible plaga» para que el encargado vaya a verlo (visible en la app, sin WhatsApp).
    CONFIRMADO_POR_IA = "CONFIRMADO_POR_IA", "Confirmado por IA"
    POSIBLE_PLAGA = "POSIBLE_PLAGA", "Posible plaga"


DECISIONS = (
    ReviewStatus.CONFIRMADO_POR_ESPECIALISTA,
    ReviewStatus.POSIBLE_PLAGA,
    ReviewStatus.DESCARTADO,
    ReviewStatus.EVIDENCIA_INSUFICIENTE,
)
# Casos que el especialista todavía puede decidir con «Decidir» (los demás se corrigen con «Corregir»).
DECIDIBLES = (ReviewStatus.PENDIENTE_REVISION, ReviewStatus.CONFIRMADO_POR_IA)
# v1.3: estados que se muestran en «Ubicar plaga» de la app (los descartados y la evidencia insuficiente no).
VISIBLES_EN_APP = (ReviewStatus.CONFIRMADO_POR_IA, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, ReviewStatus.POSIBLE_PLAGA,
                   ReviewStatus.PENDIENTE_REVISION)
# Estados que generan aviso por WhatsApp.
CON_AVISO = (ReviewStatus.CONFIRMADO_POR_IA, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA)


class CaseNotificationStatus(models.TextChoices):
    NO_APLICA = "NO_APLICA", "No aplica"
    PENDIENTE_ENVIO = "PENDIENTE_ENVIO", "Pendiente de envío"
    ENVIADO = "ENVIADO", "Enviado"
    ERROR_ENVIO = "ERROR_ENVIO", "Error de envío"


class LocationSource(models.TextChoices):
    GPS = "GPS", "GPS del controlador"
    MARCADOR = "MARCADOR", "Coordenadas del marcador (aproximada)"
    NINGUNA = "NINGUNA", "Sin coordenadas"


@checks_de_opciones
class Case(models.Model):
    """(web v1.0) Unidad de revisión: una foto (captura) con su análisis. Se abre cuando la IA sugiere un indicio
    (origen IA) o cuando el especialista revisa una foto sin indicios o con error de análisis (origen MANUAL)."""

    class Origin(models.TextChoices):
        IA = "IA", "Indicio sugerido por IA"
        MANUAL = "MANUAL", "Abierto por el especialista"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.OneToOneField(Capture, on_delete=models.PROTECT, related_name="case")
    ai_task = models.ForeignKey(AiTask, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    origin = models.CharField(max_length=8, choices=Origin.choices)
    status = models.CharField(max_length=28, choices=ReviewStatus.choices, default=ReviewStatus.PENDIENTE_REVISION)
    notification_status = models.CharField(max_length=16, choices=CaseNotificationStatus.choices,
                                           default=CaseNotificationStatus.NO_APLICA)
    detections_count = models.PositiveIntegerField(default=0)
    max_confidence = models.FloatField(null=True, blank=True)
    # Ubicación copiada al abrir el caso (consultas rápidas del mapa, del plano y de la bandeja; RNF-W01).
    session = models.ForeignKey(MonitoringSession, on_delete=models.PROTECT, related_name="+")
    monitoring_pass = models.ForeignKey(MonitoringPass, on_delete=models.PROTECT, related_name="+",
                                        db_column="pass_id")
    sequence = models.ForeignKey(CaptureSequence, on_delete=models.PROTECT, related_name="+")
    lot = models.ForeignKey(FieldLot, on_delete=models.PROTECT, related_name="+")
    row = models.ForeignKey(FieldRow, on_delete=models.PROTECT, related_name="+")
    lateral_code = models.CharField(max_length=10, choices=LateralCode.choices)
    segment = models.ForeignKey(FieldSegment, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    marker = models.ForeignKey(Marker, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    gps_accuracy_m = models.FloatField(null=True, blank=True)
    location_source = models.CharField(max_length=10, choices=LocationSource.choices)
    captured_at = models.DateTimeField()
    opened_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "review_cases"
        indexes = [
            models.Index(fields=["status", "opened_at"], name="caso_bandeja_idx"),
            models.Index(fields=["lot", "row", "status"], name="caso_plano_idx"),
            models.Index(fields=["captured_at"], name="caso_fecha_idx"),
        ]
        verbose_name = "caso"

    def __str__(self):
        return f"Caso {str(self.id)[:8]}"


@checks_de_opciones
class HumanReview(models.Model):
    """Decisión del especialista. Nunca se edita ni se borra: una corrección crea otra fila (supersedes)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="reviews")
    ai_task = models.ForeignKey(AiTask, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=28, choices=[(d.value, d.label) for d in DECISIONS])
    observation = models.TextField(blank=True)
    confirmed_class = models.CharField(max_length=60, blank=True)
    rejected_detection_ids = models.JSONField(default=list, blank=True)  # cajas que el especialista marcó incorrectas
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(default=timezone.now)
    supersedes = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="superseded_by")
    correction_reason = models.TextField(blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "human_reviews"
        ordering = ["reviewed_at"]
        constraints = [models.UniqueConstraint(fields=["case"], condition=Q(is_current=True),
                                               name="una_decision_vigente_por_caso")]
        verbose_name = "decisión del especialista"
        verbose_name_plural = "decisiones del especialista"
