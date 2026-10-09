# revision/tests/test_alertas_ia.py — QUÉ HACE: v1.3 (ADR-W-007) prueba la confirmación automática de la IA (umbral por
# modelo, aviso sin decisión humana), la decisión «Posible plaga» y la revisión posterior del especialista.
from django.test import TestCase

from auditoria.models import AuditEvent
from ia.models import DetectionReview
from notificaciones import services as notif
from notificaciones.models import Notification, NotificationStatus
from notificaciones.whatsapp import ConsoleClient, render_preview
from revision import services as rv
from revision.models import Case, CaseNotificationStatus, ReviewStatus
from web.tests import factories as F

ALTA = dict(F.BOX, confidence=0.91)
BAJA = dict(F.BOX, confidence=0.40)


class ConfirmacionAutomatica(TestCase):
    def setUp(self):
        self.w = F.world()
        self.w.model.auto_confirm_threshold = 0.75
        self.w.model.save(update_fields=["auto_confirm_threshold"])
        F.recipient("Jefe de fundo")

    def test_alta_confianza_confirma_y_avisa_sin_especialista(self):
        _, task, case = F.analyzed(self.w, boxes=(ALTA, BAJA))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)
        self.assertIsNone(case.decided_by)
        self.assertEqual(case.notification_status, CaseNotificationStatus.PENDIENTE_ENVIO)
        aviso = Notification.objects.get(case=case)
        self.assertIsNone(aviso.review)
        self.assertEqual(aviso.kind, Notification.Kind.CASO_CONFIRMADO_IA)
        self.assertEqual(sorted(task.detections.values_list("review_status", flat=True)),
                         sorted([DetectionReview.CONFIRMADO_POR_IA, DetectionReview.PENDIENTE_REVISION]))
        self.assertTrue(AuditEvent.objects.filter(action="CASO_CONFIRMADO_POR_IA").exists())

    def test_confianza_media_espera_al_especialista(self):
        _, _, case = F.analyzed(self.w, boxes=(BAJA,))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.PENDIENTE_REVISION)
        self.assertFalse(Notification.objects.exists())

    def test_sin_umbral_nunca_confirma_sola(self):
        self.w.model.auto_confirm_threshold = None
        self.w.model.save(update_fields=["auto_confirm_threshold"])
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.PENDIENTE_REVISION)

    def test_mensaje_de_whatsapp_de_la_ia(self):
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        payload = notif.build_whatsapp_payload(Notification.objects.get(case=case))
        self.assertIn("detectada por la IA", render_preview(payload))
        self.assertTrue(ConsoleClient().send(payload).startswith("console-"))

    def test_especialista_confirma_sin_duplicar_avisos(self):
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        n = Notification.objects.get(case=case)
        notif.mark_sent(n, "wamid.1")
        rv.decide_case(case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias visibles")
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA)
        self.assertEqual(Notification.objects.filter(case=case).count(), 1)

    def test_especialista_descarta_anula_avisos_pendientes(self):
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        rv.decide_case(case.pk, self.w.esp, ReviewStatus.DESCARTADO, "Residuo de azufre")
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.DESCARTADO)
        self.assertEqual(Notification.objects.get(case=case).status, NotificationStatus.NO_APLICA)


class PosiblePlaga(TestCase):
    def setUp(self):
        self.w = F.world()
        F.recipient("Jefe de fundo")
        _, self.task, self.case = F.analyzed(self.w, boxes=(BAJA,))

    def test_posible_plaga_sin_aviso_ni_observacion_obligatoria(self):
        rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.POSIBLE_PLAGA, "")
        case = Case.objects.get(pk=self.case.pk)
        self.assertEqual(case.status, ReviewStatus.POSIBLE_PLAGA)
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(self.task.detections.exclude(review_status=DetectionReview.POSIBLE_PLAGA).exists())

    def test_corregir_de_posible_a_confirmado_avisa(self):
        review = rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.POSIBLE_PLAGA, "")
        rv.correct_decision(self.case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Confirmado en campo",
                            "El encargado vio la colonia", review.pk)
        self.assertEqual(Notification.objects.filter(case=self.case).count(), 1)
