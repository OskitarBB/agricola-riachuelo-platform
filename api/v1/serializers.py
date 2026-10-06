# api/v1/serializers.py — DTO del contrato /api/v1 en camelCase (src/api/dto.ts del Maestro App Móvil, §15.3).
# Solo validan forma; las reglas (estados, idempotencia, firmas) están en los servicios de cada app.
import logging

from rest_framework import serializers

from cuentas.models import Platform
from cuentas.validators import PHONE_RE
from evidencias.models import QualityStatus
from monitoreo.models import (
    CameraRole,
    CaptureMode,
    Direction,
    Incident,
    IncidentType,
    LateralCode,
    PassStatus,
    SequenceStatus,
    SessionStatus,
)

SLOT_OUTCOMES = ["PENDIENTE", "OK_PENDIENTE_ARCHIVO", "OK_RECIBIDA", "RECHAZADA_CALIDAD", "ERROR_CAMARA",
                 "SIN_RESPUESTA"]
QUALITY_REASONS = ["EXPOSICION_OSCURA", "EXPOSICION_SATURADA", "NITIDEZ_BAJA", "ARCHIVO_INVALIDO", "FALLO_CAMARA",
                   "TIEMPO_AGOTADO"]
SESSION_STATUSES = [s for s in SessionStatus.values]  # SYNCED es solo local: nunca se envía


log = logging.getLogger("riachuelo.api.contrato")


class ContractWatchMixin:
    """Avisa en la consola si la app envía campos que el contrato no tiene (diferencia de versión entre app y
    servidor). No los rechaza: un campo nuevo de la app no debe bloquear la sincronización del piloto."""

    def to_internal_value(self, data):
        if isinstance(data, dict):
            extra = set(data) - set(self.fields)
            avisados = self.root.__dict__.setdefault("_campos_avisados", set())  # una vez por petición
            clave = (type(self).__name__, tuple(sorted(extra)))
            if extra and clave not in avisados:
                avisados.add(clave)
                log.warning("La app envió campos fuera del contrato en %s: %s (se ignoran)",
                            type(self).__name__.replace("Serializer", ""), ", ".join(sorted(extra)))
        return super().to_internal_value(data)


# ------------------------------------------------------------------ autenticación
class DeviceInfoSerializer(serializers.Serializer):
    deviceId = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=Platform.values)
    model = serializers.CharField(allow_blank=True, max_length=200)
    osVersion = serializers.CharField(allow_blank=True, max_length=80)
    appVersion = serializers.CharField(allow_blank=True, max_length=80)


class RegisterSerializer(ContractWatchMixin, serializers.Serializer):
    fullName = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(allow_null=True, allow_blank=True, required=False, max_length=30)
    employeeCode = serializers.CharField(allow_null=True, allow_blank=True, required=False, max_length=30)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    acceptedPrivacyNotice = serializers.BooleanField()

    def validate_fullName(self, value):
        if len(value.strip()) < 5:
            raise serializers.ValidationError("Escribe tu nombre completo.")
        return value

    def validate_phone(self, value):
        if value and not PHONE_RE.match(value.replace(" ", "")):
            raise serializers.ValidationError("Escribe un celular válido (9 a 15 dígitos).")
        return value

    def validate_acceptedPrivacyNotice(self, value):
        if value is not True:
            raise serializers.ValidationError("Debes aceptar el aviso de privacidad.")
        return value


class LoginSerializer(ContractWatchMixin, serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    device = DeviceInfoSerializer()


class RefreshSerializer(serializers.Serializer):
    refreshToken = serializers.CharField(max_length=4000)
    deviceId = serializers.UUIDField()


class LogoutSerializer(serializers.Serializer):
    refreshToken = serializers.CharField(max_length=4000)
    deviceId = serializers.UUIDField(required=False)


class ChangePasswordSerializer(serializers.Serializer):
    currentPassword = serializers.CharField(max_length=128, trim_whitespace=False)
    newPassword = serializers.CharField(max_length=128, trim_whitespace=False)


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254, allow_blank=True)


# ------------------------------------------------------------------ sincronización
class CameraSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=CameraRole.values)
    deviceId = serializers.UUIDField()
    userId = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=Platform.values)
    model = serializers.CharField(allow_blank=True, max_length=200)
    osVersion = serializers.CharField(allow_blank=True, max_length=80)
    appVersion = serializers.CharField(allow_blank=True, max_length=80)
    pairedAt = serializers.DateTimeField()
    released = serializers.BooleanField()


