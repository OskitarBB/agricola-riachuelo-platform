# monitoreo/models.py — Lo que sincroniza la app (tablas monitoring_sessions, session_devices, monitoring_passes,
# marker_changes, capture_sequences, incidents). La web solo LEE estas tablas: nunca las edita (RN-W08).
# Las escribe únicamente la API /api/v1 (monitoreo/services.py), con upsert idempotente por ID.
from django.db import models

from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from cuentas.models import Device, Platform, User
from config.restricciones import checks_de_opciones


class SessionStatus(models.TextChoices):  # SYNCED es solo local en la app: nunca llega al servidor
    DRAFT = "DRAFT", "Borrador"
    PREPARING = "PREPARING", "Preparando"
    READY = "READY", "Lista"
    ACTIVE = "ACTIVE", "En curso"
    PAUSED = "PAUSED", "En pausa"
    CLOSING = "CLOSING", "Cerrando"
    CLOSED = "CLOSED", "Cerrada"


class CaptureMode(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    AUTOMATICO = "AUTOMATICO", "Automático"
    MIXTO = "MIXTO", "Mixto"  # eliminado en la app v0.2.0 (Q-20 del maestro móvil); se conserva para datos antiguos


class LateralCode(models.TextChoices):
    LATERAL_A = "LATERAL_A", "Lateral A"
    LATERAL_B = "LATERAL_B", "Lateral B"


class CameraRole(models.TextChoices):
    CAMERA_1 = "CAMERA_1", "Cámara 1"
    CAMERA_2 = "CAMERA_2", "Cámara 2"


class Direction(models.TextChoices):
    ASCENDENTE = "ASCENDENTE", "Ascendente"
    DESCENDENTE = "DESCENDENTE", "Descendente"


class PassStatus(models.TextChoices):
    READY = "READY", "Lista"
    ACTIVE = "ACTIVE", "En curso"
    PAUSED = "PAUSED", "En pausa"
    COMPLETED = "COMPLETED", "Completa"
    INCOMPLETE = "INCOMPLETE", "Incompleta"


class SequenceStatus(models.TextChoices):
    CREATED = "CREATED", "Creada"
    COMMAND_SENT = "COMMAND_SENT", "Orden enviada"
    PARTIAL = "PARTIAL", "Parcial"
    COMPLETE = "COMPLETE", "Completa"
    INCOMPLETE = "INCOMPLETE", "Incompleta"
    CANCELLED = "CANCELLED", "Cancelada"


@checks_de_opciones
class MonitoringSession(models.Model):
    session_id = models.UUIDField(primary_key=True)
    operator = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sessions",
                                 db_column="operator_user_id")
    controller_device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="sessions",
                                          db_column="controller_device_id")
    status = models.CharField(max_length=12, choices=SessionStatus.choices)
    mode = models.CharField(max_length=12, choices=CaptureMode.choices)
    interval_ms = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    app_version = models.CharField(max_length=40)
    config_version = models.CharField(max_length=40)
    quality_profile_version = models.CharField(max_length=20)
    short_test_passed_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "monitoring_sessions"
        indexes = [models.Index(fields=["started_at"], name="sesion_inicio_idx")]
        verbose_name = "sesión de monitoreo"
        verbose_name_plural = "sesiones de monitoreo"

    def __str__(self):
        return f"Sesión {str(self.session_id)[:8]}"


