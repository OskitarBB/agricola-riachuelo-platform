# web/permissions.py — Matriz única de permisos de la web (sección 7.2). Las vistas, las plantillas y las pruebas
# leen ESTA tabla; los servicios vuelven a comprobar las reglas críticas (RN-W01) por su cuenta.
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, resolve_url
from django.utils.http import urlencode
from django_htmx.http import HttpResponseClientRedirect

from cuentas.models import Role

A, E, S = Role.ADMINISTRADOR, Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR

PERMISOS = {
    "dashboard.ver": {A, E, S},
    "bandeja.ver": {A, E, S},
    "caso.ver": {A, E, S},
    "caso.decidir": {E},
    "caso.corregir": {E},
    "caso.abrir_manual": {E},
    "mapa.ver": {A, E, S},
    "sesiones.ver": {A, E, S},
    "reportes.exportar": {A, E, S},
    "notificaciones.ver": {A, E, S},
    "ia.ver": {A, E},
    "ia.reencolar": {A},
    "usuarios.gestionar": {A},
    "dispositivos.gestionar": {A},
    "destinatarios.gestionar": {A},
    "catalogos.gestionar": {A, S},  # v1.2 (ADR-W-006): lotes, hileras, segmentos y marcadores
    "auditoria.ver": {A},
}


def can(user, perm):
    return bool(user and user.is_authenticated and user.can_use_web and user.has_role(*PERMISOS[perm]))


def web_view(perm):
    """Decorador obligatorio de toda vista de la web (W-07)."""
    if perm not in PERMISOS:
        raise KeyError(perm)

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                if request.htmx:  # sesión vencida durante un refresco HTMX: recargar la página completa en el login
                    nxt = request.htmx.current_url_abs_path or "/"
                    return HttpResponseClientRedirect(f"{resolve_url(settings.LOGIN_URL)}?{urlencode({'next': nxt})}")
                return redirect_to_login(request.get_full_path())
            if user.must_change_password:
                return redirect("web:cambiar_contrasena")
            if not can(user, perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapper.web_permission = perm
        return wrapper

    return decorator
