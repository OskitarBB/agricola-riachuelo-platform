from django.apps import AppConfig


class NotificacionesConfig(AppConfig):
    """Notification recipients, outbound queue and WhatsApp clients."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "notificaciones"
