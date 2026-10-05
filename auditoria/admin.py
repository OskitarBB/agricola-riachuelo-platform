from django.contrib import admin

from auditoria.models import AuditEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    """Evidencia y trazabilidad: en Django Admin se consultan, nunca se crean, editan ni borran (RN-W08)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("timestamp", "action", "entity_type", "entity_id", "user")
    list_filter = ("action", "entity_type")
    search_fields = ("entity_id", "action")
