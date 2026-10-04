"""Evidence captured by the mobile app and reviewed by specialists."""
import uuid

from django.db import models


class QualityStatus(models.TextChoices):
    UTILIZABLE = "UTILIZABLE", "Utilizable"
    RECHAZADA = "RECHAZADA", "Rechazada"
    PENDIENTE = "PENDIENTE", "Pendiente"


class Capture(models.Model):
    capture_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey("monitoreo.MonitoringSession", null=True, blank=True, on_delete=models.SET_NULL, related_name="captures")
    pass_record = models.ForeignKey("monitoreo.FieldPass", null=True, blank=True, on_delete=models.SET_NULL, related_name="captures")
    row = models.ForeignKey("monitoreo.CropRow", null=True, blank=True, on_delete=models.SET_NULL, related_name="captures")
    device = models.ForeignKey("cuentas.MobileDevice", null=True, blank=True, on_delete=models.SET_NULL, related_name="captures")
    captured_at = models.DateTimeField()
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    marker_code = models.CharField(max_length=80, blank=True)
    quality_status = models.CharField(max_length=20, choices=QualityStatus.choices, default=QualityStatus.PENDIENTE)
    cloudinary_public_id = models.CharField(max_length=255, unique=True)
    cloudinary_version = models.PositiveBigIntegerField(null=True, blank=True)
    cloudinary_bytes = models.PositiveIntegerField(default=0)
    cloudinary_format = models.CharField(max_length=20, default="jpg")
    cloudinary_width = models.PositiveIntegerField(null=True, blank=True)
    cloudinary_height = models.PositiveIntegerField(null=True, blank=True)
    replaces_capture = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "captures"
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["quality_status", "-captured_at"], name="idx_capture_quality_time"),
            models.Index(fields=["latitude", "longitude"], name="idx_capture_location"),
        ]

    def __str__(self):
        return str(self.capture_id)

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None


class QualityResult(models.Model):
    result_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.OneToOneField(Capture, on_delete=models.CASCADE, related_name="quality_result")
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=180, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quality_results"

    def __str__(self):
        return f"{self.capture_id} - {self.score}"
