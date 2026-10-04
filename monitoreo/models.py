"""Field monitoring entities synchronized by the mobile app."""
import uuid

from django.conf import settings
from django.db import models


class Farm(models.Model):
    farm_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "farms"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Lot(models.Model):
    lot_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="lots")
    code = models.CharField(max_length=40)
    crop = models.CharField(max_length=80, default="Vid")
    area_ha = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    geojson = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "lots"
        ordering = ["farm__name", "code"]
        constraints = [models.UniqueConstraint(fields=["farm", "code"], name="uniq_lot_per_farm")]

    def __str__(self):
        return f"{self.farm} / {self.code}"


class CropRow(models.Model):
    row_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lot = models.ForeignKey(Lot, on_delete=models.CASCADE, related_name="rows")
    number = models.PositiveIntegerField()
    label = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "crop_rows"
        ordering = ["lot__code", "number"]
        constraints = [models.UniqueConstraint(fields=["lot", "number"], name="uniq_row_per_lot")]

    def __str__(self):
        return self.label or f"Hilera {self.number}"


class SessionStatus(models.TextChoices):
    ABIERTA = "ABIERTA", "Abierta"
    SINCRONIZADA = "SINCRONIZADA", "Sincronizada"
    CERRADA = "CERRADA", "Cerrada"


class MonitoringSession(models.Model):
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=60, unique=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    lot = models.ForeignKey(Lot, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=SessionStatus.choices, default=SessionStatus.ABIERTA)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monitoring_sessions"
        ordering = ["-started_at"]

    def __str__(self):
        return self.code


class CameraSide(models.TextChoices):
    IZQUIERDA = "IZQUIERDA", "Izquierda"
    DERECHA = "DERECHA", "Derecha"
    FRONTAL = "FRONTAL", "Frontal"


class SessionCamera(models.Model):
    camera_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="cameras")
    device = models.ForeignKey("cuentas.MobileDevice", null=True, blank=True, on_delete=models.SET_NULL)
    side = models.CharField(max_length=16, choices=CameraSide.choices)
    label = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "session_cameras"
        constraints = [models.UniqueConstraint(fields=["session", "side"], name="uniq_camera_side_per_session")]

    def __str__(self):
        return f"{self.session} - {self.get_side_display()}"


class FieldPass(models.Model):
    pass_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="passes")
    row = models.ForeignKey(CropRow, null=True, blank=True, on_delete=models.SET_NULL, related_name="passes")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    direction = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "field_passes"
        ordering = ["session", "started_at"]

    def __str__(self):
        return f"{self.session} / {self.row or 'sin hilera'}"