@checks_de_opciones
class SessionDevice(models.Model):
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="cameras")
    role = models.CharField(max_length=10, choices=CameraRole.choices)
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    platform = models.CharField(max_length=10, choices=Platform.choices)
    model = models.CharField(max_length=80, blank=True)
    os_version = models.CharField(max_length=40, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    paired_at = models.DateTimeField()
    released = models.BooleanField(default=False)

    class Meta:
        db_table = "session_devices"
        constraints = [models.UniqueConstraint(fields=["session", "role", "device"], name="session_devices_unico")]


@checks_de_opciones
class MonitoringPass(models.Model):
    pass_id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="passes")
    lot = models.ForeignKey(FieldLot, on_delete=models.PROTECT, related_name="+")
    row = models.ForeignKey(FieldRow, on_delete=models.PROTECT, related_name="passes")
    lateral_code = models.CharField(max_length=10, choices=LateralCode.choices)
    pass_order = models.PositiveIntegerField()
    direction = models.CharField(max_length=12, choices=Direction.choices)
    start_marker = models.ForeignKey(Marker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    end_marker = models.ForeignKey(Marker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=12, choices=PassStatus.choices)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    sequences_total = models.PositiveIntegerField(default=0)
    sequences_complete = models.PositiveIntegerField(default=0)
    sequences_incomplete = models.PositiveIntegerField(default=0)
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "monitoring_passes"
        indexes = [models.Index(fields=["row", "lateral_code", "status"], name="pasada_cobertura_idx")]
        verbose_name = "pasada"


@checks_de_opciones
class MarkerChange(models.Model):
    marker_change_id = models.UUIDField(primary_key=True)
    monitoring_pass = models.ForeignKey(MonitoringPass, on_delete=models.CASCADE, related_name="marker_changes",
                                        db_column="pass_id")
    marker = models.ForeignKey(Marker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    segment = models.ForeignKey(FieldSegment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField()
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    gps_accuracy_m = models.FloatField(null=True, blank=True)
    gps_timestamp = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "marker_changes"


@checks_de_opciones
class CaptureSequence(models.Model):
    sequence_id = models.UUIDField(primary_key=True)
    monitoring_pass = models.ForeignKey(MonitoringPass, on_delete=models.CASCADE, related_name="sequences",
                                        db_column="pass_id")
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="sequences")
    sequence_number = models.PositiveIntegerField()
    mode = models.CharField(max_length=12, choices=CaptureMode.choices)
    status = models.CharField(max_length=14, choices=SequenceStatus.choices)
    segment = models.ForeignKey(FieldSegment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    marker = models.ForeignKey(Marker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    gps_accuracy_m = models.FloatField(null=True, blank=True)
    gps_timestamp = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    expected_capture_ids = models.JSONField(default=dict)  # {"CAMERA_1": uuid, "CAMERA_2": uuid}
    slot_outcomes = models.JSONField(default=dict)  # {"CAMERA_1": "OK_RECIBIDA", …}
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "capture_sequences"
        constraints = [models.UniqueConstraint(fields=["monitoring_pass", "sequence_number"],
                                               name="secuencia_numero_unico")]
        verbose_name = "secuencia"


class IncidentType(models.TextChoices):
    CALIDAD = "CALIDAD", "Calidad"
    DESCONEXION = "DESCONEXION", "Desconexión"
    BATERIA = "BATERIA", "Batería"
    TEMPERATURA = "TEMPERATURA", "Temperatura"
    ESPACIO = "ESPACIO", "Espacio"
    GPS = "GPS", "GPS"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
    SINCRONIZACION = "SINCRONIZACION", "Sincronización"
    SOPORTE = "SOPORTE", "Soporte"
    OPERADOR = "OPERADOR", "Operador"
    OTRO = "OTRO", "Otro"


@checks_de_opciones
class Incident(models.Model):
    class Severity(models.TextChoices):
        INFO = "INFO", "Información"
        AVISO = "AVISO", "Aviso"
        ERROR = "ERROR", "Error"

    class CreatedBy(models.TextChoices):
        SISTEMA = "SISTEMA", "Sistema"
        OPERADOR = "OPERADOR", "Operador"

    incident_id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name="incidents")
    monitoring_pass = models.ForeignKey(MonitoringPass, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="incidents", db_column="pass_id")
    sequence = models.ForeignKey(CaptureSequence, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="incidents")
    capture_id = models.UUIDField(null=True, blank=True)  # la captura puede no haberse sincronizado
    device_id = models.UUIDField(null=True, blank=True)
    type = models.CharField(max_length=16, choices=IncidentType.choices)
    severity = models.CharField(max_length=6, choices=Severity.choices)
    detail = models.TextField()
    occurred_at = models.DateTimeField()
    created_by = models.CharField(max_length=10, choices=CreatedBy.choices)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "incidents"
        ordering = ["occurred_at"]
        verbose_name = "incidencia"
