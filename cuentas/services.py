"""Account service functions.

Web and future API endpoints should use these helpers so role/status changes
are audited and password rules stay centralized.
"""
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.crypto import get_random_string

from auditoria.services import log_event
from cuentas.models import AccountStatus, Role, User, UserRole


@transaction.atomic
def approve_user(user_id, approver, roles):
    user = User.objects.select_for_update().get(pk=user_id)
    user.activate(approver)
    user.save(update_fields=["status", "approved_by", "approved_at"])
    set_roles(user, roles, approver)
    log_event(approver, "USUARIO_APROBADO", target=user)
    return user


@transaction.atomic
def set_roles(user, roles, actor):
    clean_roles = [role for role in roles if role in Role.values]
    UserRole.objects.filter(user=user).exclude(role__in=clean_roles).delete()
    for role in clean_roles:
        UserRole.objects.get_or_create(user=user, role=role)
    log_event(actor, "ROLES_CAMBIADOS", target=user, payload={"roles": clean_roles})
    return user


@transaction.atomic
def block_user(user_id, actor):
    user = User.objects.select_for_update().get(pk=user_id)
    user.status = AccountStatus.BLOQUEADO
    user.is_active = False
    user.save(update_fields=["status", "is_active"])
    log_event(actor, "USUARIO_BLOQUEADO", target=user)
    return user


@transaction.atomic
def issue_temporary_password(user_id, actor):
    user = User.objects.select_for_update().get(pk=user_id)
    password = f"Ria-{get_random_string(10)}"
    validate_password(password, user)
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    log_event(actor, "PASSWORD_TEMPORAL", target=user)
    return password