class SessionUpsertSerializer(ContractWatchMixin, serializers.Serializer):
    sessionId = serializers.UUIDField()
    operatorUserId = serializers.UUIDField()
    controllerDeviceId = serializers.UUIDField()
    status = serializers.ChoiceField(choices=SESSION_STATUSES)
    mode = serializers.ChoiceField(choices=CaptureMode.values)
    intervalMs = serializers.IntegerField(min_value=0)
    startedAt = serializers.DateTimeField(allow_null=True)
    endedAt = serializers.DateTimeField(allow_null=True)
    appVersion = serializers.CharField(max_length=40)
    configVersion = serializers.CharField(max_length=40)
    qualityProfileVersion = serializers.CharField(max_length=20)
    shortTestPassedAt = serializers.DateTimeField(allow_null=True)
    cameras = CameraSerializer(many=True)


class MarkerChangeSerializer(serializers.Serializer):
    markerChangeId = serializers.UUIDField()
    markerId = serializers.CharField(allow_null=True, max_length=40)
    segmentId = serializers.CharField(allow_null=True, max_length=40)
    changedAt = serializers.DateTimeField()
    lat = serializers.FloatField(allow_null=True, min_value=-90, max_value=90)
    lon = serializers.FloatField(allow_null=True, min_value=-180, max_value=180)
    gpsAccuracyM = serializers.FloatField(allow_null=True, min_value=0)
    gpsTimestamp = serializers.DateTimeField(allow_null=True)


class PassUpsertSerializer(ContractWatchMixin, serializers.Serializer):
    passId = serializers.UUIDField()
    lotId = serializers.CharField(max_length=20)
    rowId = serializers.CharField(max_length=30)
    lateralCode = serializers.ChoiceField(choices=LateralCode.values)
    passOrder = serializers.IntegerField(min_value=1)
    direction = serializers.ChoiceField(choices=Direction.values)
    startMarkerId = serializers.CharField(allow_null=True, max_length=40)
    endMarkerId = serializers.CharField(allow_null=True, max_length=40)
    status = serializers.ChoiceField(choices=PassStatus.values)
    startedAt = serializers.DateTimeField(allow_null=True)
    endedAt = serializers.DateTimeField(allow_null=True)
    sequencesTotal = serializers.IntegerField(min_value=0)
    sequencesComplete = serializers.IntegerField(min_value=0)
    sequencesIncomplete = serializers.IntegerField(min_value=0)
    markerChanges = MarkerChangeSerializer(many=True)


