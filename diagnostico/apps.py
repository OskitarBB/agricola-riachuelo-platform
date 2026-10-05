from django.apps import AppConfig


class DiagnosticoConfig(AppConfig):
    name = "diagnostico"
    verbose_name = "Diagnóstico"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from diagnostico import checks  # noqa: F401 — registra las comprobaciones de `manage.py check`
        from diagnostico.arranque import anunciar_arranque

        anunciar_arranque()
