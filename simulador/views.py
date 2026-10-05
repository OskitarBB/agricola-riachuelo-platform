# simulador/views.py — Cloudinary simulado para desarrollo (evidencias/nube.py, modo «simulado»).
#
# subir: recibe el multipart que la app envía a `ticket.url` (file + los `fields` firmados), comprueba la firma con
#        el mismo algoritmo del SDK, guarda el JPEG en media/cloudinary_simulado/<public_id>.jpg y responde con la
#        forma de la Upload API (public_id, version, signature, bytes, format, width, height, etag, existing).
#        No usa la sesión ni CSRF: emula un servicio externo que se autentica por firma (como Cloudinary).
# foto:  entrega la foto a la web (variante miniatura/revision/original) solo con sesión iniciada (W-10).
import hashlib
import io
import json
import logging
import time

import cloudinary
import cloudinary.utils
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, ImageOps

from evidencias import nube
from simulador.fotos import foto_demo_jpeg, foto_real_jpeg

log = logging.getLogger("riachuelo.simulador")
NO_FIRMADOS = {"file", "api_key", "signature", "resource_type", "cloud_name"}


def _error(status, message):
    log.warning("Cloudinary simulado rechazó la subida: %s", message)
    return JsonResponse({"error": {"message": message}}, status=status)


@csrf_exempt
@require_POST
def subir(request, cloud):
    if not nube.es_simulado():
        raise Http404
    cfg = cloudinary.config()
    if cloud != cfg.cloud_name:
        return _error(404, f"Unknown cloud name: {cloud}")
    if request.POST.get("api_key") != cfg.api_key:
        return _error(401, "Invalid api_key")
    params = {k: v for k, v in request.POST.items() if k not in NO_FIRMADOS}
    esperado = cloudinary.utils.api_sign_request(params, cfg.api_secret)
    if request.POST.get("signature") != esperado:
        return _error(401, "Invalid Signature. String to sign - '%s'." % cloudinary.utils.api_string_to_sign(params))
    try:
        ts = int(params.get("timestamp", "0"))
    except ValueError:
        ts = 0
    if abs(time.time() - ts) > 3600:
        return _error(400, f"Stale request - reported time is {ts} which is more than 1 hour ago")
    archivo = request.FILES.get("file")
    if archivo is None:
        return _error(400, "Missing required parameter - file")
    if archivo.size > settings.CLOUDINARY_MAX_UPLOAD_BYTES:
        return _error(400, f"File size too large. Got {archivo.size}. Maximum is {settings.CLOUDINARY_MAX_UPLOAD_BYTES}.")
    public_id = params.get("public_id", "")
    if not public_id:
        return _error(400, "Missing public_id")
    meta, error = guardar_foto(public_id, archivo.read(), sobrescribir=params.get("overwrite") != "false")
    if error:
        return _error(400, error)
    return JsonResponse(meta)


def guardar_foto(public_id, data, sobrescribir=False):
    """Guarda el JPEG en media/cloudinary_simulado/ y devuelve (meta, error) con la forma de la Upload API de
    Cloudinary, firmada como Cloudinary (signature_version=1 sobre public_id + version). Lo usan la subida directa
    de la app (v2.0) y la subida por el servidor (compatibilidad con la app v1, evidencias.nube)."""
    cfg = cloudinary.config()
    path = nube.ruta_simulada(public_id)
    meta_path = path.with_suffix(".json")
    if path.exists() and not sobrescribir and meta_path.exists():
        meta = json.loads(meta_path.read_text())  # overwrite = false: se devuelve el recurso existente
        meta["existing"] = True
        log.info("Cloudinary simulado: %s ya existía (existing=true)", public_id)
        return meta, None
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        width, height, fmt = img.width, img.height, (Image.open(io.BytesIO(data)).format or "JPEG").lower()
    except Exception:  # noqa: BLE001
        return None, "Invalid image file"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    version = int(time.time())
    firma = cloudinary.utils.api_sign_request({"public_id": public_id, "version": version}, cfg.api_secret,
                                              signature_version=1)
    meta = {
        "public_id": public_id, "version": version, "signature": firma, "bytes": len(data),
        "format": "jpg" if fmt in ("jpeg", "jpg", "mpo") else fmt, "width": width, "height": height,
        "etag": hashlib.md5(data).hexdigest(), "type": "authenticated", "resource_type": "image",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(version)),
    }
    meta_path.write_text(json.dumps(meta))
    log.info("Cloudinary simulado: foto recibida %s (%s bytes, %s×%s)", public_id, len(data), width, height)
    return meta, None


@require_GET
def foto(request, variant, public_id):
    if not nube.es_simulado() or variant not in nube.VARIANTS:
        raise Http404
    user = request.user
    if not (user.is_authenticated and user.can_use_web):
        return HttpResponse(status=403)
    width = nube.SIM_VARIANT_WIDTH[variant]
    path = nube.ruta_simulada(public_id)
    data = foto_real_jpeg(path, width) if path.exists() else foto_demo_jpeg(public_id, width)
    resp = HttpResponse(data, content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=3600"
    resp["X-Foto-Demo"] = "0" if path.exists() else "1"
    return resp
