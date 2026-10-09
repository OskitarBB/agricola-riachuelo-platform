# api/v1/views.py — Endpoints /api/v1 de la app móvil (Maestro App Móvil §15.2). Cada vista: valida la forma con su
# serializador → llama al servicio de su app → responde el DTO del contrato. Hasta la v1.2 no exponían URLs de fotos,
# estados de IA ni datos de revisión (28.10). v1.3 (ADR-W-007) agrega UNA excepción, de solo lectura y por rol:
# GET mobile/pest-reports («Ubicar plaga»: alertas con ubicación, miniatura firmada y capas del fundo).
import hashlib
import json
import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from api.authentication import device_id_from
from api.errors import ApiError
from api.permissions import FieldWork, PestReaders
from api.v1 import serializers as s
from campo.models import FieldLot, FieldRow, FieldSegment, Marker, QualityProfile
from cuentas import services as cuentas
from cuentas.services import iso
from evidencias import services as evidencias
from evidencias.models import Capture
from monitoreo import services as monitoreo
from monitoreo.models import LateralCode

log = logging.getLogger("riachuelo.api")


def _valid(serializer_class, data):
    ser = serializer_class(data=data)
    ser.is_valid(raise_exception=True)
    return ser.validated_data


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


# ------------------------------------------------------------------ salud
class HealthView(PublicView):
    @extend_schema(summary="Comprobar que el backend responde (y su base de datos)", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            log.error("GET /health: la base de datos no responde: %s", exc)
            raise ApiError("INTERNAL_ERROR", 503, "La base de datos no responde.") from exc
        return Response({"status": "UP", "serverTime": iso(timezone.now())})


# ------------------------------------------------------------------ autenticación
class RegisterView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "registro"

    @extend_schema(request=s.RegisterSerializer, summary="Registro (cuenta pendiente de aprobación)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request):
        data = _valid(s.RegisterSerializer, request.data)
        user = cuentas.register_user(data, device_id_from(request))
        return Response({"userId": str(user.pk), "status": user.status}, status=status.HTTP_201_CREATED)


class LoginView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=s.LoginSerializer, summary="Login con datos del dispositivo",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request):
        data = _valid(s.LoginSerializer, request.data)
        return Response(cuentas.app_login(data["email"], data["password"], data["device"]))


class RefreshView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "renovar"

    @extend_schema(request=s.RefreshSerializer, summary="Renovar tokens (rotación del refresh)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request):
        data = _valid(s.RefreshSerializer, request.data)
        return Response(cuentas.app_refresh(data["refreshToken"], data["deviceId"]))


class LogoutView(PublicView):
    @extend_schema(request=s.LogoutSerializer, summary="Revocar el refresh del dispositivo", responses={204: None})
    def post(self, request):
        data = _valid(s.LogoutSerializer, request.data)
        cuentas.app_logout(data["refreshToken"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(summary="Perfil del usuario actual", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(cuentas.user_profile(request.user))


class ChangePasswordView(APIView):
    @extend_schema(request=s.ChangePasswordSerializer, summary="Cambiar contraseña (quita mustChangePassword)",
                  responses={204: None})
    def post(self, request):
        data = _valid(s.ChangePasswordSerializer, request.data)
        cuentas.app_change_password(request.user, data["currentPassword"], data["newPassword"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetView(PublicView):
    @extend_schema(request=s.PasswordResetSerializer, summary="Pedir restablecimiento al administrador (siempre 202)",
                  responses={202: None})
    def post(self, request):
        try:
            data = _valid(s.PasswordResetSerializer, request.data)
            cuentas.request_password_reset(data.get("email"), request.META.get("REMOTE_ADDR", ""))
        except Exception as exc:  # noqa: BLE001 — el contrato responde 202 siempre (no revela si el correo existe)
            log.warning("Pedido de restablecimiento no registrado: %s", exc)
        return Response(status=status.HTTP_202_ACCEPTED)


# ------------------------------------------------------------------ catálogos
def _catalog_version(payload):
    """catalogVersion = momento en que el servidor vio por primera vez este contenido de catálogos (cambia solo si
    cambian lotes, hileras, segmentos, marcadores o el perfil de calidad)."""
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    key = f"catalogo-version:{digest}"
    version = cache.get(key)
    if version is None:
        version = iso(timezone.now())
        cache.set(key, version, None)
    return version


class BootstrapView(APIView):
    @extend_schema(summary="Catálogos activos y perfil de calidad publicado", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        lots = [{"id": lot.pk, "code": lot.code, "name": lot.name, "active": lot.active}
                for lot in FieldLot.objects.filter(active=True).order_by("code")]
        lot_ids = [x["id"] for x in lots]
        rows = [{"id": r.pk, "lotId": r.lot_id, "number": r.number, "plantCount": r.plant_count, "active": r.active}
                for r in FieldRow.objects.filter(lot_id__in=lot_ids, active=True).order_by("lot_id", "number")]
        row_ids = [x["id"] for x in rows]
        # v1.2 (ADR-W-006): solo segmentos y marcadores activos; "active" es un campo agregado (compatible).
        segments = [{"id": g.pk, "rowId": g.row_id, "code": g.code, "startPlant": g.start_plant,
                     "endPlant": g.end_plant, "isPilot": g.is_pilot, "active": True}
                    for g in FieldSegment.objects.filter(row_id__in=row_ids, active=True)
                    .order_by("row_id", "start_plant")]
        markers = [{"id": m.pk, "rowId": m.row_id, "segmentId": m.segment_id, "code": m.code,
                    "description": m.description or None, "position": m.position, "lat": m.lat, "lon": m.lon,
                    "active": True}
                   for m in Marker.objects.filter(row_id__in=row_ids, active=True)
                   .exclude(segment__active=False).order_by("row_id", "code")]
        profile = (QualityProfile.objects.filter(published_at__isnull=False).order_by("-published_at").first())
        quality = {"version": profile.version, "params": profile.params} if profile else None
        payload = {"lots": lots, "rows": rows, "segments": segments, "markers": markers,
                   "lateralCodes": list(LateralCode.values), "qualityProfile": quality}
        return Response({"catalogVersion": _catalog_version(payload), **payload, "serverTime": iso(timezone.now())})


# ------------------------------------------------------------------ sincronización (idempotente por ID)
class SessionUpsertView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(request=s.SessionUpsertSerializer, summary="Crear o actualizar sesión (idempotente por sessionId)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request):
        data = _valid(s.SessionUpsertSerializer, request.data)
        session, created = monitoreo.upsert_session(data, getattr(request, "device_id", None))
        return Response({"sessionId": str(session.pk), "status": session.status},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PassUpsertView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(request=s.PassUpsertSerializer, summary="Crear o actualizar pasada (idempotente por passId)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request, session_id):
        session_id = uuid.UUID(session_id)
        data = _valid(s.PassUpsertSerializer, request.data)
        obj, created = monitoreo.upsert_pass(session_id, data)
        return Response({"passId": str(obj.pk), "status": obj.status},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _same_session(path_id, body_id):
    if str(path_id) != str(body_id):
        raise ApiError("VALIDATION_ERROR", 400, field_errors=[
            {"field": "sessionId", "message": "No coincide con la sesión de la ruta."}])


class SequenceBatchView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(request=s.SequenceBatchSerializer, summary="Secuencias de la sesión (hasta 200 por petición)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request, session_id):
        session_id = uuid.UUID(session_id)
        data = _valid(s.SequenceBatchSerializer, request.data)
        _same_session(session_id, data["sessionId"])
        return Response(monitoreo.upsert_sequences(session_id, data["sequences"]))


class IncidentBatchView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(request=s.IncidentBatchSerializer, summary="Incidencias de la sesión (hasta 200 por petición)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request, session_id):
        session_id = uuid.UUID(session_id)
        data = _valid(s.IncidentBatchSerializer, request.data)
        _same_session(session_id, data["sessionId"])
        return Response(monitoreo.upsert_incidents(session_id, data["incidents"]))


# ------------------------------------------------------------------ capturas
class UploadTicketView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(request=s.UploadTicketSerializer, summary="Ticket firmado para subir UNA foto a Cloudinary",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request, capture_id):
        capture_id = uuid.UUID(capture_id)
        data = _valid(s.UploadTicketSerializer, request.data)
        return Response(evidencias.upload_ticket(capture_id, data, request.build_absolute_uri("/")))


class CaptureConfirmView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    # JSON: contrato v2.0 (la app ya subió a Cloudinary con el ticket). Multipart: contrato v1 de la app actual
    # (file + metadata); el servidor sube la foto. API_SUBIDA_MULTIPART=false lo desactiva cuando la app migre.
    parser_classes = [JSONParser, MultiPartParser]

    @extend_schema(request=s.CaptureConfirmSerializer, summary="Confirmar la captura (metadatos + resultado de Cloudinary)",
                  responses=OpenApiTypes.OBJECT)
    def post(self, request):
        if (request.content_type or "").startswith("multipart/"):
            return self._multipart(request)
        data = _valid(s.CaptureConfirmSerializer, request.data)
        meta = dict(data["metadata"])
        raw_meta = request.data.get("metadata") or {}
        meta["retakeContext"] = raw_meta.get("retakeContext")  # se guarda tal como llega (camelCase, 11.5)
        capture, created = evidencias.confirm_capture(meta, dict(data["cloudinary"]))
        return Response({"captureId": str(capture.pk), "status": "SINCRONIZADO", "duplicate": not created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


    def _multipart(self, request):
        if not settings.API_SUBIDA_MULTIPART:
            raise ApiError("VALIDATION_ERROR", 400, "El servidor espera el flujo v2.0: pide un ticket con "
                                                    "POST /captures/{captureId}/upload-ticket y sube a Cloudinary.")
        try:
            raw_meta = json.loads(request.data.get("metadata") or "")
        except (TypeError, ValueError) as exc:
            raise ApiError("VALIDATION_ERROR", 400, field_errors=[
                {"field": "metadata", "message": "Debe ser el JSON de la captura (texto)."}]) from exc
        archivo = request.FILES.get("file")
        if archivo is None:
            raise ApiError("VALIDATION_ERROR", 400, field_errors=[{"field": "file", "message": "Falta la foto."}])
        if not isinstance(raw_meta, dict):
            raise ApiError("VALIDATION_ERROR", 400, field_errors=[
                {"field": "metadata", "message": "Debe ser un objeto JSON."}])
        meta = dict(_valid(s.CaptureMetadataSerializer, raw_meta))
        meta["retakeContext"] = raw_meta.get("retakeContext")
        capture, created = evidencias.confirm_multipart(meta, archivo)
        return Response({"captureId": str(capture.pk), "status": "SINCRONIZADO", "duplicate": not created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CaptureDetailView(APIView):
    permission_classes = [IsAuthenticated, FieldWork]  # v1.3: el especialista no sincroniza
    @extend_schema(summary="Estado de sincronización de una captura (diagnóstico)", responses=OpenApiTypes.OBJECT)
    def get(self, request, capture_id):
        capture_id = uuid.UUID(capture_id)
        c = Capture.objects.filter(pk=capture_id).first()
        if c is None:
            raise ApiError("NOT_FOUND", 404, "El servidor no tiene esa captura.")
        return Response({"captureId": str(c.pk), "status": "SINCRONIZADO", "sessionId": str(c.session_id),
                         "passId": str(c.monitoring_pass_id), "sequenceId": str(c.sequence_id),
                         "sizeBytes": c.size_bytes, "md5": c.md5, "confirmedAt": iso(c.confirmed_at)})


# ------------------------------------------------------------------ v1.3 (ADR-W-007): «Ubicar plaga»
class PestReportsView(APIView):
    """Alertas de plaga para ir al lugar: confirmadas por la IA o por el especialista, posibles plagas y casos aún
    en revisión (los descartados y la evidencia insuficiente no salen). Con ubicación, miniatura firmada y las capas
    del fundo (contornos, hileras y puntos) para dibujar el mapa en la app. Operador, administrador y especialista."""

    permission_classes = [IsAuthenticated, PestReaders]

    @extend_schema(summary="Alertas de plaga con ubicación («Ubicar plaga»)", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from datetime import timedelta

        from evidencias.media import signed_image_url
        from revision.models import VISIBLES_EN_APP, Case, ReviewStatus
        from web.queries import map_layers

        try:
            dias = max(1, min(int(request.query_params.get("days", 30)), 90))
        except ValueError:
            dias = 30
        desde = timezone.now() - timedelta(days=dias)
        qs = (Case.objects.filter(status__in=VISIBLES_EN_APP, captured_at__gte=desde)
              .select_related("lot", "row", "segment", "marker", "capture", "ai_task")
              .prefetch_related("reviews", "ai_task__detections")
              .order_by("-captured_at")[:500])
        estados = dict(ReviewStatus.choices)
        laterales = dict(LateralCode.choices)
        reports = []
        for c in qs:
            vigente = next((r for r in c.reviews.all() if r.is_current), None)
            dets = sorted(c.ai_task.detections.all(), key=lambda d: -d.confidence) if c.ai_task_id else []
            label = (vigente.confirmed_class if vigente and vigente.confirmed_class else
                     dets[0].class_name if dets else None)
            reports.append({
                "caseId": str(c.pk), "status": c.status, "statusLabel": estados.get(c.status, c.status),
                "origin": c.origin, "label": label, "maxConfidence": c.max_confidence,
                "capturedAt": iso(c.captured_at), "decidedAt": iso(c.decided_at) if c.decided_at else None,
                "lot": {"id": c.lot_id, "code": c.lot.code, "name": c.lot.name},
                "row": {"id": c.row_id, "number": c.row.number, "plantCount": c.row.plant_count},
                "lateralCode": c.lateral_code, "lateralLabel": laterales.get(c.lateral_code, c.lateral_code),
                "segment": ({"id": c.segment_id, "code": c.segment.code, "startPlant": c.segment.start_plant,
                             "endPlant": c.segment.end_plant} if c.segment_id else None),
                "marker": {"id": c.marker_id, "code": c.marker.code} if c.marker_id else None,
                "lat": c.lat, "lon": c.lon, "gpsAccuracyM": c.gps_accuracy_m, "locationSource": c.location_source,
                "observation": vigente.observation if vigente else "",
                "thumbnailUrl": signed_image_url(c.capture, "miniatura"),
            })
        farm = map_layers()
        farm.pop("pointKinds", None)
        return Response({"reports": reports, "farm": farm, "days": dias, "serverTime": iso(timezone.now())})
