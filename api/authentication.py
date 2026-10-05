# api/authentication.py — JWT de SimpleJWT + X-Device-Id no revocado (§28.6 del maestro móvil).
#
# Respuestas del contrato: token ausente, inválido o vencido → 401 TOKEN_EXPIRED (la app renueva y reintenta);
# cuenta que ya no puede usar la app → 403 ACCOUNT_BLOCKED / ACCOUNT_PENDING / ACCOUNT_REJECTED / ROLE_NOT_ALLOWED;
# celular revocado (devices.revoked_at) → 403 DEVICE_REVOKED en cualquier llamada con ese X-Device-Id.
import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from api.errors import ApiError
from cuentas.models import Device, User
from cuentas.services import ensure_app_access, ensure_device_not_revoked

TOQUE_DISPOSITIVO = timedelta(minutes=5)  # last_seen_at se actualiza como máximo cada 5 min por celular


def device_id_from(request):
    """X-Device-Id (UUID generado por la app al instalarse). Un valor mal formado es un error de la app (400)."""
    raw = (request.META.get("HTTP_X_DEVICE_ID") or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, field_errors=[
            {"field": "X-Device-Id", "message": "Debe ser un UUID."}]) from exc


class DeviceJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None
        raw = self.get_raw_token(header)
        if raw is None:
            return None
        try:
            token = self.get_validated_token(raw)
        except InvalidToken as exc:
            raise ApiError("TOKEN_EXPIRED", 401) from exc
        user = User.objects.filter(pk=token.get("user_id")).first()
        if user is None:
            raise ApiError("TOKEN_EXPIRED", 401)
        device_id = device_id_from(request) or token.get("device_id")
        if token.get("device_id") and device_id and str(token.get("device_id")) != str(device_id):
            raise ApiError("TOKEN_EXPIRED", 401, "El token pertenece a otro celular.")
        ensure_device_not_revoked(device_id)
        ensure_app_access(user)
        request.device_id = device_id
        self._touch(device_id)
        return user, token

    @staticmethod
    def _touch(device_id):
        if not device_id:
            return
        limite = timezone.now() - TOQUE_DISPOSITIVO
        Device.objects.filter(pk=device_id, last_seen_at__lt=limite).update(last_seen_at=timezone.now())

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
