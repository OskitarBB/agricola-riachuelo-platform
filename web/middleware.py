# web/middleware.py
from django.utils.cache import add_never_cache_headers, patch_vary_headers


class NoStoreForAuthenticatedMiddleware:
    """Las páginas con datos de casos y URLs firmadas no se guardan en cachés ni en el historial del navegador."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            if not response.has_header("X-Foto-Demo"):  # fotos del Cloudinary simulado (solo dev): caché privada
                add_never_cache_headers(response)
            patch_vary_headers(response, ("HX-Request",))  # la misma URL devuelve página completa o fragmento
        return response
