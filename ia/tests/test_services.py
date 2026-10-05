from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from auditoria.models import AuditEvent
from ia import services as ia
from ia.models import AiStatus
from web.tests import factories as F


class ColaDeAnalisis(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_reintentos_con_espera_y_error_final(self):
        cap = F.capture(self.w)
        ia.enqueue_analysis(cap)
        for intento in range(1, ia.MAX_ATTEMPTS + 1):
            task = ia.claim_next_task("w")
            self.assertEqual(task.attempts, intento)
            task = ia.mark_analysis_failed(task, "timeout descargando")
            if intento < ia.MAX_ATTEMPTS:
                self.assertEqual(task.status, AiStatus.PENDIENTE_DE_ANALISIS)
                self.assertGreater(task.available_at, timezone.now())
                type(task).objects.filter(pk=task.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(task.status, AiStatus.ERROR_DE_ANALISIS)

    def test_arrendamiento_vencido_vuelve_a_la_cola(self):
        cap = F.capture(self.w)
        ia.enqueue_analysis(cap)
        task = ia.claim_next_task("w1")
        self.assertIsNone(ia.claim_next_task("w2"))
        type(task).objects.filter(pk=task.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(ia.claim_next_task("w2").pk, task.pk)

    def test_reencolar_solo_errores_y_queda_auditado(self):
        cap = F.capture(self.w)
        task = ia.enqueue_analysis(cap)
        with self.assertRaises(ia.InvalidTaskState):
            ia.requeue_failed(task.pk, self.w.admin)
        type(task).objects.filter(pk=task.pk).update(status=AiStatus.ERROR_DE_ANALISIS, attempts=3)
        task = ia.requeue_failed(task.pk, self.w.admin)
        self.assertEqual((task.status, task.attempts), (AiStatus.PENDIENTE_DE_ANALISIS, 0))
        self.assertTrue(AuditEvent.objects.filter(action="TAREA_IA_REENCOLADA", user=self.w.admin).exists())
