"""Role checks for the web layer.

Keep these names close to routes so templates can ask simple questions without
duplicating role strings.
"""
from cuentas.models import Role


PERMISSIONS = {
    "caso.ver": [Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR, Role.ADMINISTRADOR],
    "caso.decidir": [Role.ESPECIALISTA_FITOSANITARIO, Role.ADMINISTRADOR],
    "mapa.ver": [Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR, Role.ADMINISTRADOR],
    "sesiones.ver": [Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR, Role.ADMINISTRADOR],
    "reportes.exportar": [Role.SUPERVISOR, Role.ADMINISTRADOR],
    "usuarios.gestionar": [Role.ADMINISTRADOR],
    "ia.reencolar": [Role.ADMINISTRADOR],
}


def can(user, permission):
    if not user or not user.is_authenticated:
        return False
    roles = PERMISSIONS.get(permission, [])
    return user.is_superuser or user.has_role(*roles)


def permission_context(user):
    return {key.replace(".", "_"): can(user, key) for key in PERMISSIONS}
