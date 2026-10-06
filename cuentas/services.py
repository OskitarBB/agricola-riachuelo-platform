# cuentas/services.py — Reglas de cuentas y celulares.
#   · Acciones del ADMINISTRADOR en la web (WEB-13, WEB-14; Anexo C.5 del Maestro Web).
#   · v1.1 (ADR-W-005): alta de cuentas desde la web y tipos de cuenta (app o web) — validate_roles, create_account.
#   · Autenticación de la app móvil (Maestro App Móvil §7, §15.2 y §28.6): registro, login con datos del dispositivo,
#     renovación con rotación, cierre, cambio de contraseña y pedidos de restablecimiento.
import logging
import secrets
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from api.errors import ApiError
from auditoria import services as audit
from cuentas.models import MOBILE_ROLES, WEB_ROLES, AccountStatus, Device, PasswordResetRequest, Role, User, UserRole
from cuentas.validators import PHONE_RE

log = logging.getLogger("riachuelo.cuentas")

TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"  # sin 0/O/1/l/I
STATUS_ERRORS = {
    AccountStatus.PENDIENTE_APROBACION: "ACCOUNT_PENDING",
    AccountStatus.RECHAZADO: "ACCOUNT_REJECTED",
    AccountStatus.BLOQUEADO: "ACCOUNT_BLOCKED",
}


# ================================================================== administración (web)
def _require_admin(admin):
    if not (admin and admin.is_authenticated and admin.is_active and admin.has_role(Role.ADMINISTRADOR)):
        raise PermissionDenied("Solo el administrador gestiona cuentas")


def _blacklist_refresh_tokens(user):
    """Cierra la sesión de la app en todos los celulares del usuario (lista negra de SimpleJWT)."""
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    for token in OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now()):
        BlacklistedToken.objects.get_or_create(token=token)


# Tipos de cuenta (v1.1, ADR-W-005). Una persona del campo y una de la web tienen cuentas distintas:
#   · cuenta de la APP  → solo OPERADOR_CAMPO (rol único). Entra únicamente a la app móvil.
#   · cuenta de la WEB  → ESPECIALISTA_FITOSANITARIO, SUPERVISOR y/o ADMINISTRADOR (los permisos se suman, DW-04).
#     ADMINISTRADOR también puede usar la app (MOBILE_ROLES), por eso no necesita el rol de operador.
ROLES_DE_LA_APP = frozenset({Role.OPERADOR_CAMPO})
ROLES_DE_LA_WEB = WEB_ROLES
MSG_ROLES_VACIOS = "Elige al menos un rol válido."
MSG_OPERADOR_SOLO = ("«Operador de campo» va solo: esa cuenta es para la app móvil. Si la persona también trabaja en "
                     "la web, crea otra cuenta con otro correo.")


def validate_roles(roles) -> set:
    """Comprueba la combinación de roles de una cuenta. Devuelve el conjunto o lanza ValidationError({"roles": …})."""
    roles = set(roles or ())
    if not roles or not roles <= set(Role.values):
        raise ValidationError({"roles": MSG_ROLES_VACIOS})
    if Role.OPERADOR_CAMPO in roles and len(roles) > 1:
        raise ValidationError({"roles": MSG_OPERADOR_SOLO})
    return roles


def account_kind(roles) -> str:
    """«APP», «WEB» o «WEB_Y_APP» (administrador) según los roles."""
    roles = set(roles)
    if roles and roles <= ROLES_DE_LA_APP:
        return "APP"
    return "WEB_Y_APP" if Role.ADMINISTRADOR in roles else "WEB"


def set_roles(user_id, admin, roles):
    _require_admin(admin)
    roles = validate_roles(roles)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        before = sorted(user.roles)
        if user.pk == admin.pk and Role.ADMINISTRADOR not in roles:
            raise ValidationError({"roles": "No puedes quitarte el rol de administrador a ti mismo."})
        UserRole.objects.filter(user=user).exclude(role__in=roles).delete()
        for role in roles - set(before):
            UserRole.objects.create(user=user, role=role)
        audit.record("user", user.pk, "ROLES_CAMBIADOS", admin, {"roles": before}, {"roles": sorted(roles)})
    return user


