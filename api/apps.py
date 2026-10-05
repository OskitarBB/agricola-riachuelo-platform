from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "api"
    verbose_name = "API de la app móvil"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from api import schema  # noqa: F401 — registra la extensión de autenticación en drf-spectacular
