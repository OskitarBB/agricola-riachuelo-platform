import threading

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from auditoria.models import AuditEvent
from evidencias.models import QualityStatus
from ia import services as ia
from ia.models import AiStatus, AiTask, DetectionReview
from notificaciones.models import Notification, NotificationStatus
from revision import services as rv
from revision.models import Case, CaseNotificationStatus, HumanReview, LocationSource, ReviewStatus
from web.tests import factories as F

C, D, I = (ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, ReviewStatus.DESCARTADO, ReviewStatus.EVIDENCIA_INSUFICIENTE)


class AperturaDeCasos(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_indicio_abre_caso_con_ubicacion_gps(self):
        cap, task, case = F.analyzed(self.w)
        self.assertEqual(task.status, AiStatus.INDICIO_SUGERIDO_POR_IA)
        self.assertEqual(case.origin, Case.Origin.IA)
        self.assertEqual((case.lot_id, case.row_id, case.segment_id, case.marker_id),
                         ("SWG1", "SWG1-H05", "SWG1-S1", "SWG1-M1"))
        self.assertEqual(case.location_source, LocationSource.GPS)
        self.assertEqual((case.detections_count, case.max_confidence), (1, 0.81))
        self.assertTrue(AuditEvent.objects.filter(action="CASO_ABIERTO", entity_id=str(case.pk)).exists())

    def test_sin_gps_usa_coordenadas_del_marcador(self):
        _, _, case = F.analyzed(self.w, gps=False)
        self.assertEqual(case.location_source, LocationSource.MARCADOR)
        self.assertEqual((case.lat, case.lon, case.gps_accuracy_m), (-14.06, -75.73, None))

    def test_sin_gps_ni_marcador_queda_sin_coordenadas(self):
        _, _, case = F.analyzed(self.w, gps=False, marker=False)
        self.assertEqual(case.location_source, LocationSource.NINGUNA)
        self.assertIsNone(case.lat)

    def test_repeticion_usa_el_contexto_de_la_repeticion(self):
        ctx = {"requestedAt": "2026-11-09T14:00:00Z", "segmentId": None, "markerId": None, "lat": -14.07,
               "lon": -75.74, "gpsAccuracyM": 6.0, "gpsTimestamp": "2026-11-09T14:00:00Z"}
        _, _, case = F.analyzed(self.w, retake_context=ctx)
        self.assertEqual((case.lat, case.lon, case.gps_accuracy_m, case.segment_id), (-14.07, -75.74, 6.0, None))

    def test_sin_cajas_no_abre_caso(self):
        _, task, case = F.analyzed(self.w, boxes=())
        self.assertEqual(task.status, AiStatus.SIN_INDICIOS_IA)
        self.assertIsNone(case)
        self.assertFalse(Case.objects.exists())

    def test_foto_rechazada_por_calidad_no_se_analiza(self):
        cap = F.capture(self.w, quality=QualityStatus.REPETIR_NITIDEZ)
        self.assertIsNone(ia.enqueue_analysis(cap))
        self.assertFalse(AiTask.objects.exists())

    def test_analisis_nuevo_no_cambia_una_decision(self):
        cap, task, case = F.analyzed(self.w)
        rv.decide_case(case.pk, self.w.esp, D, "Mancha de polvo")
        task.status = AiStatus.PENDIENTE_DE_ANALISIS
        task.save()
        task = ia.claim_next_task("t")
        ia.save_analysis_result(task, [F.BOX, F.BOX], 3000, 4000, 100, "v1")
        case.refresh_from_db()
        self.assertEqual(case.status, D)
        self.assertTrue(AuditEvent.objects.filter(action="ANALISIS_POSTERIOR_A_DECISION").exists())

    def test_caso_manual_sobre_foto_sin_indicios(self):
        cap, _, _ = F.analyzed(self.w, boxes=())
        with self.assertRaises(PermissionDenied):
            rv.open_manual_case(cap.pk, self.w.sup)
        case, created = rv.open_manual_case(cap.pk, self.w.esp)
        self.assertTrue(created)
        self.assertEqual((case.origin, case.detections_count), (Case.Origin.MANUAL, 0))
        again, created = rv.open_manual_case(cap.pk, self.w.esp)
        self.assertEqual((again.pk, created), (case.pk, False))

    def test_caso_manual_exige_analisis_terminado(self):
        cap = F.capture(self.w)
        ia.enqueue_analysis(cap)  # PENDIENTE_DE_ANALISIS
        with self.assertRaises(ValidationError):
            rv.open_manual_case(cap.pk, self.w.esp)


class Decisiones(TestCase):
    def setUp(self):
        self.w = F.world()
        self.cap, self.task, self.case = F.analyzed(self.w, boxes=(F.BOX, dict(F.BOX, confidence=0.4)))
        self.jefe = F.recipient("Jefe de fundo")
        self.sup_lote = F.recipient("Supervisor SWG1", phone="+51911111111", lots=[self.w.lot])
        F.recipient("Supervisor SWG2", phone="+51922222222", lots=[self.w.lot2])
        F.recipient("Sin consentimiento", phone="+51933333333", opt_in=False)
        F.recipient("Inactivo", phone="+51944444444", active=False)

    def test_solo_el_especialista_decide(self):
        for u in (self.w.sup, self.w.admin, self.w.op):
            with self.assertRaises(PermissionDenied):
                rv.decide_case(self.case.pk, u, C, "x")
        self.assertFalse(HumanReview.objects.exists())

    def test_confirmar_registra_todo_en_una_transaccion(self):
        dets = list(self.task.detections.order_by("-confidence"))
        review = rv.decide_case(self.case.pk, self.w.esp, C, "Colonias en racimo", "chanchito_blanco", [dets[1].pk])
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, C)
        self.assertEqual(self.case.decided_by, self.w.esp)
        self.assertEqual(review.rejected_detection_ids, [dets[1].pk])
        self.assertEqual({d.pk: d.review_status for d in self.task.detections.all()},
                         {dets[0].pk: DetectionReview.CONFIRMADO_POR_ESPECIALISTA,
                          dets[1].pk: DetectionReview.DESCARTADO})
        avisos = Notification.objects.filter(review=review)
        self.assertEqual({n.recipient_name for n in avisos}, {"Jefe de fundo", "Supervisor SWG1"})  # alcance y consentimiento
        self.assertTrue(all(n.status == NotificationStatus.PENDIENTE_ENVIO for n in avisos))
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.PENDIENTE_ENVIO)
        self.assertTrue(AuditEvent.objects.filter(action="CASO_DECIDIDO", entity_id=str(self.case.pk)).exists())

    def test_descartar_o_insuficiente_no_avisa(self):
        rv.decide_case(self.case.pk, self.w.esp, D, "")
        self.case.refresh_from_db()
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.NO_APLICA)
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(self.task.detections.exclude(review_status=DetectionReview.DESCARTADO).exists())

    def test_observacion_obligatoria_al_confirmar_y_en_insuficiente(self):
        for decision in (C, I):
            with self.assertRaises(ValidationError) as ctx:
                rv.decide_case(self.case.pk, self.w.esp, decision, " ")
            self.assertIn("observation", ctx.exception.error_dict)

    def test_cajas_y_clase_deben_pertenecer_al_caso(self):
        otro_cap, otra_task, _ = F.analyzed(self.w)
        ajena = otra_task.detections.first().pk
        with self.assertRaises(ValidationError) as ctx:
            rv.decide_case(self.case.pk, self.w.esp, C, "obs", rejected_detection_ids=[ajena])
        self.assertIn("rejected_detection_ids", ctx.exception.error_dict)
        with self.assertRaises(ValidationError) as ctx:
            rv.decide_case(self.case.pk, self.w.esp, C, "obs", confirmed_class="filoxera")
        self.assertIn("confirmed_class", ctx.exception.error_dict)

    def test_no_se_decide_dos_veces(self):
        rv.decide_case(self.case.pk, self.w.esp, D, "")
        with self.assertRaises(rv.CaseAlreadyDecided) as ctx:
            rv.decide_case(self.case.pk, self.w.esp2, C, "obs")
        self.assertEqual(ctx.exception.case.decided_by, self.w.esp)
        self.assertEqual(HumanReview.objects.count(), 1)

    def test_correccion_anula_avisos_pendientes_y_conserva_historial(self):
        first = rv.decide_case(self.case.pk, self.w.esp, C, "Colonias")
        enviado = Notification.objects.filter(review=first).order_by("pk").first()
        enviado.status = NotificationStatus.ENVIADO
        enviado.save()
        second = rv.correct_decision(self.case.pk, self.w.esp2, D, "Era pelusa", "Revisé el original", first.pk)
        self.case.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(self.case.status, D)
        self.assertFalse(first.is_current)
        self.assertEqual(second.supersedes, first)
        estados = dict(Notification.objects.values_list("recipient_name", "status"))
        self.assertEqual(sorted(estados.values()), sorted([NotificationStatus.NO_APLICA, NotificationStatus.ENVIADO]))
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.ENVIADO)  # lo enviado no se retira

    def test_correccion_de_descartado_a_confirmado_avisa_una_vez(self):
        first = rv.decide_case(self.case.pk, self.w.esp, D, "")
        second = rv.correct_decision(self.case.pk, self.w.esp, C, "Sí hay colonias", "Segunda mirada", first.pk)
        self.assertEqual(Notification.objects.filter(review=second).count(), 2)
        third = rv.correct_decision(self.case.pk, self.w.esp, C, "Colonias (texto corregido)", "Redacción", second.pk)
        self.assertEqual(Notification.objects.filter(review=third).count(), 0)  # no se repite el aviso

    def test_correccion_con_version_vieja(self):
        first = rv.decide_case(self.case.pk, self.w.esp, D, "")
        rv.correct_decision(self.case.pk, self.w.esp, I, "Borrosa", "Mejor no decidir", first.pk)
        with self.assertRaises(rv.StaleReview):
            rv.correct_decision(self.case.pk, self.w.esp2, C, "obs", "motivo", first.pk)

    def test_correccion_exige_motivo(self):
        first = rv.decide_case(self.case.pk, self.w.esp, D, "")
        with self.assertRaises(ValidationError):
            rv.correct_decision(self.case.pk, self.w.esp, C, "obs", " ", first.pk)


@skipUnlessDBFeature("has_select_for_update")
class DecisionConcurrente(TransactionTestCase):
    """Dos especialistas pulsan «Guardar» a la vez: SELECT … FOR UPDATE deja pasar solo a uno."""

    def test_un_solo_ganador(self):
        w = F.world()
        _, _, case = F.analyzed(w)
        results, barrier = [], threading.Barrier(2)

        def decide(user, decision):
            try:
                barrier.wait()
                rv.decide_case(case.pk, user, decision, "obs")
                results.append("ok")
            except rv.CaseAlreadyDecided:
                results.append("409")
            finally:
                connection.close()

        threads = [threading.Thread(target=decide, args=(w.esp, C)), threading.Thread(target=decide, args=(w.esp2, D))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["409", "ok"])
        self.assertEqual(HumanReview.objects.filter(case=case).count(), 1)
