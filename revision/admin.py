"""Review admin is for inspection; decisions should go through services."""
from django.contrib import admin

from revision.models import Case, HumanReview


class HumanReviewInline(admin.TabularInline):
    model = HumanReview
    extra = 0
    readonly_fields = ("reviewer", "from_status", "to_status", "observation", "created_at")
    can_delete = False


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("case_id", "status", "disease", "decided_by", "decided_at", "opened_at")
    list_filter = ("status", "notification_status", "opened_at")
    search_fields = ("case_id", "capture__capture_id", "disease")
    readonly_fields = ("opened_at", "decided_at")
    inlines = [HumanReviewInline]


admin.site.register(HumanReview)
