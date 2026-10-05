# ia/models.py — Modelos de detector, cola de análisis y cajas (tablas model_configs, ai_tasks, detections).
import uuid

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from evidencias.models import Capture
from config.restricciones import checks_de_opciones


class ModelConfig(models.Model):
    name = models.CharField(max_length=60)  # p. ej. "yolo11n-chanchito"
    version = models.CharField(max_length=40, unique=True)
    weights_uri = models.CharField(max_length=255)
    weights_sha256 = models.CharField(max_length=64, blank=True)
    classes = models.JSONField(default=list)  # clases que el modelo puede sugerir
    conf_threshold = models.FloatField(default=0.25)
    iou_threshold = models.FloatField(default=0.45)
    imgsz = models.PositiveIntegerField(default=640)
    tiling = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "model_configs"
        constraints = [models.UniqueConstraint(fields=["active"], condition=Q(active=True),
                                               name="un_solo_modelo_activo")]
        verbose_name = "modelo de IA"
        verbose_name_plural = "modelos de IA"

    def __str__(self):
        return f"{self.name} {self.version}"


class AiStatus(models.TextChoices):
    PENDIENTE_DE_ANALISIS = "PENDIENTE_DE_ANALISIS", "Pendiente de análisis"
    EN_ANALISIS = "EN_ANALISIS", "En análisis"
    INDICIO_SUGERIDO_POR_IA = "INDICIO_SUGERIDO_POR_IA", "Indicio sugerido por IA"
    SIN_INDICIOS_IA = "SIN_INDICIOS_IA", "Sin indicios de la IA"
    ERROR_DE_ANALISIS = "ERROR_DE_ANALISIS", "Error de análisis"


@checks_de_opciones
class AiTask(models.Model):
    task_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.ForeignKey(Capture, on_delete=models.PROTECT, related_name="ai_tasks")
    model_config = models.ForeignKey(ModelConfig, on_delete=models.PROTECT, related_name="tasks")
    status = models.CharField(max_length=24, choices=AiStatus.choices, default=AiStatus.PENDIENTE_DE_ANALISIS)
    requested_at = models.DateTimeField(default=timezone.now)
    available_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=80, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    processing_ms = models.PositiveIntegerField(null=True, blank=True)
    model_version = models.CharField(max_length=40, blank=True)
    # (web v1.0) Tamaño de la imagen tal como la analizó el worker (después de aplicar la orientación EXIF).
    # Las cajas están en píxeles de esta imagen; la web usa estos valores para el viewBox del visor.
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    raw_output = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "ai_tasks"
        constraints = [models.UniqueConstraint(fields=["capture", "model_config"], name="ai_task_por_modelo")]
        indexes = [models.Index(fields=["status", "available_at"], name="ai_cola_idx")]
        verbose_name = "tarea de IA"
        verbose_name_plural = "tareas de IA"


class DetectionReview(models.TextChoices):
    PENDIENTE_REVISION = "PENDIENTE_REVISION", "Pendiente de revisión"
    CONFIRMADO_POR_ESPECIALISTA = "CONFIRMADO_POR_ESPECIALISTA", "Confirmada"
    DESCARTADO = "DESCARTADO", "Descartada"
    EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE", "Evidencia insuficiente"


@checks_de_opciones
class Detection(models.Model):
    task = models.ForeignKey(AiTask, on_delete=models.CASCADE, related_name="detections")
    class_name = models.CharField(max_length=60)
    confidence = models.FloatField()
    x_min = models.FloatField()
    y_min = models.FloatField()
    x_max = models.FloatField()
    y_max = models.FloatField()
    review_status = models.CharField(max_length=28, choices=DetectionReview.choices,
                                     default=DetectionReview.PENDIENTE_REVISION)

    class Meta:
        db_table = "detections"
        ordering = ["-confidence"]
        constraints = [
            models.CheckConstraint(condition=Q(confidence__gte=0) & Q(confidence__lte=1), name="det_confianza"),
            models.CheckConstraint(condition=Q(x_min__lt=F("x_max")) & Q(y_min__lt=F("y_max")), name="det_caja"),
        ]
        verbose_name = "caja"

    @property
    def box_width(self):
        return self.x_max - self.x_min

    @property
    def box_height(self):
        return self.y_max - self.y_min
