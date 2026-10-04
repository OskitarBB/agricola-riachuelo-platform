from django.apps import AppConfig


class MonitoreoConfig(AppConfig):
    """Read-only field monitoring data synchronized by the mobile app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "monitoreo"
