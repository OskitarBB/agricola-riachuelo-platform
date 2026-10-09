# api/permissions.py — QUÉ HACE: v1.3 (ADR-W-007) permisos por rol dentro de la API de la app.
#   · FieldWork: monitoreo y sincronización (sesiones, pasadas, secuencias, incidencias, fotos) → solo operador de campo
#     y administrador. El especialista ingresa a la app solo para «Ubicar plaga» y recibe 403 ROLE_NOT_ALLOWED aquí.
#   · PestReaders: «Ubicar plaga» → operador, administrador y especialista.
from rest_framework.permissions import BasePermission

from api.errors import ApiError
from cuentas.models import MOBILE_FIELD_ROLES, MOBILE_ROLES


class _PorRol(BasePermission):
    roles = frozenset()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False  # DRF responde 401 con el autenticador
        if not (user.roles & self.roles):
            raise ApiError("ROLE_NOT_ALLOWED", 403)
        return True


class FieldWork(_PorRol):
    roles = MOBILE_FIELD_ROLES


class PestReaders(_PorRol):
    roles = MOBILE_ROLES
