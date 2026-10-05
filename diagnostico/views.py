# diagnostico/views.py — Errores del navegador (JavaScript, HTMX, fotos o mapa que no cargan) → consola del servidor.
# Así un problema que ve el especialista en su pantalla queda escrito en la terminal donde corre la plataforma,
# con la página, el usuario y el traceId. Lleva CSRF (no es csrf_exempt) y un tope por IP para que no se abuse.
import json
import logging

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.http import require_POST

log = logging.getLogger("riachuelo.navegador")
MAX_POR_MINUTO = 30


@require_POST
def error_cliente(request):
    ip = request.META.get("REMOTE_ADDR", "?")
    key = f"errores-cliente:{ip}"
    n = cache.get(key, 0)
    if n >= MAX_POR_MINUTO:
        return HttpResponse(status=204)
    cache.set(key, n + 1, 60)
    try:
        data = json.loads(request.body[:8000] or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    quien = request.user.email if request.user.is_authenticated else "anónimo"
    tipo = str(data.get("tipo", "error"))[:40]
    mensaje = str(data.get("mensaje", ""))[:500]
    pagina = str(data.get("pagina", ""))[:300]
    detalle = str(data.get("detalle", ""))[:1500]
    nivel = logging.WARNING if tipo in ("foto", "red", "lento") else logging.ERROR
    log.log(nivel, "Navegador (%s) en %s · %s: %s%s", quien, pagina, tipo, mensaje,
            f"\n      {detalle}" if detalle else "")
    return HttpResponse(status=204)
