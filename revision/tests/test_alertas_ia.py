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

    def test_una_sola_caja_alta_no_basta(self):
        # 21/10: en campo una sola caja de 0,72 sobre un tallo se confirmó sola. Con el mínimo (2) espera.
        self.w.model.auto_confirm_min_boxes = 2
        self.w.model.save(update_fields=["auto_confirm_min_boxes"])
        _, _, case = F.analyzed(self.w, boxes=(ALTA, BAJA))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.PENDIENTE_REVISION)
        self.assertFalse(Notification.objects.exists())
        self.w.model.auto_confirm_min_boxes = 1  # configurable por modelo
        self.w.model.save(update_fields=["auto_confirm_min_boxes"])
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)

    def test_varias_cajas_medianas_confirman(self):
        # 21/10: 5 cajas de 0,46–0,63 sobre colonias. Con la regla «3 cajas ≥ 0,50» la IA confirma sola.
        self.w.model.auto_confirm_min_boxes = 2
        self.w.model.auto_confirm_many_boxes, self.w.model.auto_confirm_many_threshold = 3, 0.50
        self.w.model.save()
        cajas = tuple(dict(F.BOX, confidence=c) for c in (0.63, 0.57, 0.54, 0.48, 0.46))
        _, task, case = F.analyzed(self.w, boxes=cajas)
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)
        self.assertEqual(task.detections.filter(review_status=DetectionReview.CONFIRMADO_POR_IA).count(), 3)
        ev = AuditEvent.objects.filter(action="CASO_CONFIRMADO_POR_IA").latest("pk")
        self.assertEqual((ev.after["rule"], ev.after["boxThreshold"]), ("medianas", 0.5))
        # Solo 2 cajas medianas: espera al especialista.
        _, _, case2 = F.analyzed(self.w, boxes=tuple(dict(F.BOX, confidence=c) for c in (0.63, 0.57, 0.46)))
        case2.refresh_from_db()
        self.assertEqual(case2.status, ReviewStatus.PENDIENTE_REVISION)

    def test_confirmado_con_una_caja_vuelve_a_revision_con_el_comando(self):
        # 21/10: casos confirmados con la regla vieja (una sola caja) se corrigen con --revisar-confirmados.
        from io import StringIO

        from django.core.management import call_command

        _, task, case = F.analyzed(self.w, boxes=(ALTA,))  # min 1 (regla vieja): se confirma sola
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)
        out = StringIO()
        call_command("aplicar_triage", "--min-cajas", "2", "--revisar-confirmados", "--simular", stdout=out)
        self.assertIn("1 caso(s) «Confirmado por IA» vuelven", out.getvalue())
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)  # simular no cambia nada
        call_command("aplicar_triage", "--min-cajas", "2", "--revisar-confirmados", stdout=StringIO())
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.PENDIENTE_REVISION)
        self.assertIsNone(case.decided_at)
        self.assertFalse(task.detections.filter(review_status=DetectionReview.CONFIRMADO_POR_IA).exists())
        self.assertEqual(Notification.objects.get(case=case).status, NotificationStatus.NO_APLICA)
        self.assertTrue(AuditEvent.objects.filter(action="CASO_DEVUELTO_A_REVISION").exists())

    def test_una_sola_caja_no_abre_caso(self):
        # 21/10: una caja de 0,63 sobre un reflejo blanco en la uva. Con «mínimo de cajas para abrir caso» = 2 la IA
        # descarta la foto (queda en «Descartadas por la IA»); con 2 cajas sí abre caso.
        from ia.models import AiStatus

        self.w.model.review_threshold, self.w.model.review_min_boxes = 0.40, 2
        self.w.model.save()
        _, task, case = F.analyzed(self.w, boxes=(dict(F.BOX, confidence=0.63),))
        task.refresh_from_db()
        self.assertIsNone(case)
        self.assertEqual(task.status, AiStatus.DESCARTADO_POR_IA)
        _, _, case = F.analyzed(self.w, boxes=(dict(F.BOX, confidence=0.63), dict(F.BOX, confidence=0.45)))
        self.assertIsNotNone(case)

    def test_comando_descarta_casos_pendientes_de_una_caja(self):
        from io import StringIO

        from django.core.management import call_command

        self.w.model.auto_confirm_threshold = None
        self.w.model.save()
        _, task, case = F.analyzed(self.w, boxes=(dict(F.BOX, confidence=0.63),))  # min 1: abre caso
        self.assertEqual(Case.objects.filter(pk=case.pk).count(), 1)
        call_command("aplicar_triage", "--revision", "0.40", "--min-cajas-caso", "2", stdout=StringIO())
        self.assertFalse(Case.objects.filter(pk=case.pk).exists())
        task.refresh_from_db()
        self.assertEqual(task.status, "DESCARTADO_POR_IA")

    def test_alta_confianza_confirma_y_avisa_sin_especialista(self):
        _, task, case = F.analyzed(self.w, boxes=(ALTA, dict(ALTA, confidence=0.88), BAJA))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)
        self.assertIsNone(case.decided_by)
        self.assertEqual(case.notification_status, CaseNotificationStatus.PENDIENTE_ENVIO)
        aviso = Notification.objects.get(case=case)
        self.assertIsNone(aviso.review)
        self.assertEqual(aviso.kind, Notification.Kind.CASO_CONFIRMADO_IA)
        self.assertEqual(sorted(task.detections.values_list("review_status", flat=True)),
                         sorted([DetectionReview.CONFIRMADO_POR_IA, DetectionReview.CONFIRMADO_POR_IA,
                                 DetectionReview.PENDIENTE_REVISION]))
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
