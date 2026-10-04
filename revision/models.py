"""Human review case models."""
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse


class ReviewStatus(models.TextChoices):
    PENDIENTE_REVISION = "PENDIENTE_REVISION", "Pendiente"
    CONFIRMADO_POR_ESPECIALISTA = "CONFIRMADO_POR_ESPECIALISTA", "Confirmado"
    DESCARTADO = "DESCARTADO", "Descartado"
    EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE", "Evidencia insuficiente"


class LocationSource(models.TextChoices):
    GPS = "GPS", "GPS"
    MARCADOR = "MARCADOR", "Marcador"
    SIN_UBICACION = "SIN_UBICACION", "Sin ubicacion"


class CaseNotificationStatus(models.TextChoices):
    SIN_AVISO = "SIN_AVISO", "Sin aviso"
    PENDIENTE = "PENDIENTE", "Pendiente"
    ENVIADO = "ENVIADO", "Enviado"
    ERROR = "ERROR", "Error"
    ANULADO = "ANULADO", "Anulado"


class Case(models.Model):
    case_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.OneToOneField("evidencias.Capture", on_delete=models.PROTECT, related_name="case")
    status = models.CharField(max_length=40, choices=ReviewStatus.choices, default=ReviewStatus.PENDIENTE_REVISION)
    notification_status = models.CharField(max_length=24, choices=CaseNotificationStatus.choices, default=CaseNotificationStatus.SIN_AVISO)
    disease = models.CharField(max_length=120, blank=True)
    severity = models.CharField(max_length=40, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    location_source = models.CharField(max_length=24, choices=LocationSource.choices, default=LocationSource.GPS)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "review_cases"
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["status", "-opened_at"], name="idx_case_status_time"),
            models.Index(fields=["latitude", "longitude"], name="idx_case_location"),
        ]

    def __str__(self):
        return f"{self.case_id} - {self.status}"

    def get_absolute_url(self):
        return reverse("web:caso", args=[self.pk])

    @property
    def lot(self):
        return self.capture.row.lot if self.capture and self.capture.row_id else None

    @property
    def row_label(self):
        return str(self.capture.row) if self.capture and self.capture.row_id else "Sin hilera"


class HumanReview(models.Model):
    review_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    from_status = models.CharField(max_length=40, choices=ReviewStatus.choices)
    to_status = models.CharField(max_length=40, choices=ReviewStatus.choices)
    observation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "human_reviews"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.case_id}: {self.from_status} -> {self.to_status}"