def approve_user(user_id, admin, roles):
    _require_admin(admin)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if user.status != AccountStatus.PENDIENTE_APROBACION:
            raise ValidationError("La cuenta no está pendiente de aprobación.")
        set_roles(user.pk, admin, roles)
        user.status, user.approved_by, user.approved_at = AccountStatus.ACTIVO, admin, timezone.now()
        user.save(update_fields=["status", "approved_by", "approved_at"])
        audit.record("user", user.pk, "CUENTA_APROBADA", admin,
                     {"status": AccountStatus.PENDIENTE_APROBACION}, {"status": AccountStatus.ACTIVO})
    return user


def change_status(user_id, admin, new_status):
    """Rechazar (pendiente → RECHAZADO), bloquear (ACTIVO → BLOQUEADO) o desbloquear (BLOQUEADO → ACTIVO)."""
    _require_admin(admin)
    allowed = {
        AccountStatus.PENDIENTE_APROBACION: {AccountStatus.RECHAZADO},
        AccountStatus.ACTIVO: {AccountStatus.BLOQUEADO},
        AccountStatus.BLOQUEADO: {AccountStatus.ACTIVO},
    }
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if user.pk == admin.pk:
            raise ValidationError("No puedes cambiar el estado de tu propia cuenta.")
        if new_status not in allowed.get(user.status, set()):
            raise ValidationError("Cambio de estado no permitido.")
        before = user.status
        user.status = new_status
        user.save(update_fields=["status"])
        if new_status == AccountStatus.BLOQUEADO:
            _blacklist_refresh_tokens(user)  # la web la saca en la siguiente petición (User.is_active)
        audit.record("user", user.pk, "CUENTA_ESTADO", admin, {"status": before}, {"status": new_status})
    return user


def _generate_temporary_password() -> str:
    """12 caracteres sin ambiguos (sin 0/O/1/l/I), siempre con letras y números (política de la app y de la web)."""
    while True:
        temp = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(12))
        if any(ch.isdigit() for ch in temp) and any(ch.isalpha() for ch in temp):
            return temp


def set_temporary_password(user_id, admin):
    """D-07: contraseña temporal + cambio obligatorio. Devuelve la contraseña UNA vez para entregarla en persona."""
    _require_admin(admin)
    temp = _generate_temporary_password()  # cumple la política para que la app la acepte sin internet después
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.set_password(temp)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        _blacklist_refresh_tokens(user)
        PasswordResetRequest.objects.filter(
            Q(user=user) | Q(email__iexact=user.email),
            status=PasswordResetRequest.Status.PENDIENTE).update(
            status=PasswordResetRequest.Status.ATENDIDA, handled_by=admin, handled_at=timezone.now())
        audit.record("user", user.pk, "CONTRASENA_TEMPORAL", admin, None, {"mustChangePassword": True})
    return temp


def create_account(admin, full_name, email, roles, phone="", employee_code=""):
    """v1.1 (ADR-W-005): el administrador crea una cuenta ACTIVA desde la web (WEB-13 → «Nueva cuenta»).

    Nace con una contraseña temporal y cambio obligatorio (D-07), aprobada por quien la crea. No hay registro público
    en la web: los operadores siguen pudiendo registrarse desde la app (D-05) y el administrador los aprueba.
    Devuelve (usuario, contraseña_temporal); la contraseña se muestra UNA vez para entregarla en persona.
    """
    _require_admin(admin)
    roles = validate_roles(roles)
    email = (email or "").strip().lower()
    full_name = " ".join((full_name or "").split())
    phone = (phone or "").replace(" ", "")
    employee_code = (employee_code or "").strip()
    errores = {}
    if len(full_name) < 5:
        errores["full_name"] = "Escribe el nombre completo."
    if phone and not PHONE_RE.match(phone):
        errores["phone"] = "Escribe un celular válido (9 a 15 dígitos)."
    existente = User.objects.filter(email__iexact=email).only("status").first() if email else None
    if existente is not None:
        errores["email"] = ("Ese correo ya pidió una cuenta desde la app: apruébala en «Solicitudes pendientes»."
                            if existente.status == AccountStatus.PENDIENTE_APROBACION
                            else "Ya existe una cuenta con ese correo.")
    if errores:
        raise ValidationError(errores)
    temp = _generate_temporary_password()
    now = timezone.now()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email, temp, roles=sorted(roles), full_name=full_name, phone=phone, employee_code=employee_code,
                status=AccountStatus.ACTIVO, must_change_password=True, approved_by=admin, approved_at=now)
            audit.record("user", user.pk, "CUENTA_CREADA", admin, None,
                         {"status": user.status, "roles": sorted(roles), "tipo": account_kind(roles),
                          "mustChangePassword": True})
    except IntegrityError as exc:  # carrera: el mismo correo se registró en la app al mismo tiempo
        raise ValidationError({"email": "Ya existe una cuenta con ese correo."}) from exc
    log.info("Cuenta creada desde la web por %s: %s (%s)", admin.email, email, ", ".join(sorted(roles)))
    return user, temp


