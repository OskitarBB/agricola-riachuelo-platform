"""Notification queue admin."""
from django.contrib import admin

from notificaciones.models import Notification, NotificationRecipient


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_e164", "lot", "is_active")
    list_filter = ("is_active", "lot")
    search_fields = ("name", "phone_e164")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("notification_id", "case", "recipient", "status", "attempts", "sent_at")
    list_filter = ("status", "created_at")
    search_fields = ("notification_id", "case__case_id", "recipient__phone_e164")
