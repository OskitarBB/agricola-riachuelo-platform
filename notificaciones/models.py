# notificaciones/models.py — Destinatarios y cola de avisos de WhatsApp (tablas notification_recipients, notifications).
import uuid

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from campo.models import FieldLot
from cuentas.models import User
from revision.models import Case, HumanReview
from config.restricciones import checks_de_opciones

phone_e164 = RegexValidator(r"^\+[1-9]\d{7,14}$", "Usa el formato internacional, p. ej. +51987654321.")


@checks_de_opciones
class NotificationRecipient(models.Model):
    """(web v1.0) Persona que recibe el aviso de un caso confirmado (CU8: jefe de fundo y supervisor de zona)."""

    class RoleLabel(models.TextChoices):
        JEFE_FUNDO = "JEFE_FUNDO", "Jefe de fundo"
        SUPERVISOR_ZONA = "SUPERVISOR_ZONA", "Supervisor de zona"
        OTRO = "OTRO", "Otro"

    full_name = models.CharField("nombre", max_length=150)
    phone_e164 = models.CharField("celular (E.164)", max_length=16, validators=[phone_e164])
    role_label = models.CharField("función", max_length=16, choices=RoleLabel.choices)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                             verbose_name="cuenta de la web",
                             help_text="Cuenta de la web con la que abre el enlace del caso")
    lots = models.ManyToManyField(FieldLot, blank=True, related_name="+", db_table="notification_recipient_lots",
                                  verbose_name="lotes", help_text="Vacío = todos los lotes")
    opt_in_at = models.DateTimeField(null=True, blank=True, help_text="Fecha en que aceptó recibir avisos")
    active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notification_recipients"
        ordering = ["full_name"]
        verbose_name = "destinatario"

    def __str__(self):
        return f"{self.full_name} ({self.get_role_label_display()})"


class NotificationStatus(models.TextChoices):
    NO_APLICA = "NO_APLICA", "No aplica"  # en filas: aviso pendiente anulado por una corrección (8.5)
    PENDIENTE_ENVIO = "PENDIENTE_ENVIO", "Pendiente de envío"
    ENVIADO = "ENVIADO", "Enviado"
    ERROR_ENVIO = "ERROR_ENVIO", "Error de envío"


@checks_de_opciones
class Notification(models.Model):
    class Kind(models.TextChoices):
        CASO_CONFIRMADO = "CASO_CONFIRMADO", "Caso confirmado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="notifications")
    review = models.ForeignKey(HumanReview, on_delete=models.PROTECT, related_name="notifications")
    recipient = models.ForeignKey(NotificationRecipient, on_delete=models.PROTECT, related_name="notifications")
    channel = models.CharField(max_length=10, default="WHATSAPP")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CASO_CONFIRMADO)
    recipient_name = models.CharField(max_length=150)  # copia al encolar (auditoría)
    recipient_phone = models.CharField(max_length=16)
    status = models.CharField(max_length=16, choices=NotificationStatus.choices,
                              default=NotificationStatus.PENDIENTE_ENVIO)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=80, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notifications"
        constraints = [models.UniqueConstraint(fields=["review", "recipient"], name="aviso_unico_por_decision")]
        indexes = [models.Index(fields=["status", "available_at"], name="aviso_cola_idx")]
        verbose_name = "aviso"
