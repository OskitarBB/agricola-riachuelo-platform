"""Account, role and device models.

The web uses Django sessions, but the same user table can also back JWT flows
for the mobile API. Role changes go through services/views, not ad-hoc admin
actions, so they can be audited.
"""
import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class AccountStatus(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    ACTIVO = "ACTIVO", "Activo"
    RECHAZADO = "RECHAZADO", "Rechazado"
    BLOQUEADO = "BLOQUEADO", "Bloqueado"


class Role(models.TextChoices):
    OPERADOR_CAMPO = "OPERADOR_CAMPO", "Operador de campo"
    ESPECIALISTA_FITOSANITARIO = "ESPECIALISTA_FITOSANITARIO", "Especialista"
    SUPERVISOR = "SUPERVISOR", "Supervisor"
    ADMINISTRADOR = "ADMINISTRADOR", "Administrador"


class UserManager(BaseUserManager):
    """Create users with email as the stable login identifier."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El correo es obligatorio")
        email = self.normalize_email(email)
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("status", AccountStatus.ACTIVO)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Platform user shared by the review web and future API tokens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column="user_id")
    username = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=24, choices=AccountStatus.choices, default=AccountStatus.PENDIENTE)
    must_change_password = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_users",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        ordering = ["email"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.full_name or self.get_full_name() or self.email

    @property
    def roles(self):
        return list(self.user_roles.values_list("role", flat=True))

    def has_role(self, *roles):
        return self.is_superuser or self.user_roles.filter(role__in=roles).exists()

    def activate(self, approver=None):
        self.status = AccountStatus.ACTIVO
        self.approved_by = approver
        self.approved_at = timezone.now()


class UserRole(models.Model):
    """Many-to-one role table; a person may review and supervise."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.CharField(max_length=40, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_roles"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_role"),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.get_role_display()}"


class MobileDevice(models.Model):
    """Device registered by the mobile app and managed from the web."""

    device_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")
    label = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=40, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    battery_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    local_storage_mb = models.PositiveIntegerField(default=0)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mobile_devices"
        ordering = ["code"]

    def __str__(self):
        return self.code
