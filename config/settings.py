# config/settings.py — Configuración de la plataforma Django (API /api/v1, web de revisión y worker de IA).
# Todo lo sensible sale de variables de entorno (sección 5.5 del Maestro Web). Nunca subir .env a Git.
# Base: Anexo B.1 del Maestro Web v1.0. Agregados de esta entrega (marcados «v1.0+»): API /api/v1 (Maestro App
# Móvil §15), registro de peticiones con traceId, Cloudinary simulado para desarrollo y parámetros del worker.
import secrets
import sys
import warnings
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

APP_ENV = env("APP_ENV", default="dev")  # dev | piloto
if APP_ENV not in ("dev", "piloto"):
    raise ImproperlyConfigured("APP_ENV debe ser 'dev' o 'piloto'.")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
TESTING = "test" in sys.argv

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if APP_ENV == "piloto":
        raise ImproperlyConfigured("Falta DJANGO_SECRET_KEY en el entorno piloto.")
    # v1.0+: solo en dev, clave efímera para poder arrancar (las sesiones se pierden al reiniciar).
    SECRET_KEY = "dev-efimera-" + secrets.token_urlsafe(40)
    SECRET_KEY_EFIMERA = True
else:
    SECRET_KEY_EFIMERA = False

# En dev se acepta cualquier host para que los celulares de la red local lleguen a la API (http://<IP>:8000).
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"] if APP_ENV == "dev" else ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000")  # enlaces en WhatsApp

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "cuentas",
    "campo",
    "monitoreo",
    "evidencias",
    "ia",
    "revision",
    "notificaciones",
    "auditoria",
    "api",
    "web",
    "diagnostico",
    "simulador",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "diagnostico.middleware.RequestLogMiddleware",  # v1.0+: traceId y registro de cada petición en consola
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "web.middleware.NoStoreForAuthenticatedMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context_processors.web_context",
            ],
        },
    },
]

# Base de datos: Supabase (sección 5.5). Conexión directa o session pooler (puerto 5432); nunca el transaction pooler.
# v1.0+: sin DATABASE_URL en dev se usa SQLite (vista previa rápida); en piloto es obligatoria.
if APP_ENV == "piloto" and not env("DATABASE_URL", default=""):
    raise ImproperlyConfigured("Falta DATABASE_URL (Supabase) en el entorno piloto.")
_DB_URL = env("DATABASE_URL", default="").strip() or f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"
DATABASES = {"default": env.db_url_config(_DB_URL)}
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", env("DB_SSLMODE", default="require"))
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
else:
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("timeout", 20)  # SQLite: web y worker a la vez en la laptop
# Tamaño máximo de la base en el plan contratado (Supabase Free: 500 MB; Pro: 8 GB) — lo vigila `diagnostico`.
DB_LIMITE_MB = env.int("DB_LIMITE_MB", default=500)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Caché compartida entre procesos gunicorn (bloqueo de login, KPIs del dashboard). Tabla creada por migración.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "web_cache"}}

AUTH_USER_MODEL = "cuentas.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "cuentas.validators.LettersAndDigitsValidator"},  # misma política que la app (PASSWORD_POLICY)
]
if TESTING:  # solo pruebas: hash rápido (PBKDF2 real en dev y piloto)
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:dashboard"
LOGOUT_REDIRECT_URL = "web:login"

# Sesión web (cookie) — sección 7.3
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)  # una jornada
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # HTMX lee el token de hx-headers; no hace falta leer la cookie
# HTTPS obligatorio solo en piloto: en dev la web y la API se usan por http://<IP-de-la-laptop>:8000.
HTTPS = APP_ENV == "piloto" and not DEBUG
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=HTTPS)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=HTTPS)
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=HTTPS)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # detrás del proxy HTTPS del hosting
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600 if HTTPS else 0)
SECURE_CONTENT_TYPE_NOSNIFF = True
# HSTS solo para el dominio de la plataforma: los demás subdominios del dominio de Hostinger (correo, web
# institucional) pueden no tener HTTPS, así que no se incluyen ni se pide la lista de precarga.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
X_FRAME_OPTIONS = "DENY"
# OpenStreetMap exige un Referer válido en las teselas: 'same-origin' (valor por defecto de Django) no lo envía.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"  # se muestra en hora de Lima; se guarda en UTC
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"  # v1.0+: solo lo usa el Cloudinary simulado de desarrollo
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Piloto: archivos con hash y comprimidos (collectstatic). Dev y pruebas: sin manifiesto, sin collectstatic.
    "staticfiles": {"BACKEND": env("STATICFILES_BACKEND", default="") or (
        "django.contrib.staticfiles.storage.StaticFilesStorage" if (DEBUG or TESTING)
        else "whitenoise.storage.CompressedManifestStaticFilesStorage")},
}

# Cloudinary: el SDK lee CLOUDINARY_URL (cloudinary://<api_key>:<api_secret>@<cloud_name>) del entorno.
# v1.0+: si falta (o es el ejemplo con <…>) y APP_ENV=dev, se usa el Cloudinary SIMULADO local (evidencias/nube.py).
CLOUDINARY_URL = env("CLOUDINARY_URL", default="")
if TESTING and not CLOUDINARY_URL:  # pruebas: SDK real con credenciales ficticias (solo firma local, sin red)
    CLOUDINARY_URL = "cloudinary://123456789012345:secreto-de-prueba@riachuelo-test"
