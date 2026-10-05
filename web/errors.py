# web/errors.py — 403 legible (también para HTMX: el fragmento muestra el motivo en lugar de romper la pantalla).
from django.shortcuts import render


def forbidden(request, exception=None):
    template = "web/partials/error.html" if getattr(request, "htmx", False) else "web/403.html"
    return render(request, template, {"mensaje": "No tienes permiso para esta acción."}, status=403)
