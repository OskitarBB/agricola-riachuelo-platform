"""Read-oriented evidence admin."""
from django.contrib import admin

from evidencias.models import Capture, QualityResult


@admin.register(Capture)
class CaptureAdmin(admin.ModelAdmin):
    list_display = ("capture_id", "session", "row", "quality_status", "captured_at")
    list_filter = ("quality_status", "captured_at")
    search_fields = ("capture_id", "cloudinary_public_id", "marker_code")
    readonly_fields = ("created_at",)


admin.site.register(QualityResult)
