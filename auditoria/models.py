# auditoria/models.py — Historial de cambios (tabla audit_events). Solo se inserta; nunca se edita ni se borra.
from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    entity_type = models.CharField(max_length=40)  # "case", "user", "ai_task", "notification_recipient"…
    entity_id = models.CharField(max_length=64)
    action = models.CharField(max_length=40)  # "CASO_DECIDIDO", "CUENTA_APROBADA"…
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    timestamp = models.DateTimeField(default=timezone.now)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    trace_id = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "audit_events"
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["entity_type", "entity_id"], name="auditoria_entidad_idx"),
                   models.Index(fields=["timestamp"], name="auditoria_fecha_idx")]
        verbose_name = "evento de auditoría"
        verbose_name_plural = "eventos de auditoría"