def revoke_device(device_id, admin):
    _require_admin(admin)
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device_id)
        if device.revoked_at is None:
            device.revoked_at, device.revoked_by = timezone.now(), admin
            device.save(update_fields=["revoked_at", "revoked_by"])
            audit.record("device", device.pk, "CELULAR_REVOCADO", admin, None,
                         {"revokedAt": device.revoked_at.isoformat()})
    return device


# ================================================================== app móvil (/api/v1/auth/*)
def iso(dt) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def user_profile(user) -> dict:
    """UserProfile del contrato (§11.1 del maestro móvil)."""
    return {"id": str(user.pk), "fullName": user.full_name, "email": user.email, "roles": sorted(user.roles),
            "status": user.status, "mustChangePassword": user.must_change_password}


def ensure_app_access(user):
    """RN-02: solo cuentas ACTIVO con OPERADOR_CAMPO o ADMINISTRADOR (403 con el código del contrato)."""
    if user.status != AccountStatus.ACTIVO:
        raise ApiError(STATUS_ERRORS.get(user.status, "ACCOUNT_BLOCKED"), 403)
    if not (user.roles & MOBILE_ROLES):
        raise ApiError("ROLE_NOT_ALLOWED", 403)


def ensure_device_not_revoked(device_id):
    if device_id and Device.objects.filter(pk=device_id, revoked_at__isnull=False).exists():
        raise ApiError("DEVICE_REVOKED", 403)


def register_user(data, device_id=None):
    """POST /auth/register → cuenta PENDIENTE_APROBACION (D-05). El administrador la aprueba en la web (WEB-13)."""
    email = data["email"].strip().lower()
    candidate = User(email=email, full_name=data["fullName"].strip())
    try:
        validate_password(data["password"], candidate)
    except ValidationError as exc:
        raise ApiError("VALIDATION_ERROR", 400,
                       field_errors=[{"field": "password", "message": " ".join(exc.messages)}]) from exc
    if User.objects.filter(email__iexact=email).exists():
        raise ApiError("EMAIL_ALREADY_REGISTERED", 409)
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email, data["password"], full_name=data["fullName"].strip(),
                phone=(data.get("phone") or "").replace(" ", ""), employee_code=(data.get("employeeCode") or "").strip(),
                status=AccountStatus.PENDIENTE_APROBACION, accepted_privacy_notice_at=timezone.now())
            audit.record("user", user.pk, "CUENTA_REGISTRADA", None, None,
                         {"status": user.status, "deviceId": str(device_id) if device_id else None})
    except IntegrityError as exc:  # carrera: dos registros con el mismo correo a la vez
        raise ApiError("EMAIL_ALREADY_REGISTERED", 409) from exc
    log.info("Nueva solicitud de cuenta desde la app: %s (pendiente de aprobación)", email)
    return user


def _lock_key(email):
    return f"api-login-fallos:{email.lower()}"


def _issue_tokens(user, device_id):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    refresh["device_id"] = str(device_id)  # reclamos mínimos (JWT < 2 KB, Q-06)
    refresh["roles"] = sorted(user.roles)
    access = refresh.access_token
    now = timezone.now()
    return {
        "accessToken": str(access),
        "accessTokenExpiresAt": iso(datetime.fromtimestamp(access["exp"], tz=dt_timezone.utc)),
        "refreshToken": str(refresh),
        "refreshTokenExpiresAt": iso(datetime.fromtimestamp(refresh["exp"], tz=dt_timezone.utc)),
        "user": user_profile(user),
        "serverTime": iso(now),
    }


