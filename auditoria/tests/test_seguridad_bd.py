from unittest import skipUnless

from django.db import IntegrityError, connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from auditoria import services as audit
from auditoria.models import AuditEvent


@skipUnless(connection.vendor == "postgresql", "Solo PostgreSQL (Supabase)")
class SeguridadSupabase(TestCase):
    """Tras `migrate` (la BD de pruebas también se crea con migrate): RLS en todas las tablas y sin privilegios
    para los roles de la Data API. En el PostgreSQL local de pruebas se crean antes `anon` y `authenticated`."""

    def test_rls_en_todas_las_tablas_de_public(self):
        with connection.cursor() as cur:
            cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity")
            self.assertEqual(cur.fetchall(), [])

    def test_roles_de_la_data_api_sin_acceso(self):
        with connection.cursor() as cur:
            cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
            roles = [r for (r,) in cur.fetchall()]
            if not roles:
                self.skipTest("El clúster no tiene los roles de Supabase")
            for role in roles:
                for table in ("users", "review_cases", "captures", "notifications", "audit_events"):
                    cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", [role, f"public.{table}"])
                    self.assertFalse(cur.fetchone()[0], f"{role} puede leer {table}")


# ---------------------------------------------------------------- v1.0+ (docs/ARQUITECTURA_DATOS.md)

@skipUnless(connection.vendor == "postgresql", "El trigger solo existe en PostgreSQL (Supabase)")
class AuditoriaSoloInsercion(TestCase):
    def setUp(self):
        from web.tests import factories as F

        self.usuario = F.user("audita@x.pe")
        self.evento = audit.record("user", self.usuario.pk, "PRUEBA", self.usuario, None, {"a": 1})

    def test_no_se_edita_ni_se_borra(self):
        for operacion in (lambda q: q.update(action="OTRA"), lambda q: q.delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                operacion(AuditEvent.objects.filter(pk=self.evento.pk))
        self.assertEqual(AuditEvent.objects.get(pk=self.evento.pk).action, "PRUEBA")

    def test_eliminar_la_cuenta_conserva_el_evento(self):
        AuditEvent.objects.filter(pk=self.evento.pk).update(user=None)  # lo que hace on_delete=SET_NULL
        self.assertIsNone(AuditEvent.objects.get(pk=self.evento.pk).user_id)


class RestriccionesCheck(TestCase):
    """Estados y coordenadas imposibles se rechazan en la base de datos, no solo en formularios (cap. X §10.7)."""

    def test_estado_inexistente_y_coordenadas_imposibles(self):
        from web.tests import factories as F

        w = F.world()
        u = F.user("estado@x.pe")
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(u).objects.filter(pk=u.pk).update(status="INVENTADO")
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(w.marker).objects.filter(pk=w.marker.pk).update(lat=123.0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(w.session).objects.filter(pk=w.session.pk).update(status="SYNCED")  # SYNCED es solo local en la app
