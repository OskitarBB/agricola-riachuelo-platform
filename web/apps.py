from django.apps import AppConfig


class WebConfig(AppConfig):
    """Server-rendered review interface with HTMX-friendly views."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "web"
