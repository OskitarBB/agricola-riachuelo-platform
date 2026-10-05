# web/context_processors.py
from django.conf import settings

from evidencias import nube
from web.permissions import PERMISOS, can


def web_context(request):
    user = getattr(request, "user", None)
    puede = {perm.replace(".", "_"): can(user, perm) for perm in PERMISOS} if user is not None else {}
    # v1.0+: pantalla de carga animada solo en la primera página después de ingresar (la marca la pone `ingresar`).
    session = getattr(request, "session", None)
    mostrar_splash = bool(session is not None and session.get("mostrar_splash") and session.pop("mostrar_splash"))
    return {"puede": puede, "APP_ENV": settings.APP_ENV, "WEB": settings.WEB, "NUBE_SIMULADA": nube.es_simulado(),
            "mostrar_splash": mostrar_splash}
