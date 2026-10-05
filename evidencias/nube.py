# evidencias/nube.py — Único punto que conoce a Cloudinary (§28.7 del Maestro App Móvil, sección 14 del Maestro Web).
#
# Dos modos, elegidos UNA vez al arrancar:
#   real      → CLOUDINARY_URL válido: el SDK oficial firma tickets, verifica respuestas y genera URLs firmadas
#               de entrega `authenticated` (miniatura, revision, original).
#   simulado  → solo APP_ENV=dev y sin CLOUDINARY_URL: un Cloudinary local (app `simulador`) con la MISMA firma
#               (api_sign_request / verify_api_response_signature del SDK) para probar el flujo completo de la app
#               en la laptop: ticket → subida → confirmación → worker → bandeja. Nunca se activa en piloto.
#
# Reglas: el API secret nunca sale del servidor (W-09); las URLs firmadas se generan al renderizar y no se guardan
# (W-10); la web nunca llama a la Admin API (14.3).
import hashlib
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.utils
from django.conf import settings
from django.urls import reverse

log = logging.getLogger("riachuelo.nube")

REAL, SIMULADO, SIN_CONFIGURAR = "real", "simulado", "sin_configurar"
SIM_CLOUD_NAME = "riachuelo-simulado"
SIM_API_KEY = "000000000000000"

# Transformaciones con nombre creadas en la consola de Cloudinary (28.7 del maestro móvil, 14.1 del Maestro Web).
VARIANTS = {
    "miniatura": "miniatura",  # c_limit,w_400,q_auto — bandeja, listas, sesiones
    "revision": "revision",  # c_limit,w_1600,q_auto — visor del caso
    "original": None,  # archivo original — solo al pulsar «Original» en el visor
}
SIM_VARIANT_WIDTH = {"miniatura": 400, "revision": 1600, "original": None}

_modo = None


def _url_valida(url: str) -> bool:
    if not url or "<" in url or ">" in url:
        return False
    p = urlparse(url)
    return p.scheme == "cloudinary" and bool(p.username) and bool(p.password) and bool(p.hostname)


def _sim_secret() -> str:
    # Secreto del simulado derivado de la clave de Django: estable entre reinicios si hay DJANGO_SECRET_KEY en .env.
    return hashlib.sha256(("cloudinary-simulado:" + settings.SECRET_KEY).encode()).hexdigest()[:27]


def configurar():
    """Configura el SDK según el entorno. Se llama en EvidenciasConfig.ready()."""
    global _modo
    if _url_valida(settings.CLOUDINARY_URL):
        p = urlparse(settings.CLOUDINARY_URL)
        cloudinary.config(cloud_name=p.hostname, api_key=p.username, api_secret=p.password, secure=True)
        _modo = REAL
    elif settings.APP_ENV != "piloto":
        cloudinary.config(cloud_name=SIM_CLOUD_NAME, api_key=SIM_API_KEY, api_secret=_sim_secret(), secure=True)
        _modo = SIMULADO
    else:
        _modo = SIN_CONFIGURAR  # diagnostico/checks.py lo informa como error en piloto
    return _modo


def modo() -> str:
    return _modo or configurar()


def es_simulado() -> bool:
    return modo() == SIMULADO


class NubeNoConfigurada(Exception):
    pass


def _exigir_configuracion():
    if modo() == SIN_CONFIGURAR:
        raise NubeNoConfigurada("Falta CLOUDINARY_URL: no se pueden firmar tickets ni URLs de fotos.")


# ------------------------------------------------------------------ public_id (D-32)
def public_id_for(session_id, pass_id, capture_id) -> str:
    return f"riachuelo/{settings.CLOUDINARY_ENV_PREFIX}/{session_id}/{pass_id}/{capture_id}"


