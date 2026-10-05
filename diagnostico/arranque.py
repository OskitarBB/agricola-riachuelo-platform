# diagnostico/arranque.py — Resumen de configuración al iniciar `runserver` o `worker_ia`: qué base de datos, qué
# Cloudinary (real o simulado), qué cliente de WhatsApp y qué detector se usan, y en qué dirección escucha la API.
import logging
import os
import socket
import sys

from django.conf import settings

log = logging.getLogger("riachuelo.arranque")
_anunciado = False


def ip_local():
    """IP de esta computadora en la red local (para EXPO_PUBLIC_API_URL de la app). No envía paquetes."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def resumen():
    from evidencias import nube

    db = settings.DATABASES["default"]
    motor = "PostgreSQL" if db["ENGINE"].endswith("postgresql") else "SQLite"
    destino = f"{db.get('HOST') or 'local'}/{db.get('NAME')}" if motor == "PostgreSQL" else str(db.get("NAME"))
    nube_txt = {"real": "Cloudinary (URLs firmadas)", "simulado": "Cloudinary SIMULADO en esta laptop (solo dev)",
                "sin_configurar": "SIN CONFIGURAR (falta CLOUDINARY_URL)"}[nube.modo()]
    wa = "consola (no envía)" if settings.WHATSAPP_CLIENT.endswith("ConsoleClient") else "WhatsApp Cloud API"
    return [
        f"Entorno: {settings.APP_ENV} · DEBUG {'sí' if settings.DEBUG else 'no'} · Base de datos: {motor} ({destino})",
        f"Fotos: {nube_txt} · WhatsApp: {wa} · Detector IA: {settings.IA_DETECTOR}",
    ]


def anunciar_arranque():
    global _anunciado
    if _anunciado or "test" in sys.argv:
        return
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando == "runserver" and os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
        return  # el proceso que vigila los archivos no atiende peticiones: se anuncia en el hijo
    if comando not in ("runserver", "worker_ia"):
        return
    _anunciado = True
    puerto = "8000"
    for arg in sys.argv[2:]:
        if not arg.startswith("-"):
            puerto = arg.rsplit(":", 1)[-1]
    lineas = ["", "  ╭──────────────────────────────────────────────────────────╮",
              "  │  Agrícola Riachuelo · Plataforma de monitoreo de la vid  │",
              "  ╰──────────────────────────────────────────────────────────╯"]
    lineas += ["  " + x for x in resumen()]
    if comando == "runserver":
        escucha_todo = any(a.startswith("0.0.0.0") for a in sys.argv[2:])
        lineas.append(f"  Web: http://127.0.0.1:{puerto}/   ·   Gestión: http://127.0.0.1:{puerto}/gestion/")
        if escucha_todo:
            lineas.append(f"  App móvil: EXPO_PUBLIC_API_URL=http://{ip_local()}:{puerto}  (misma red Wi-Fi)")
        else:
            lineas.append(f"  App móvil: inicia con «python manage.py runserver 0.0.0.0:{puerto}» para que el "
                          "celular llegue a la API")
    lineas.append("  Revisión completa de la configuración: python manage.py diagnostico")
    log.info("\n".join(lineas))
    if getattr(settings, "SECRET_KEY_EFIMERA", False):
        log.warning("DJANGO_SECRET_KEY no está en .env: se usa una clave temporal (las sesiones se pierden al "
                    "reiniciar). Ejecuta scripts/iniciar.ps1 o copia .env.example a .env.")
