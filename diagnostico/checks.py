# diagnostico/checks.py — Comprobaciones de configuración que Django ejecuta en `check`, `runserver` y `migrate`.
# Errores (E) impiden arrancar en piloto con una configuración insegura o incompleta; avisos (W) se muestran en la
# consola con la forma de corregirlos.
from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

STATIC = Path(settings.BASE_DIR) / "web" / "static" / "web"
VENDOR = ["vendor/htmx.min.js", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css", "iconos.svg"]


@register(Tags.security, Tags.compatibility)
def configuracion(app_configs, **kwargs):
    from evidencias import nube

    issues = []
    piloto = settings.APP_ENV == "piloto"
    if piloto and settings.DEBUG:
        issues.append(Error("DJANGO_DEBUG=true en el entorno piloto.", hint="Pon DJANGO_DEBUG=false.",
                            id="riachuelo.E001"))
    if nube.modo() == nube.SIN_CONFIGURAR:
        issues.append(Error("Falta CLOUDINARY_URL: la app no podrá subir fotos ni la web mostrarlas.",
                            hint="Copia cloudinary://<api_key>:<api_secret>@<cloud_name> del panel de Cloudinary.",
                            id="riachuelo.E002"))
    if piloto and not settings.PUBLIC_BASE_URL.startswith("https://"):
        issues.append(Error("PUBLIC_BASE_URL debe ser https:// en piloto (enlace del WhatsApp).",
                            id="riachuelo.E003"))
    if piloto and ("*" in settings.ALLOWED_HOSTS or not settings.ALLOWED_HOSTS):
        issues.append(Error("ALLOWED_HOSTS debe listar el dominio de la plataforma en piloto.",
                            hint="Ejemplo: ALLOWED_HOSTS=monitoreo.tudominio.pe", id="riachuelo.E004"))
    if settings.WHATSAPP_CLIENT.endswith("CloudApiClient") and not (
            settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID and settings.WHATSAPP_GRAPH_VERSION):
        cls = Error if piloto else Warning
        issues.append(cls("WHATSAPP_CLIENT=CloudApiClient sin WHATSAPP_TOKEN, WHATSAPP_PHONE_ID o "
                          "WHATSAPP_GRAPH_VERSION: los avisos quedarán en ERROR_ENVIO.", id="riachuelo.W003"))
    if piloto and settings.WHATSAPP_CLIENT.endswith("ConsoleClient"):
        issues.append(Warning("En piloto WHATSAPP_CLIENT sigue en ConsoleClient: los avisos no se envían.",
                              hint="WHATSAPP_CLIENT=notificaciones.whatsapp.CloudApiClient", id="riachuelo.W004"))
    if settings.IA_DETECTOR in ("onnx", "yolo") and not Path(settings.MODEL_PATH).exists():
        issues.append(Warning(f"IA_DETECTOR={settings.IA_DETECTOR} pero no existe MODEL_PATH={settings.MODEL_PATH}.",
                              hint="Copia los pesos exportados del modelo YOLO o usa IA_DETECTOR=simulado en dev.",
                              id="riachuelo.W005"))
    if piloto and settings.IA_DETECTOR == "simulado":
        issues.append(Error("IA_DETECTOR=simulado en piloto: el worker inventaría cajas.", id="riachuelo.E006"))
    for rel in VENDOR:
        if not (STATIC / rel).exists():
            issues.append(Error(f"Falta el archivo estático web/static/web/{rel}.", id="riachuelo.E007"))
    if settings.SECRET_KEY_EFIMERA:
        issues.append(Warning("Sin DJANGO_SECRET_KEY: clave temporal (las sesiones se pierden al reiniciar).",
                              hint="Copia .env.example a .env (scripts/iniciar.ps1 lo hace solo).",
                              id="riachuelo.W008"))
    return issues
