"""Admin registration kept conservative; operational role changes live in the web."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from cuentas.models import MobileDevice, User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "full_name", "status", "is_staff", "is_active")
    list_filter = ("status", "is_staff", "is_superuser", "user_roles__role")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    inlines = [UserRoleInline]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Riachuelo", {"fields": ("full_name", "status", "must_change_password", "approved_by", "approved_at")}),
    )


@admin.register(MobileDevice)
class MobileDeviceAdmin(admin.ModelAdmin):
    list_display = ("code", "owner", "platform", "last_sync_at", "battery_percent", "is_revoked")
    list_filter = ("platform", "is_revoked")
    search_fields = ("code", "owner__email", "owner__full_name")
