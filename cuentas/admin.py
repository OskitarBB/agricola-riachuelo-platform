from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from cuentas.models import Device, PasswordResetRequest, User, UserRole


class UserRoleInline(admin.TabularInline):
    """Solo lectura: los roles se cambian en la web (WEB-13) para pasar por cuentas.services y la auditoría."""

    model = UserRole
    extra = 0
    can_delete = False
    readonly_fields = ("role", "assigned_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    # Aprobar, rechazar, bloquear, roles y contraseña temporal se hacen en la web (WEB-13): cuentas.services + auditoría.
    # Aquí solo se editan datos de contacto y, por un superusuario, is_staff / is_superuser (excepción a W-15:
    # Django lo registra en django_admin_log).
    list_display = ("full_name", "email", "status", "must_change_password", "is_staff", "created_at")
    list_filter = ("status", "is_staff", "user_roles__role")
    search_fields = ("full_name", "email", "employee_code")
    readonly_fields = ("password", "status", "must_change_password", "approved_by", "approved_at", "created_at",
                       "last_login", "accepted_privacy_notice_at")
    exclude = ("groups", "user_permissions")
    inlines = [UserRoleInline]

    def has_add_permission(self, request):
        # v1.1 (ADR-W-005, W-03): las cuentas se crean en la web (Usuarios → «Nueva cuenta») o desde la app, para que
        # pasen por cuentas.services (reglas de roles, contraseña temporal y auditoría). El primer administrador del
        # servidor se crea con `python manage.py createsuperuser`.
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # las cuentas se rechazan o bloquean, no se borran (trazabilidad)


@admin.register(Device)
class DeviceAdmin(ReadOnlyAdmin):  # revocar: WEB-14
    list_display = ("device_id", "model", "platform", "app_version", "user", "last_seen_at", "revoked_at")


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(ReadOnlyAdmin):  # se atienden con «Contraseña temporal» en WEB-13
    list_display = ("email", "user", "requested_at", "status", "handled_by", "handled_at")
