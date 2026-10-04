from django.apps import AppConfig


class RevisionConfig(AppConfig):
    """Human review rules for detections and evidence decisions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "revision"
