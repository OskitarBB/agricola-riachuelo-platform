"""AI queue models.

YOLO runs in a separate worker process. HTTP requests only enqueue, inspect or
requeue tasks; they never perform image analysis.
"""
import uuid

from django.db import models


class ModelConfig(models.Model):
    model_config_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    weights_ref = models.CharField(max_length=255, blank=True)
    conf_threshold = models.DecimalField(max_digits=4, decimal_places=2, default=0.50)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "model_configs"
        ordering = ["-is_active", "name", "version"]

    def __str__(self):
        return f"{self.name} {self.version}"


class TaskStatus(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    TOMADA = "TOMADA", "Tomada"
    INDICIO_SUGERIDO_POR_IA = "INDICIO_SUGERIDO_POR_IA", "Indicio sugerido"
    SIN_INDICIOS = "SIN_INDICIOS", "Sin indicios"
    ERROR = "ERROR", "Error"


class AITask(models.Model):
    task_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.OneToOneField("evidencias.Capture", on_delete=models.CASCADE, related_name="ai_task")
    model_config = models.ForeignKey(ModelConfig, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=40, choices=TaskStatus.choices, default=TaskStatus.PENDIENTE)
    requested_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=120, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "ai_tasks"
        ordering = ["requested_at"]
        indexes = [models.Index(fields=["status", "available_at"], name="idx_ai_task_queue")]

    def __str__(self):
        return f"{self.task_id} - {self.status}"


class DetectionReview(models.TextChoices):
    SIN_REVISION = "SIN_REVISION", "Sin revision"
    CONFIRMADO = "CONFIRMADO", "Confirmado"
    DESCARTADO = "DESCARTADO", "Descartado"


class Detection(models.Model):
    detection_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(AITask, on_delete=models.CASCADE, related_name="detections")
    label = models.CharField(max_length=80)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    bbox = models.JSONField(default=dict)
    review_status = models.CharField(max_length=20, choices=DetectionReview.choices, default=DetectionReview.SIN_REVISION)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "detections"
        ordering = ["-confidence"]

    def __str__(self):
        return f"{self.label} {self.confidence}"
