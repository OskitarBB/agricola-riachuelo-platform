from django.apps import AppConfig


class EvidenciasConfig(AppConfig):
    name = "evidencias"
    verbose_name = "Evidencias (fotos)"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Configura el SDK de Cloudinary (real o simulado de desarrollo) una sola vez por proceso.
        from evidencias import nube

        nube.configurar()