CLOUDINARY_ENV_PREFIX = env("CLOUDINARY_ENV_PREFIX", default=APP_ENV)
# Compatibilidad con la app actual (v1): POST /captures/upload multipart con la foto; el servidor la sube a Cloudinary.
# Cuando la app use el ticket v2.0 (sube directo a Cloudinary), poner false.
API_SUBIDA_MULTIPART = env.bool("API_SUBIDA_MULTIPART", default=True)
CLOUDINARY_MAX_UPLOAD_BYTES = env.int("CLOUDINARY_MAX_UPLOAD_BYTES", default=10 * 1024 * 1024)  # plan Free

# WhatsApp Cloud API (lo usa solo el worker; la web nunca llama a WhatsApp)
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN", default="")
WHATSAPP_PHONE_ID = env("WHATSAPP_PHONE_ID", default="")
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", default="")  # versión vigente indicada por Meta
WHATSAPP_TEMPLATE = env("WHATSAPP_TEMPLATE", default="caso_confirmado")
WHATSAPP_TEMPLATE_LANG = env("WHATSAPP_TEMPLATE_LANG", default="es")
WHATSAPP_CLIENT = env("WHATSAPP_CLIENT", default="notificaciones.whatsapp.ConsoleClient")

# Worker de IA (v1.0+, §28.8 del Maestro App Móvil). IA_DETECTOR: simulado | onnx | yolo.
IA_DETECTOR = env("IA_DETECTOR", default="simulado" if APP_ENV == "dev" else "onnx")
MODEL_PATH = str(BASE_DIR / env("MODEL_PATH", default="ia/inference/weights/modelo.onnx"))  # relativa → a BASE_DIR
IA_SIMULADO_PROBABILIDAD = env.float("IA_SIMULADO_PROBABILIDAD", default=0.2)  # fotos con indicio (solo simulado)
IA_DESCARGA_TIMEOUT = env.int("IA_DESCARGA_TIMEOUT", default=60)

# Parámetros de la web (sección 17 del Maestro Web)
WEB = {
    "BANDEJA_POLL_SECONDS": env.int("WEB_BANDEJA_POLL_SECONDS", default=15),
    "BANDEJA_PAGE_SIZE": 25,
    "MAPA_MAX_FEATURES": 5000,
    "DASHBOARD_CACHE_SECONDS": 60,
    "LOGIN_MAX_FAILED": 5,
    "LOGIN_LOCKOUT_MINUTES": 15,
    "OBSERVATION_MAX_LENGTH": 2000,
    "EXPORT_MAX_ROWS": 50000,
    "ACTIVIDAD_POLL_SECONDS": env.int("WEB_ACTIVIDAD_POLL_SECONDS", default=20),  # v1.0+: avisos en vivo
}

# API /api/v1 de la app móvil (Maestro App Móvil §15 y §28.6)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["api.authentication.DeviceJWTAuthentication"],  # JWT + X-Device-Id
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "api.errors.api_exception_handler",  # cuerpo ApiErrorBody (15.3)
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "registro": "20/hour", "renovar": "60/min"},
    "UNAUTHENTICATED_USER": None,
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),  # ≥ auth.offlineLoginMaxDays de la app (7.5)
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Riachuelo · API de la app móvil",
    "DESCRIPTION": "Contrato /api/v1 (Maestro App Móvil v2.0, sección 15). JSON camelCase, fechas ISO-8601 UTC.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Los serializadores usan .values (sin etiquetas): mismo conjunto → un solo nombre de enum en el esquema.
    "ENUM_NAME_OVERRIDES": {"CameraRoleEnum": ["CAMERA_1", "CAMERA_2"], "LateralCodeEnum": ["LATERAL_A", "LATERAL_B"],
                            "PlatformEnum": ["android", "ios"]},
}

# Registro en consola (v1.0+): cada petición con traceId, errores con su traza y avisos de configuración.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_REQUESTS = env.bool("LOG_REQUESTS", default=not TESTING)
LOG_SLOW_MS = env.int("LOG_SLOW_MS", default=1500)  # RNF-W01: toda pantalla < 1,5 s
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"consola": {"()": "diagnostico.logs.ConsoleFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "consola"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.server": {"level": "ERROR"},  # las líneas de cada petición las escribe RequestLogMiddleware
        "django.request": {"level": "CRITICAL" if TESTING else "ERROR"},
        "django.db.backends": {"level": "WARNING"},
        "django.utils.autoreload": {"level": "WARNING"},  # runserver ya imprime «Watching for file changes»
        "django.security.csrf": {"level": "CRITICAL" if TESTING else "WARNING"},
    },
}
if TESTING:  # las pruebas provocan errores a propósito: la consola solo muestra el resultado
    LOGGING["root"]["level"] = "CRITICAL"

# WhiteNoise avisa si no existe staticfiles/ (solo se crea con collectstatic, necesario recién en piloto).
warnings.filterwarnings("ignore", message="No directory at", module="django.core.handlers.base")
