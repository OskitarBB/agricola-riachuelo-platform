"""AI queue admin."""
from django.contrib import admin

from ia.models import AITask, Detection, ModelConfig


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "conf_threshold", "is_active")
    list_filter = ("is_active",)


@admin.register(AITask)
class AITaskAdmin(admin.ModelAdmin):
    list_display = ("task_id", "capture", "status", "attempts", "requested_at", "finished_at")
    list_filter = ("status", "requested_at")
    search_fields = ("task_id", "capture__capture_id")


admin.site.register(Detection)
