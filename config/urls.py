# config/urls.py — Rutas raíz: /gestion/ (Django Admin), /api/v1/ (app móvil), / (web de revisión).
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponsePermanentRedirect
from django.templatetags.static import static
from django.urls import include, path

admin.site.site_header = "Riachuelo · Gestión"
admin.site.site_title = "Riachuelo · Gestión"
admin.site.index_title = "Catálogos, perfiles de calidad y modelos de IA"


def favicon(request):
    # Los navegadores piden /favicon.ico aunque la página declare otro ícono; se resuelve en cada petición
    # para respetar el nombre con hash de whitenoise (CompressedManifestStaticFilesStorage).
    return HttpResponsePermanentRedirect(static("web/img/favicon.ico"))


urlpatterns = [
    path("gestion/", admin.site.urls),  # Django Admin (solo superusuarios, DW-19)
    path("api/v1/", include("api.v1.urls")),  # API de la app móvil (Maestro App Móvil, sección 15)
    path("diagnostico/", include("diagnostico.urls")),  # v1.0+: errores del navegador → consola del servidor
    path("favicon.ico", favicon),
    path("", include("web.urls")),
]

# v1.0+: Cloudinary simulado y fotos locales SOLO en desarrollo sin CLOUDINARY_URL (nunca en piloto).
if settings.APP_ENV != "piloto":
    urlpatterns.insert(0, path("dev/", include("simulador.urls")))

handler403 = "web.errors.forbidden"
