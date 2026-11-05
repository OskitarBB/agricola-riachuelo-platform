# evidencias/tests/test_papelera.py — QUÉ HACE: v1.5 (ADR-W-012) prueba la papelera de fotos: la foto (y su caso) salen
# de todas las listas, no se analizan ni se deciden, se restauran tal cual, se borran para siempre (a mano, al vaciar
# o solas a los PAPELERA_DIAS días) y solo el administrador puede hacerlo.
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auditoria.models import AuditEvent
from evidencias import papelera
from evidencias.models import Capture, DeletedCapture, DeletionReason
from ia import services as ia
from notificaciones.models import Notification, NotificationStatus
from revision import services as rv
from revision.models import Case, ReviewStatus
from web import queries
from web.tests import factories as F


def nube_ok(public_ids):
    return set(public_ids), {}


class Base(TestCase):
    def setUp(self):
        p = mock.patch("evidencias.nube.delete_public_ids", side_effect=nube_ok)
        p.start()
        self.addCleanup(p.stop)
        self.w = F.world()
        self.cap, _, self.case = F.analyzed(self.w)


class Servicio(Base):
    def test_enviar_oculta_la_foto_y_su_caso(self):
        papelera.enviar(self.cap.pk, self.w.admin, "  foto  borrosa ")
        self.cap.refresh_from_db()
        self.assertIsNotNone(self.cap.trashed_at)
        self.assertEqual(self.cap.trash_reason, "foto borrosa")
        self.assertFalse(queries.bandeja({}).filter(pk=self.case.pk).exists())
        self.assertEqual(queries.dashboard(timezone.localdate() - timedelta(days=1), timezone.localdate())["capturas"], 0)
        self.assertIsNone(queries.next_pending_case_id(self.case))
        self.assertTrue(AuditEvent.objects.filter(action="FOTO_A_PAPELERA", entity_id=str(self.cap.pk)).exists())

    def test_anula_los_avisos_pendientes(self):
        F.recipient("Jefe")
        rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias")
        papelera.enviar(self.cap.pk, self.w.admin)
        self.assertEqual(Notification.objects.get().status, NotificationStatus.NO_APLICA)

    def test_no_se_decide_ni_se_analiza(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        with self.assertRaises(ValidationError):
            rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.DESCARTADO, "")
        otra = F.capture(self.w)
        ia.enqueue_analysis(otra)
        papelera.enviar(otra.pk, self.w.admin)
        self.assertIsNone(ia.claim_next_task("w1"))

    def test_restaurar_deja_todo_como_estaba(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        papelera.restaurar(self.cap.pk, self.w.admin)
        self.assertTrue(queries.bandeja({}).filter(pk=self.case.pk).exists())
        with self.assertRaises(papelera.PapeleraInvalida):
            papelera.restaurar(self.cap.pk, self.w.admin)

    def test_eliminar_solo_borra_lo_que_esta_en_la_papelera(self):
        self.assertEqual(papelera.eliminar([self.cap.pk], self.w.admin), 0)  # no está en la papelera
        papelera.enviar(self.cap.pk, self.w.admin)
        self.assertEqual(papelera.eliminar([self.cap.pk], self.w.admin), 1)
        self.assertFalse(Capture.objects.filter(pk=self.cap.pk).exists())
        self.assertFalse(Case.objects.filter(pk=self.case.pk).exists())
        self.assertEqual(DeletedCapture.objects.get(pk=self.cap.pk).reason, DeletionReason.PAPELERA)

    @override_settings(PAPELERA_DIAS=30)
    def test_el_worker_borra_las_vencidas(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        self.assertEqual(papelera.vaciar_vencidas(), 0)
        Capture.objects.filter(pk=self.cap.pk).update(trashed_at=timezone.now() - timedelta(days=31))
        self.assertEqual(papelera.vaciar_vencidas(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="PAPELERA_VENCIDAS_ELIMINADAS").exists())

    def test_vaciar_pide_confirmacion(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        with self.assertRaises(papelera.PapeleraInvalida):
            papelera.vaciar(self.w.admin, "si")
        self.assertEqual(papelera.vaciar(self.w.admin, "eliminar"), 1)


class Pantallas(Base):
    def test_solo_el_administrador(self):
        self.client.force_login(self.w.esp)
        self.assertEqual(self.client.get(reverse("web:papelera")).status_code, 403)
        self.assertEqual(self.client.post(reverse("web:captura_papelera", args=[self.cap.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("web:captura", args=[self.cap.pk])), "Eliminar esta foto")

    def test_boton_eliminar_y_papelera(self):
        self.client.force_login(self.w.admin)
        self.assertContains(self.client.get(reverse("web:captura", args=[self.cap.pk])), "Eliminar esta foto")
        self.assertContains(self.client.get(reverse("web:caso", args=[self.case.pk])), "Eliminar esta foto")
        r = self.client.post(reverse("web:captura_papelera", args=[self.cap.pk]), {"volver": "https://otro.sitio/x"})
        self.assertRedirects(r, reverse("web:sesion", args=[self.w.session.pk]))  # nunca a otro sitio
        r = self.client.get(reverse("web:papelera"))
        self.assertContains(r, "Restaurar")
        self.assertContains(r, "Se borra el")
        self.assertContains(self.client.get(reverse("web:captura", args=[self.cap.pk])), "está en la papelera")
        self.assertNotContains(self.client.get(reverse("web:sesion", args=[self.w.session.pk])),
                               reverse("web:captura", args=[self.cap.pk]) + '"')

    def test_los_demas_no_ven_la_foto_de_la_papelera(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        self.client.force_login(self.w.esp)
        self.assertEqual(self.client.get(reverse("web:captura", args=[self.cap.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("web:caso", args=[self.case.pk])).status_code, 404)

    def test_restaurar_y_borrar_desde_la_web(self):
        papelera.enviar(self.cap.pk, self.w.admin)
        self.client.force_login(self.w.admin)
        self.client.post(reverse("web:papelera_restaurar", args=[self.cap.pk]))
        self.cap.refresh_from_db()
        self.assertIsNone(self.cap.trashed_at)
        papelera.enviar(self.cap.pk, self.w.admin)
        self.assertRedirects(self.client.post(reverse("web:papelera_eliminar", args=[self.cap.pk])),
                             reverse("web:papelera"))
        self.assertFalse(Capture.objects.filter(pk=self.cap.pk).exists())
