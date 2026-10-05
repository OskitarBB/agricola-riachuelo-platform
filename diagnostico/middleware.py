# diagnostico/middleware.py — Una línea en consola por petición (método, ruta, estado, tiempo, usuario y traceId),
# en amarillo los 4xx, en rojo los 5xx y marcadas «LENTA» las que superan LOG_SLOW_MS (RNF-W01).
# La traza completa de un error 500 la escribe el logger django.request (o el manejador de la API) con el mismo traceId.
import logging
import time

from django.conf import settings

from diagnostico.contexto import new_trace_id, reset_trace_id, set_trace_id

log = logging.getLogger("riachuelo.http")

SIN_REGISTRO = ("/static/", "/favicon.ico", "/dev/media/")
# Sondeos automáticos de la web (actividad cada 20 s, bandeja cada 15 s): solo se escriben si fallan o son lentos.
SONDEOS = ("actividad-poll", "bandeja")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trace_id = request.headers.get("X-Trace-Id", "")[:40] or new_trace_id()
        request.trace_id = trace_id
        token = set_trace_id(trace_id)
        inicio = time.perf_counter()
        try:
            response = self.get_response(request)
        except Exception:  # noqa: BLE001 — se registra y se vuelve a lanzar (Django responde 500)
            ms = (time.perf_counter() - inicio) * 1000
            log.error("%s %s → 500 · %.0f ms · excepción no controlada", request.method, request.path, ms)
            reset_trace_id(token)
            raise
        ms = (time.perf_counter() - inicio) * 1000
        response["X-Trace-Id"] = trace_id
        if settings.LOG_REQUESTS and not request.path.startswith(SIN_REGISTRO):
            self._registrar(request, response, ms)
        reset_trace_id(token)
        return response

    def _registrar(self, request, response, ms):
        status = response.status_code
        quien = ""
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            quien = f" · {user.email}"
        elif request.headers.get("X-Device-Id"):
            quien = f" · celular {request.headers['X-Device-Id'][:8]}"
        extra = ""
        if getattr(request, "htmx", False):
            extra = " · htmx"
        code = getattr(response, "api_error_code", "")
        if code:
            extra += f" · {code}"
        lenta = ms >= settings.LOG_SLOW_MS
        linea = f"{request.method} {request.get_full_path()[:160]} → {status} · {ms:.0f} ms{quien}{extra}"
        if lenta:
            linea += f" · LENTA (> {settings.LOG_SLOW_MS} ms)"
        if status >= 500:
            log.error(linea)
        elif status >= 400 or lenta:
            log.warning(linea)
        elif request.headers.get("HX-Trigger") in SONDEOS:
            log.debug(linea)
        else:
            log.info(linea)
