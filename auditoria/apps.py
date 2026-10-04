from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    """Append-only audit events and database security checks."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "auditoria"