# ------------------------------------------------------------------ ticket de subida (15.7, paso 1)
def build_upload_ticket(public_id: str, base_url: str = "") -> dict:
    """Parámetros firmados para subir UNA foto (timestamp del servidor; vigencia 1 hora en Cloudinary).
    base_url solo se usa en modo simulado: la app sube a la misma dirección con la que llamó a la API
    (p. ej. http://192.168.1.50:8000 en la red de la laptop)."""
    _exigir_configuracion()
    import time

    timestamp = int(time.time())
    params = {"timestamp": timestamp, "public_id": public_id, "type": "authenticated", "overwrite": "false"}
    cfg = cloudinary.config()
    signature = cloudinary.utils.api_sign_request(params, cfg.api_secret)
    fields = {k: str(v) for k, v in params.items()}
    fields.update({"api_key": cfg.api_key, "signature": signature})
    server_time = datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)
    if es_simulado():
        url = (base_url or settings.PUBLIC_BASE_URL).rstrip("/") + reverse("simulador:subir", args=[cfg.cloud_name])
    else:
        url = f"https://api.cloudinary.com/v1_1/{cfg.cloud_name}/image/upload"
    return {
        "url": url,
        "fields": fields,
        "publicId": public_id,
        "expiresAt": _iso(server_time + timedelta(hours=1)),
        "maxBytes": settings.CLOUDINARY_MAX_UPLOAD_BYTES,
        "serverTime": _iso(server_time),
    }


def verify_cloudinary_result(expected_public_id: str, size_bytes: int, result: dict):
    """Devuelve el código de error de la sección 15.3 o None si el resultado de Cloudinary es válido."""
    _exigir_configuracion()
    if result["publicId"] != expected_public_id or int(result["bytes"]) != int(size_bytes):
        return "UPLOAD_MISMATCH"
    ok = cloudinary.utils.verify_api_response_signature(result["publicId"], result["version"], result["signature"])
    return None if ok else "UPLOAD_SIGNATURE_INVALID"


# ------------------------------------------------------------------ subida por el servidor (compatibilidad app v1)
class SubidaFallida(Exception):
    pass


def subir_desde_servidor(public_id: str, data: bytes) -> dict:
    """La app v1 (Fase 4 sin migrar) envía el JPEG por multipart a POST /captures/upload: el servidor lo sube a
    Cloudinary con los mismos parámetros que firmaría en el ticket (authenticated, overwrite=false) y devuelve el
    resultado con la forma de CloudinaryResultSerializer, para confirmarlo por el mismo camino que la v2.0."""
    _exigir_configuracion()
    if es_simulado():
        from simulador.views import guardar_foto

        meta, error = guardar_foto(public_id, data, sobrescribir=False)
        if error:
            raise SubidaFallida(error)
    else:
        import io

        import cloudinary.exceptions
        import cloudinary.uploader

        try:
            meta = cloudinary.uploader.upload(io.BytesIO(data), public_id=public_id, type="authenticated",
                                              overwrite=False, resource_type="image")
        except cloudinary.exceptions.Error as exc:
            raise SubidaFallida(str(exc)) from exc
    return {"publicId": meta["public_id"], "version": int(meta["version"]), "signature": meta.get("signature", ""),
            "bytes": int(meta["bytes"]), "format": meta.get("format") or "", "width": meta.get("width"),
            "height": meta.get("height"), "etag": meta.get("etag") or ""}


# ------------------------------------------------------------------ URLs firmadas para la web (W-10)
def signed_image_url(capture, variant="revision") -> str:
    if variant not in VARIANTS:
        raise ValueError(f"Variante desconocida: {variant}")
    if es_simulado():
        # Fotos locales del simulado (o generadas de demostración); la vista exige sesión iniciada.
        return reverse("simulador:foto", args=[variant, capture.cloudinary_public_id]) + f"?v={capture.cloudinary_version}"
    options = {"type": "authenticated", "sign_url": True, "secure": True, "version": capture.cloudinary_version}
    named = VARIANTS[variant]
    if named:
        options.update(transformation=named, format="jpg")
    else:
        options["format"] = capture.cloudinary_format or "jpg"
    url, _ = cloudinary.utils.cloudinary_url(capture.cloudinary_public_id, **options)
    return url


# ------------------------------------------------------------------ descarga del original (solo el worker)
def ruta_simulada(public_id: str) -> Path:
    seguro = public_id.replace("..", "_").strip("/")
    return Path(settings.MEDIA_ROOT) / "cloudinary_simulado" / f"{seguro}.jpg"


def download_original(capture, timeout=None) -> bytes:
    """Bytes del original (el worker analiza a resolución completa: tiling, 28.8). En simulado sin archivo real
    devuelve una foto de demostración generada para ese public_id."""
    _exigir_configuracion()
    if es_simulado():
        path = ruta_simulada(capture.cloudinary_public_id)
        if path.exists():
            return path.read_bytes()
        from simulador.fotos import foto_demo_jpeg

        return foto_demo_jpeg(capture.cloudinary_public_id, None)
    import requests

    url = signed_image_url(capture, "original")
    resp = requests.get(url, timeout=timeout or settings.IA_DESCARGA_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
