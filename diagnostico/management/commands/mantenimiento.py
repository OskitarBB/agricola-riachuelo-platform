# diagnostico/management/commands/mantenimiento.py — Limpieza periódica (semanal) de datos técnicos que crecen solos.
#
#   python manage.py mantenimiento
#
# Borra solo datos técnicos vencidos: sesiones web expiradas (django_session), refresh tokens vencidos de la app
# (token_blacklist) y entradas viejas de la caché (web_cache). Nunca toca evidencia, casos, decisiones ni auditoría
# (la retención de evidencia la decide el equipo, Q-05). Al final informa el tamaño de las tablas más grandes.
# En el plan Free de Supabase, ejecutarlo cada semana también evita que el proyecto se pause por inactividad.
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Limpia sesiones, tokens vencidos y caché vieja; informa el tamaño de la base de datos."

    def handle(self, *args, **opts):
        call_command("clearsessions")
        self.stdout.write("✔ Sesiones web vencidas eliminadas")
        call_command("flushexpiredtokens")
        self.stdout.write("✔ Tokens de la app vencidos eliminados")
        with connection.cursor() as cur:
            cur.execute("DELETE FROM web_cache WHERE expires < %s", [timezone.now()])
            self.stdout.write(f"✔ Caché: {cur.rowcount} entradas vencidas eliminadas")
            if connection.vendor == "postgresql":
                cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                self.stdout.write(f"Tamaño de la base: {cur.fetchone()[0]}")
                cur.execute("SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_statio_user_tables "
                            "ORDER BY pg_total_relation_size(relid) DESC LIMIT 6")
                for nombre, tam in cur.fetchall():
                    self.stdout.write(f"   {nombre:28} {tam}")
