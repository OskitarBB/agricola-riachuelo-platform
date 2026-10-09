# cuentas/models.py — Usuarios, roles y dispositivos (tablas users, user_roles, devices, password_reset_requests).
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from config.restricciones import checks_de_opciones


class Role(models.TextChoices):
    ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
    OPERADOR_CAMPO = "OPERADOR_CAMPO", "Operador de campo"
    ESPECIALISTA_FITOSANITARIO = "ESPECIALISTA_FITOSANITARIO", "Especialista fitosanitario"
    SUPERVISOR = "SUPERVISOR", "Supervisor"


# Roles que pueden entrar a la web (DW-05). OPERADOR_CAMPO usa solo la app móvil.
WEB_ROLES = frozenset({Role.ADMINISTRADOR, Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR})
# Roles que pueden usar la app móvil (RN-02 del Maestro App Móvil, MOBILE_ALLOWED_ROLES).
# Roles que trabajan en el campo con la app (controlador, cámaras, sincronización).
MOBILE_FIELD_ROLES = frozenset({Role.OPERADOR_CAMPO, Role.ADMINISTRADOR})
# v1.3 (ADR-W-007): roles que pueden ingresar a la app. El especialista entra SOLO a «Ubicar plaga» (lectura): las
# rutas de monitoreo y sincronización exigen MOBILE_FIELD_ROLES (api.permissions.FieldWork).
MOBILE_ROLES = MOBILE_FIELD_ROLES | {Role.ESPECIALISTA_FITOSANITARIO}


class AccountStatus(models.TextChoices):
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION", "Pendiente de aprobación"
    ACTIVO = "ACTIVO", "Activo"
    RECHAZADO = "RECHAZADO", "Rechazado"
    BLOQUEADO = "BLOQUEADO", "Bloqueado"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, roles=(), **extra):
        if not email:
            raise ValueError("El correo es obligatorio")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        for role in roles:
            UserRole.objects.create(user=user, role=role)
        return user

    def create_superuser(self, email, password, **extra):
        extra.setdefault("full_name", "Administrador")
        extra.update(is_staff=True, is_superuser=True, status=AccountStatus.ACTIVO)
        return self.create_user(email, password, roles=[Role.ADMINISTRADOR], **extra)


@checks_de_opciones
class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField("nombre completo", max_length=150)
    email = models.EmailField("correo", unique=True)
    phone = models.CharField("celular", max_length=20, blank=True)
    employee_code = models.CharField("código de trabajador", max_length=30, blank=True)
    status = models.CharField(max_length=24, choices=AccountStatus.choices,
                              default=AccountStatus.PENDIENTE_APROBACION, db_index=True)
    must_change_password = models.BooleanField(default=False)
    is_staff = models.BooleanField("acceso a Django Admin", default=False)
    accepted_privacy_notice_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    approved_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        db_table = "users"
        verbose_name = "usuario"

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    # Django invalida la sesión web en la siguiente petición si is_active es False (ModelBackend.get_user):
    # bloquear o rechazar una cuenta la saca de la web sin esperar a que caduque la cookie.
    @property
    def is_active(self):
        return self.status == AccountStatus.ACTIVO

    @property
    def roles(self) -> frozenset:
        cached = getattr(self, "_roles_cache", None)
        if cached is None:
            prefetched = getattr(self, "_prefetched_objects_cache", {}).get("user_roles")
            if prefetched is not None:  # listas con prefetch_related("user_roles"): sin consulta extra
                cached = frozenset(r.role for r in prefetched)
            else:
                cached = frozenset(UserRole.objects.filter(user_id=self.pk).values_list("role", flat=True))
            self._roles_cache = cached
        return cached

    @property
    def role_labels(self) -> list:
        return [Role(r).label for r in sorted(self.roles)]

    def has_role(self, *roles) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def can_use_web(self) -> bool:
        return self.is_active and bool(self.roles & WEB_ROLES)

    @property
    def can_use_app(self) -> bool:
        return bool(self.roles & MOBILE_ROLES)

    @property
    def initials(self) -> str:
        parts = [p for p in (self.full_name or self.email).split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"


@checks_de_opciones
class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.CharField(max_length=32, choices=Role.choices)
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "user_roles"
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="user_roles_unico")]

    def __str__(self):
        return f"{self.user_id}:{self.role}"


class Platform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"


@checks_de_opciones
class Device(models.Model):
    """Instalación de la app móvil (deviceId generado en el celular, RF-11 del maestro móvil)."""

    device_id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="devices", help_text="Último usuario que inició sesión")
    platform = models.CharField(max_length=10, choices=Platform.choices)
    model = models.CharField(max_length=80, blank=True)
    os_version = models.CharField(max_length=40, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")

    class Meta:
        db_table = "devices"

    def __str__(self):
        return f"{self.model or self.platform} ({str(self.device_id)[:8]})"


@checks_de_opciones
class PasswordResetRequest(models.Model):
    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ATENDIDA = "ATENDIDA", "Atendida"
        DESCARTADA = "DESCARTADA", "Descartada"

    email = models.EmailField()
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    requested_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDIENTE)
    handled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "password_reset_requests"
        ordering = ["-requested_at"]
