# api/errors.py — Errores del contrato /api/v1 (Maestro App Móvil §15.1 y §15.3, ApiErrorBody).
#
# Toda respuesta de error de la API tiene la forma { code, message, fieldErrors?, traceId } con un código de
# ApiErrorCode. Los servicios que atienden a la app (cuentas, monitoreo, evidencias) lanzan ApiError; el manejador
# api_exception_handler convierte también las excepciones de DRF y cualquier error inesperado (500 INTERNAL_ERROR,
# con la traza en la consola del servidor y el mismo traceId).
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from diagnostico.contexto import current_trace_id

log = logging.getLogger("riachuelo.api")

# Mensajes por defecto (el texto que ve la persona lo decide la app con API_ERROR_MESSAGES, §19).
MESSAGES = {
    "VALIDATION_ERROR": "Revisa los datos enviados.",
    "EMAIL_ALREADY_REGISTERED": "Ese correo ya tiene una cuenta.",
    "INVALID_CREDENTIALS": "Correo o contraseña incorrectos.",
    "ACCOUNT_PENDING": "La cuenta está pendiente de aprobación.",
    "ACCOUNT_REJECTED": "La solicitud de cuenta fue rechazada.",
    "ACCOUNT_BLOCKED": "La cuenta está bloqueada.",
    "ROLE_NOT_ALLOWED": "El usuario no tiene permiso para usar la app móvil.",
    "DEVICE_REVOKED": "Este celular fue desactivado por el administrador.",
    "PASSWORD_POLICY": "La contraseña no cumple los requisitos.",
    "TOO_MANY_ATTEMPTS": "Demasiados intentos. Espera unos minutos.",
    "TOKEN_EXPIRED": "El token de acceso no es válido o venció.",
    "REFRESH_INVALID": "La sesión ya no es válida.",
    "SESSION_NOT_FOUND": "El servidor no tiene la sesión.",
    "PASS_NOT_FOUND": "El servidor no tiene la pasada.",
    "SEQUENCE_NOT_FOUND": "El servidor no tiene la secuencia.",
    "CAPTURE_CONFLICT": "Ya existe una foto con ese identificador y otro contenido.",
    "PAYLOAD_TOO_LARGE": "La foto supera el tamaño permitido.",
    "UPLOAD_SIGNATURE_INVALID": "La firma de la respuesta de Cloudinary no es válida.",
    "UPLOAD_NOT_FOUND": "No se encontró la foto en Cloudinary.",
    "UPLOAD_MISMATCH": "La foto de Cloudinary no coincide con la captura.",
    "INTERNAL_ERROR": "El servidor tuvo un problema.",
    "NOT_FOUND": "No existe.",
    # v1.3.1 (ADR-W-008): el administrador borró la sesión o la foto; la app borra su copia local y no reintenta.
    "SESSION_DELETED": "El administrador eliminó esta sesión.",
    "CAPTURE_DELETED": "El administrador eliminó esta foto.",  # Supuesto (W-04): 404 sin código definido en el contrato (GET /captures/{id})
}


class ApiError(Exception):
    def __init__(self, code, status=400, message=None, field_errors=None):
        super().__init__(message or MESSAGES.get(code, code))
        self.code = code
        self.status = status
        self.message = message or MESSAGES.get(code, code)
        self.field_errors = field_errors or []


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


def _flatten(detail, prefix=""):
    """Errores de serializadores DRF → [{field, message}] con rutas camelCase (p. ej. device.deviceId)."""
    out = []
    if isinstance(detail, dict):
        for k, v in detail.items():
            key = "" if k in ("non_field_errors", "__all__") else _camel(str(k))
            out += _flatten(v, f"{prefix}.{key}" if prefix and key else (key or prefix))
    elif isinstance(detail, list):
        if detail and all(not isinstance(x, (dict, list)) for x in detail):
            out.append({"field": prefix, "message": " ".join(str(x) for x in detail)})
        else:
            for i, v in enumerate(detail):
                out += _flatten(v, f"{prefix}[{i}]")
    else:
        out.append({"field": prefix, "message": str(detail)})
    return out


def error_response(code, status, message=None, field_errors=None):
    body = {"code": code, "message": message or MESSAGES.get(code, code), "traceId": current_trace_id()}
    if field_errors:
        body["fieldErrors"] = field_errors
    resp = Response(body, status=status)
    resp.api_error_code = code  # lo muestra la línea del registro en consola
    return resp


def api_exception_handler(exc, context):
    from rest_framework.views import set_rollback  # import local: evita un ciclo con rest_framework.views

    set_rollback()  # si la vista corría dentro de una transacción, no se confirma nada a medias
    if isinstance(exc, ApiError):
        if exc.status >= 500:
            log.error("API %s: %s", exc.code, exc.message)
        return error_response(exc.code, exc.status, exc.message, exc.field_errors)
    if isinstance(exc, drf.ValidationError):
        return error_response("VALIDATION_ERROR", 400, field_errors=_flatten(exc.detail))
    if isinstance(exc, drf.ParseError):
        return error_response("VALIDATION_ERROR", 400, "El cuerpo no es JSON válido.")
    if isinstance(exc, drf.UnsupportedMediaType):
        return error_response("VALIDATION_ERROR", 415, "Se espera Content-Type: application/json.")
    if isinstance(exc, (InvalidToken, TokenError, drf.NotAuthenticated, drf.AuthenticationFailed)):
        return error_response("TOKEN_EXPIRED", 401)
    if isinstance(exc, drf.Throttled):
        resp = error_response("TOO_MANY_ATTEMPTS", 429)
        if exc.wait:
            resp["Retry-After"] = str(int(exc.wait))
        return resp
    if isinstance(exc, (drf.PermissionDenied, DjangoPermissionDenied)):
        return error_response("ROLE_NOT_ALLOWED", 403)
    if isinstance(exc, (drf.NotFound, Http404)):
        return error_response("NOT_FOUND", 404)
    if isinstance(exc, drf.MethodNotAllowed):
        return error_response("VALIDATION_ERROR", 405, "Método no permitido.")
    if isinstance(exc, drf.APIException):
        return error_response("INTERNAL_ERROR", exc.status_code, str(exc.detail))
    view = context.get("view")
    log.exception("Error no controlado en la API (%s): %s", type(view).__name__ if view else "?", exc)
    return error_response("INTERNAL_ERROR", 500)
