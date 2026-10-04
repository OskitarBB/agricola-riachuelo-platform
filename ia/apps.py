from django.apps import AppConfig


class IaConfig(AppConfig):
    """AI task queue and model outputs processed outside HTTP requests."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "ia"
