# diagnostico/management/commands/comprobar_bd.py — Prueba la conexión a la base de datos ANTES de migrar y, si
# falla, dice en una línea qué está mal y cómo arreglarlo (sin mostrar la contraseña). Lo usa iniciar.bat.
#
#   python manage.py comprobar_bd
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from diagnostico import bd


class Command(BaseCommand):
    help = "Prueba la conexión a la base de datos y explica el error en lenguaje claro."

    def handle(self, *args, **opts):
        if connection.vendor == "sqlite":
            self.stdout.write(f"  ✔ Base de datos: SQLite ({settings.DATABASES['default']['NAME']})")
            return
        url = bd.url_cruda()
        self.stdout.write(f"  Base de datos: {bd.resumen_seguro(url)}")
        problemas = bd.problemas_de_url(url)
        for texto, ayuda in problemas:
            self.stdout.write(self.style.ERROR(f"  ✖ {texto}"))
            self.stdout.write(f"      → {ayuda}")
        t0 = time.perf_counter()
        try:
            connection.ensure_connection()
            with connection.cursor() as cur:
                cur.execute("SELECT current_setting('server_version')")
                version = cur.fetchone()[0]
        except Exception as exc:  # noqa: BLE001 — se explica y se sale con código 1
            texto, ayuda = bd.explicar_error(exc)
            self.stdout.write(self.style.ERROR(f"  ✖ {texto}"))
            self.stdout.write(f"      → {ayuda}")
            sys.exit(1)
        ms = (time.perf_counter() - t0) * 1000
        self.stdout.write(self.style.SUCCESS(f"  ✔ Conectado a PostgreSQL {version} en {ms:.0f} ms"))
        if ms > 800:
            self.stdout.write("      ! Latencia alta: para el piloto conviene la región São Paulo (sa-east-1).")
