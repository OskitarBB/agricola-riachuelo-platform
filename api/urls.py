"""Minimal API endpoints for health checks and future mobile routes."""
from django.http import JsonResponse
from django.urls import path


def health(request):
    """Return a cheap health response without touching external services."""
    return JsonResponse({"status": "ok", "service": "riachuelo-platform"})


urlpatterns = [
    path("health/", health, name="health"),
]
