from django.apps import AppConfig


class ApiConfig(AppConfig):
    """Small API surface kept separate from the web views."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
