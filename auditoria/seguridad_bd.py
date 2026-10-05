# auditoria/seguridad_bd.py — Segunda barrera en Supabase (28.4 del maestro móvil): después de cada `migrate`
# activa RLS en todas las tablas del esquema public y quita privilegios a los roles de la Data API.
# Django se conecta con el dueño de las tablas, al que RLS no restringe (sin FORCE ROW LEVEL SECURITY).
#
# v1.0+ (docs/ARQUITECTURA_DATOS.md §6): además de tablas y secuencias, revoca funciones, el uso del esquema public y
# los privilegios por defecto de objetos futuros, para que una tabla nueva nunca nazca expuesta al Data API aunque
# el proyecto de Supabase sea anterior al cambio del 30/10/2026.
from django.db import connection

API_ROLES = ("anon", "authenticated")


def asegurar_bd(**kwargs):
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
        )
        for (table,) in cur.fetchall():
            cur.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        cur.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", [list(API_ROLES)])
        for (role,) in cur.fetchall():
            cur.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"')
            cur.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"')
            cur.execute(f'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM "{role}"')
            cur.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
            cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM "{role}"')
            cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM "{role}"')
            cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM "{role}"')