class CameraMapField(serializers.DictField):
    """Record<CameraRole, …>: solo claves CAMERA_1 / CAMERA_2."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        bad = set(value) - set(CameraRole.values)
        if bad:
            raise serializers.ValidationError(f"Claves no válidas: {', '.join(sorted(bad))}.")
        return value


class SequenceSerializer(ContractWatchMixin, serializers.Serializer):
    sequenceId = serializers.UUIDField()
    passId = serializers.UUIDField()
    sequenceNumber = serializers.IntegerField(min_value=0)
    mode = serializers.ChoiceField(choices=CaptureMode.values)
    status = serializers.ChoiceField(choices=SequenceStatus.values)
    segmentId = serializers.CharField(allow_null=True, max_length=40)
    markerId = serializers.CharField(allow_null=True, max_length=40)
    lat = serializers.FloatField(allow_null=True, min_value=-90, max_value=90)
    lon = serializers.FloatField(allow_null=True, min_value=-180, max_value=180)
    gpsAccuracyM = serializers.FloatField(allow_null=True, min_value=0)
    gpsTimestamp = serializers.DateTimeField(allow_null=True)
    issuedAt = serializers.DateTimeField()
    completedAt = serializers.DateTimeField(allow_null=True)
    expectedCaptureIds = CameraMapField(child=serializers.UUIDField())
    slotOutcomes = CameraMapField(child=serializers.ChoiceField(choices=SLOT_OUTCOMES))


class SequenceBatchSerializer(serializers.Serializer):
    sessionId = serializers.UUIDField()
    sequences = SequenceSerializer(many=True, allow_empty=True, max_length=200)  # sync.batchSize


class IncidentSerializer(ContractWatchMixin, serializers.Serializer):
    incidentId = serializers.UUIDField()
    passId = serializers.UUIDField(allow_null=True)
    sequenceId = serializers.UUIDField(allow_null=True)
    captureId = serializers.UUIDField(allow_null=True)
    deviceId = serializers.UUIDField(allow_null=True)
    type = serializers.ChoiceField(choices=IncidentType.values)
    severity = serializers.ChoiceField(choices=Incident.Severity.values)
    detail = serializers.CharField(max_length=4000, allow_blank=True)
    occurredAt = serializers.DateTimeField()
    createdBy = serializers.ChoiceField(choices=Incident.CreatedBy.values)


class IncidentBatchSerializer(serializers.Serializer):
    sessionId = serializers.UUIDField()
    incidents = IncidentSerializer(many=True, allow_empty=True, max_length=200)


# ------------------------------------------------------------------ capturas (v2.0: ticket + Cloudinary + confirmación)
class UploadTicketSerializer(serializers.Serializer):
    captureId = serializers.UUIDField()
    sessionId = serializers.UUIDField()
    passId = serializers.UUIDField()
    sequenceId = serializers.UUIDField()
    sizeBytes = serializers.IntegerField(min_value=1)
    md5 = serializers.RegexField(r"^[0-9a-fA-F]{32}$")
    mimeType = serializers.ChoiceField(choices=["image/jpeg"])


class QualityMetricsSerializer(serializers.Serializer):
    luminanceMean = serializers.FloatField()
    darkRatio = serializers.FloatField()
    brightRatio = serializers.FloatField()
    laplacianVariance = serializers.FloatField()
    analyzedRegions = serializers.IntegerField(min_value=0)
    durationMs = serializers.FloatField(min_value=0)


class QualitySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=QualityStatus.values)  # CAPTURED nunca se sincroniza
    reasons = serializers.ListField(child=serializers.ChoiceField(choices=QUALITY_REASONS), allow_empty=True)
    metrics = QualityMetricsSerializer(allow_null=True)
    profileVersion = serializers.CharField(max_length=20)


class RetakeContextSerializer(serializers.Serializer):
    requestedAt = serializers.CharField(max_length=40)
    segmentId = serializers.CharField(allow_null=True, max_length=40)
    markerId = serializers.CharField(allow_null=True, max_length=40)
    lat = serializers.FloatField(allow_null=True)
    lon = serializers.FloatField(allow_null=True)
    gpsAccuracyM = serializers.FloatField(allow_null=True)
    gpsTimestamp = serializers.CharField(allow_null=True, max_length=40)


class CaptureMetadataSerializer(ContractWatchMixin, serializers.Serializer):
    captureId = serializers.UUIDField()
    sequenceId = serializers.UUIDField()
    sessionId = serializers.UUIDField()
    passId = serializers.UUIDField()
    lateralCode = serializers.ChoiceField(choices=LateralCode.values)
    deviceId = serializers.UUIDField()
    cameraRole = serializers.ChoiceField(choices=CameraRole.values)
    cameraUserId = serializers.UUIDField()
    operatorUserId = serializers.UUIDField()
    capturedAt = serializers.DateTimeField()
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    sizeBytes = serializers.IntegerField(min_value=1)
    md5 = serializers.RegexField(r"^[0-9a-fA-F]{32}$")
    quality = QualitySerializer()
    replacesCaptureId = serializers.UUIDField(allow_null=True)
    retakeContext = RetakeContextSerializer(allow_null=True)
    appVersion = serializers.CharField(max_length=40)


class CloudinaryResultSerializer(serializers.Serializer):
    publicId = serializers.CharField(max_length=255)
    version = serializers.IntegerField(min_value=1)
    signature = serializers.CharField(max_length=128)
    bytes = serializers.IntegerField(min_value=1)
    format = serializers.CharField(allow_null=True, allow_blank=True, max_length=10)
    width = serializers.IntegerField(allow_null=True)
    height = serializers.IntegerField(allow_null=True)
    etag = serializers.CharField(allow_null=True, allow_blank=True, max_length=64)


class CaptureConfirmSerializer(serializers.Serializer):
    metadata = CaptureMetadataSerializer()
    cloudinary = CloudinaryResultSerializer()
