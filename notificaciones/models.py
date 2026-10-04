"""Outbound WhatsApp notification queue."""
import uuid

from django.db import models


class NotificationStatus(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    TOMADA = "TOMADA", "Tomada"
    ENVIADA = "ENVIADA", "Enviada"
    ERROR_REINTENTABLE = "ERROR_REINTENTABLE", "Error reintentable"
    ERROR_FINAL = "ERROR_FINAL", "Error final"
    ANULADA = "ANULADA", "Anulada"


class NotificationRecipient(models.Model):
    recipient_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    phone_e164 = models.CharField(max_length=24)
    lot = models.ForeignKey("monitoreo.Lot", null=True, blank=True, on_delete=models.SET_NULL, related_name="notification_recipients")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_recipients"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} {self.phone_e164}"


class Notification(models.Model):
    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("revision.Case", on_delete=models.CASCADE, related_name="notifications")
    recipient = models.ForeignKey(NotificationRecipient, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=24, choices=NotificationStatus.choices, default=NotificationStatus.PENDIENTE)
    payload = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    available_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=120, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "available_at"], name="idx_notification_queue")]

    def __str__(self):
        return f"{self.case_id} -> {self.recipient}"
