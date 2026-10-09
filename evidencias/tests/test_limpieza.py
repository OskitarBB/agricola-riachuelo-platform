# evidencias/tests/test_limpieza.py — QUÉ HACE: v1.3.1 (ADR-W-008) prueba la limpieza de fotos: borrar una sesión
# completa (con casos, decisiones y avisos), borrar las descartadas por la IA antiguas sin tocar fotos con caso, el
# registro para los celulares (GET /mobile/deleted-captures), el bloqueo 410 al resincronizar y los permisos web.
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from api.tests.test_api import API, Base
from auditoria.models import AuditEvent
from evidencias import limpieza
from evidencias.models import Capture, DeletedCapture, DeletedSession
from ia.models import AiTask
from monitoreo.models import MonitoringSession
from notificaciones.models import Notification
from revision import services as rv
from revision.models import Case, ReviewStatus
from web.tests import factories as F

BAJA = dict(F.BOX, confidence=0.30)


def nube_ok(public_ids):
    return set(public_ids), {}


def sin_nube(test):
    """Las pruebas nunca llaman a Cloudinary: se reemplaza el borrado remoto por uno que siempre funciona."""
    p = mock.patch("evidencias.nube.delete_public_ids", side_effect=nube_ok)
    test.nube = p.start()
    test.addCleanup(p.stop)


class EliminarSesion(TestCase):
    def setUp(self):
        sin_nube(self)
        self.w = F.world()
        F.recipient("Jefe")
        _, _, self.caso = F.analyzed(self.w)
        rv.decide_case(self.caso.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias")
        F.analyzed(self.w, boxes=())
        self.assertEqual(Notification.objects.count(), 1)

    def test_pide_la_palabra_de_confirmacion(self):
        with self.assertRaises(limpieza.LimpiezaInvalida):
            limpieza.eliminar_sesion(self.w.session.pk, self.w.admin, "si")
        self.assertTrue(MonitoringSession.objects.filter(pk=self.w.session.pk).exists())

    def test_borra_todo_y_deja_registro(self):
        sid = self.w.session.pk
        r = limpieza.eliminar_sesion(sid, self.w.admin, "eliminar")
        self.assertEqual((r["fotos"], r["casos"], r["decididos"]), (2, 1, 1))
        self.assertFalse(MonitoringSession.objects.filter(pk=sid).exists())
        self.assertFalse(Capture.objects.exists())
        self.assertFalse(Case.objects.exists())
        self.assertFalse(AiTask.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(DeletedCapture.objects.count(), 2)
        self.assertTrue(DeletedSession.objects.filter(pk=sid).exists())
        self.assertFalse(DeletedCapture.objects.filter(cloud_deleted_at__isnull=True).exists())  # nube simulada
        self.assertTrue(AuditEvent.objects.filter(action="SESION_ELIMINADA", user=self.w.admin).exists())

    def test_si_la_nube_falla_queda_pendiente_para_el_worker(self):
        self.nube.side_effect = lambda ids: (set(), {p: "sin red" for p in ids})
        limpieza.eliminar_sesion(self.w.session.pk, self.w.admin, "ELIMINAR")
        self.assertEqual(limpieza.pendientes_en_nube(), 2)
        self.nube.side_effect = nube_ok
        self.assertEqual(limpieza.borrar_en_nube(), (2, 0))
        self.assertEqual(limpieza.pendientes_en_nube(), 0)


class EliminarDescartadas(TestCase):
    def setUp(self):
        sin_nube(self)
        self.w = F.world()
        self.w.model.review_threshold = 0.5
        self.w.model.save(update_fields=["review_threshold"])
        self.descartada, _, _ = F.analyzed(self.w, boxes=(BAJA,))
        self.sin_nada, _, _ = F.analyzed(self.w, boxes=())
        self.con_caso, _, _ = F.analyzed(self.w)
        self.reciente, _, _ = F.analyzed(self.w, boxes=())
        viejo = timezone.now() - timedelta(days=40)
        Capture.objects.exclude(pk=self.reciente.pk).update(captured_at=viejo)

    def test_solo_borra_antiguas_sin_caso(self):
        self.assertEqual(limpieza.descartadas_qs(30).count(), 2)
        n = limpieza.eliminar_descartadas(30, self.w.admin, "ELIMINAR")
        self.assertEqual(n, 2)
        quedan = set(Capture.objects.values_list("pk", flat=True))
        self.assertEqual(quedan, {self.con_caso.pk, self.reciente.pk})
        self.assertTrue(MonitoringSession.objects.filter(pk=self.w.session.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action="FOTOS_DESCARTADAS_ELIMINADAS").exists())


class AppYBorrados(Base):
    def setUp(self):
        super().setUp()
        sin_nube(self)
        self.foto, _, _ = F.analyzed(self.w, boxes=())
        self.sid = self.w.session.pk
        limpieza.eliminar_sesion(self.sid, self.w.admin, "ELIMINAR")

    def test_la_app_recibe_las_fotos_borradas_con_cursor(self):
        self.autenticar("op@x.pe")
        r = self.c.get(f"{API}/mobile/deleted-captures")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["captures"], [{"captureId": str(self.foto.pk), "sessionId": str(self.sid)}])
        self.assertEqual(d["sessionIds"], [str(self.sid)])
        self.assertFalse(d["hasMore"])
        r2 = self.c.get(f"{API}/mobile/deleted-captures", {"since": d["cursor"]})
        self.assertEqual((r2.json()["captures"], r2.json()["sessionIds"]), ([], []))

    def test_no_se_puede_resincronizar_lo_borrado(self):
        self.autenticar("op@x.pe")
        r = self.c.post(f"{API}/captures/{self.foto.pk}/upload-ticket", {
            "captureId": str(self.foto.pk), "sessionId": str(self.sid), "passId": str(uuid.uuid4()),
            "sequenceId": str(uuid.uuid4()), "md5": "0" * 32, "sizeBytes": 1000, "mimeType": "image/jpeg"}, format="json")
        self.assertError(r, 410, "SESSION_DELETED")

    def test_since_invalido(self):
        self.autenticar("op@x.pe")
        self.assertError(self.c.get(f"{API}/mobile/deleted-captures", {"since": "ayer"}), 400, "VALIDATION_ERROR")


class PantallasDeLimpieza(TestCase):
    def setUp(self):
        sin_nube(self)
        self.w = F.world()
        F.analyzed(self.w, boxes=())

    def test_solo_el_administrador(self):
        self.client.force_login(self.w.esp)
        self.assertEqual(self.client.get(reverse("web:limpieza")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:sesion_eliminar", args=[self.w.session.pk])).status_code, 403)

    def test_eliminar_sesion_desde_la_web(self):
        self.client.force_login(self.w.admin)
        url = reverse("web:sesion_eliminar", args=[self.w.session.pk])
        self.assertContains(self.client.get(url), "Eliminar para siempre")
        r = self.client.post(url, {"confirmacion": "no"})
        self.assertContains(r, "Para confirmar")
        r = self.client.post(url, {"confirmacion": "ELIMINAR"})
        self.assertRedirects(r, reverse("web:sesiones"))
        self.assertFalse(MonitoringSession.objects.exists())

    def test_pagina_de_limpieza(self):
        self.client.force_login(self.w.admin)
        r = self.client.get(reverse("web:limpieza"), {"dias": 1})
        self.assertContains(r, "Limpieza de fotos")
        self.assertContains(self.client.get(reverse("web:sesion", args=[self.w.session.pk])), "Eliminar sesión")
