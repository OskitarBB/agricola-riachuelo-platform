from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from ia.models import AiTask, Detection, ModelConfig


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "active", "conf_threshold", "review_threshold", "auto_confirm_threshold",
                    "created_at")


@admin.register(AiTask)
class AiTaskAdmin(ReadOnlyAdmin):
    list_display = ("task_id", "status", "attempts", "model_version", "processing_ms", "requested_at")
    list_filter = ("status",)


@admin.register(Detection)
class DetectionAdmin(ReadOnlyAdmin):
    list_display = ("task", "class_name", "confidence", "review_status")