def app_login(email, password, device):
    """POST /auth/login (§7.4): valida contraseña, estado y rol, registra el celular y emite access + refresh."""
    email = email.strip().lower()
    key = _lock_key(email)
    fails = cache.get(key, 0)
    if fails >= settings.WEB["LOGIN_MAX_FAILED"]:
        raise ApiError("TOO_MANY_ATTEMPTS", 429)
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        User().set_password(password)  # mismo tiempo de respuesta exista o no la cuenta
        ok = False
    else:
        ok = user.check_password(password)
    if not ok:
        cache.set(key, fails + 1, settings.WEB["LOGIN_LOCKOUT_MINUTES"] * 60)
        log.warning("Login de la app rechazado para %s (intento %s)", email, fails + 1)
        raise ApiError("INVALID_CREDENTIALS", 401)
    cache.delete(key)
    ensure_app_access(user)
    ensure_device_not_revoked(device["deviceId"])
    now = timezone.now()
    with transaction.atomic():
        obj, created = Device.objects.select_for_update().get_or_create(
            device_id=device["deviceId"],
            defaults={"platform": device["platform"], "first_seen_at": now})
        obj.user, obj.platform, obj.model = user, device["platform"], device.get("model", "")[:80]
        obj.os_version, obj.app_version = device.get("osVersion", "")[:40], device.get("appVersion", "")[:40]
        obj.last_seen_at = now
        obj.save()
        update_last_login(None, user)
        audit.record("user", user.pk, "INGRESO_APP", user, None,
                     {"deviceId": str(obj.device_id), "model": obj.model, "appVersion": obj.app_version,
                      "nuevoCelular": created})
        tokens = _issue_tokens(user, obj.device_id)
    log.info("Ingreso desde la app: %s en %s %s (app %s)%s", user.email, obj.get_platform_display(), obj.model,
             obj.app_version, " · celular nuevo" if created else "")
    return tokens


def app_refresh(raw_refresh, device_id):
    """POST /auth/refresh: rota el refresh (el anterior va a la lista negra); rechaza celulares revocados y cuentas
    que ya no pueden usar la app (§7.4 punto 9)."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken

    try:
        old = RefreshToken(raw_refresh)  # firma, vencimiento y lista negra
    except TokenError as exc:
        raise ApiError("REFRESH_INVALID", 401) from exc
    claim_device = old.get("device_id")
    if claim_device and device_id and str(claim_device) != str(device_id):
        raise ApiError("REFRESH_INVALID", 401, "El refresh pertenece a otro celular.")
    user = User.objects.filter(pk=old.get("user_id")).first()
    if user is None:
        raise ApiError("REFRESH_INVALID", 401)
    ensure_device_not_revoked(device_id or claim_device)
    ensure_app_access(user)
    with transaction.atomic():
        try:
            old.blacklist()
        except AttributeError:  # sin la app token_blacklist (no ocurre con la configuración del proyecto)
            pass
        Device.objects.filter(pk=device_id or claim_device).update(last_seen_at=timezone.now())
        tokens = _issue_tokens(user, device_id or claim_device)
    return tokens


def app_logout(raw_refresh):
    """POST /auth/logout: pone el refresh del dispositivo en la lista negra. Siempre 204 (no revela nada)."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken

    try:
        RefreshToken(raw_refresh).blacklist()
    except (TokenError, AttributeError):
        pass


def app_change_password(user, current, new):
    if not user.check_password(current):
        raise ApiError("INVALID_CREDENTIALS", 401)
    try:
        validate_password(new, user)
    except ValidationError as exc:
        raise ApiError("PASSWORD_POLICY", 400,
                       field_errors=[{"field": "newPassword", "message": " ".join(exc.messages)}]) from exc
    with transaction.atomic():
        user.set_password(new)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        audit.record("user", user.pk, "CONTRASENA_CAMBIADA_APP", user)


def request_password_reset(email, remote_addr=""):
    """POST /auth/password-reset-requests: siempre 202. Se guarda un pedido por correo (sin duplicar pendientes) y se
    limita la cantidad por IP para que nadie llene la bandeja del administrador."""
    email = (email or "").strip().lower()
    if not email:
        return
    ip_key = f"api-reset-ip:{remote_addr}"
    n = cache.get(ip_key, 0)
    if n >= 10:
        log.warning("Pedidos de restablecimiento ignorados por exceso desde %s", remote_addr or "?")
        return
    cache.set(ip_key, n + 1, 3600)
    if PasswordResetRequest.objects.filter(email__iexact=email, status=PasswordResetRequest.Status.PENDIENTE).exists():
        return
    user = User.objects.filter(email__iexact=email).first()
    PasswordResetRequest.objects.create(email=email, user=user)
    log.info("Pedido de restablecimiento de contraseña para %s%s", email, "" if user else " (correo sin cuenta)")
