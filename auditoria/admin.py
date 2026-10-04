"""Audit admin."""
from django.contrib import admin

from auditoria.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id")
    list_filter = ("action", "created_at")
    search_fields = ("actor__email", "action", "target_id")
    readonly_fields = ("actor", "action", "target_type", "target_id", "payload", "created_at")
