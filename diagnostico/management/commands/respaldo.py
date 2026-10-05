# diagnostico/management/commands/respaldo.py — Copia de seguridad de la base de datos con pg_dump.
#
#   python manage.py respaldo                    # respaldos/riachuelo-<entorno>-AAAAMMDD-HHMM.dump (formato custom)
#   python manage.py respaldo --carpeta D:\copias
#
# El plan Free de Supabase no incluye backups (Maestro App Móvil §28.12): hasta pasar a Pro, conviene un respaldo
# semanal. Necesita las herramientas cliente de PostgreSQL (pg_dump) de la MISMA versión mayor que el servidor o
# superior; en Windows vienen con el instalador de PostgreSQL («Command Line Tools»).
# Restaurar en una base vacía:  pg_restore --no-owner --no-privileges -d "<DATABASE_URL de destino>" archivo.dump
# y luego `python manage.py migrate` (vuelve a aplicar RLS y REVOKE). La contraseña no se escribe en el archivo.
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Respalda la base de datos PostgreSQL (Supabase) con pg_dump en formato custom."

    def add_arguments(self, parser):
        parser.add_argument("--carpeta", default=str(Path(settings.BASE_DIR) / "respaldos"))

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            raise CommandError("La base actual es SQLite: basta con copiar el archivo db.sqlite3.")
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise CommandError("No se encontró pg_dump. Instala las «Command Line Tools» de PostgreSQL "
                               "(https://www.postgresql.org/download/) y vuelve a abrir la terminal.")
        db = settings.DATABASES["default"]
        carpeta = Path(opts["carpeta"])
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"riachuelo-{settings.APP_ENV}-{datetime.now():%Y%m%d-%H%M}.dump"
        entorno = dict(os.environ, PGPASSWORD=str(db.get("PASSWORD") or ""),
                       PGSSLMODE=str((db.get("OPTIONS") or {}).get("sslmode", "prefer")))
        comando = [pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--schema=public",
                   "-h", str(db.get("HOST") or "localhost"), "-p", str(db.get("PORT") or 5432),
                   "-U", str(db.get("USER") or "postgres"), "-d", str(db["NAME"]), "-f", str(destino)]
        self.stdout.write(f"Respaldando {db.get('HOST')}/{db['NAME']} → {destino} …")
        r = subprocess.run(comando, env=entorno, capture_output=True, text=True)
        if r.returncode != 0:
            destino.unlink(missing_ok=True)
            raise CommandError(f"pg_dump falló: {r.stderr.strip()[:400]}")
        self.stdout.write(self.style.SUCCESS(f"✔ Respaldo listo: {destino} ({destino.stat().st_size / 1e6:.1f} MB)"))
        self.stdout.write("   Guárdalo fuera de esta computadora (por ejemplo, en el Drive del equipo).")
