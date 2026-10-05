# api/schema.py — Describe en el OpenAPI (/api/v1/schema) la autenticación de la app: JWT Bearer + X-Device-Id.
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class DeviceJWTScheme(OpenApiAuthenticationExtension):
    target_class = "api.authentication.DeviceJWTAuthentication"
    name = "jwtCelular"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                "description": "accessToken de POST /auth/login. Enviar también la cabecera X-Device-Id (UUID del "
                               "celular): un celular revocado responde 403 DEVICE_REVOKED."}
