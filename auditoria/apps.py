from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AuditoriaConfig(AppConfig):
    name = "auditoria"
    verbose_name = "Auditoría"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from auditoria.seguridad_bd import asegurar_bd

        post_migrate.connect(asegurar_bd, sender=self, dispatch_uid="auditoria_asegurar_bd")
