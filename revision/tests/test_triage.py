# revision/tests/test_triage.py — QUÉ HACE: v1.3.1 (ADR-W-008) prueba el triage en tres franjas (descarta la IA,
# revisa el especialista, confirma la IA), el comando aplicar_triage y que un descartado se pueda abrir a mano.
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from auditoria.models import AuditEvent
from ia.models import AiStatus, AiTask
from revision import services as rv
from revision.models import Case, ReviewStatus
from web.tests import factories as F

BAJA = dict(F.BOX, confidence=0.35)
MEDIA = dict(F.BOX, confidence=0.66)
ALTA = dict(F.BOX, confidence=0.92)


class TresFranjas(TestCase):
    def setUp(self):
        self.w = F.world()
        self.w.model.review_threshold = 0.50
        self.w.model.auto_confirm_threshold = 0.85
        self.w.model.save(update_fields=["review_threshold", "auto_confirm_threshold"])

    def test_baja_confianza_la_descarta_la_ia_sin_caso(self):
        _, task, case = F.analyzed(self.w, boxes=(BAJA,))
        self.assertIsNone(case)
        task.refresh_from_db()
        self.assertEqual(task.status, AiStatus.DESCARTADO_POR_IA)
        self.assertEqual(task.detections.count(), 1)  # las cajas se conservan para medir y reentrenar
        self.assertFalse(Case.objects.exists())

    def test_confianza_media_va_al_especialista(self):
        _, _, case = F.analyzed(self.w, boxes=(BAJA, MEDIA))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.PENDIENTE_REVISION)

    def test_alta_confianza_la_confirma_la_ia(self):
        _, _, case = F.analyzed(self.w, boxes=(ALTA,))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_IA)

    def test_sin_umbral_de_revision_todo_indicio_abre_caso(self):
        self.w.model.review_threshold = None
        self.w.model.save(update_fields=["review_threshold"])
        _, _, case = F.analyzed(self.w, boxes=(BAJA,))
        self.assertIsNotNone(case)

    def test_el_especialista_puede_abrir_un_descartado(self):
        capture, _, _ = F.analyzed(self.w, boxes=(BAJA,))
        case, creado = rv.open_manual_case(capture.pk, self.w.esp)
        self.assertTrue(creado)
        self.assertEqual(case.origin, Case.Origin.MANUAL)


class ComandoAplicarTriage(TestCase):
    def setUp(self):
        self.w = F.world()  # sin umbrales: todo abre caso, como hasta v1.3
        self.bajo = F.analyzed(self.w, boxes=(BAJA,))[2]
        self.medio = F.analyzed(self.w, boxes=(MEDIA,))[2]
        self.alto = F.analyzed(self.w, boxes=(ALTA,))[2]
        self.decidido = F.analyzed(self.w, boxes=(BAJA,))[2]
        rv.decide_case(self.decidido.pk, self.w.esp, ReviewStatus.POSIBLE_PLAGA, "")

    def correr(self, *args):
        out = StringIO()
        call_command("aplicar_triage", *args, stdout=out)
        return out.getvalue()

    def test_simular_no_cambia_nada(self):
        txt = self.correr("--revision", "0.50", "--auto", "0.85", "--simular")
        self.assertIn("1 descartados", txt)
        self.assertIn("1 confirmados", txt)
        self.assertEqual(Case.objects.count(), 4)
        self.w.model.refresh_from_db()
        self.assertIsNone(self.w.model.review_threshold)

    def test_aplica_las_tres_franjas_sin_tocar_decisiones(self):
        txt = self.correr("--revision", "0,50", "--auto", "0.85")
        self.assertIn("1 quedan para el especialista", txt)
        self.assertFalse(Case.objects.filter(pk=self.bajo.pk).exists())
        self.assertEqual(AiTask.objects.get(pk=self.bajo.ai_task_id).status, AiStatus.DESCARTADO_POR_IA)
        self.assertEqual(Case.objects.get(pk=self.medio.pk).status, ReviewStatus.PENDIENTE_REVISION)
        self.assertEqual(Case.objects.get(pk=self.alto.pk).status, ReviewStatus.CONFIRMADO_POR_IA)
        self.assertEqual(Case.objects.get(pk=self.decidido.pk).status, ReviewStatus.POSIBLE_PLAGA)
        self.assertTrue(AuditEvent.objects.filter(action="CASO_DESCARTADO_POR_IA").exists())
        self.assertTrue(AuditEvent.objects.filter(action="MODELO_UMBRALES").exists())

    def test_rechaza_umbrales_invertidos(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.correr("--revision", "0.9", "--auto", "0.5")
