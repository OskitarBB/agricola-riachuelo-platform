"""Project URL routing.

Admin lives under /gestion/ as requested by the web master document. The API
namespace is present so the mobile contract can grow without touching web URLs.
"""
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("gestion/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("", include("web.urls")),
]
