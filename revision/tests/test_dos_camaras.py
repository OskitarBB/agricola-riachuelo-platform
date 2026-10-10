# revision/tests/test_dos_camaras.py — QUÉ HACE: v1.3.3 (ADR-W-009) prueba que las dos cámaras de un mismo lugar
# (secuencia) se deciden juntas con la regla «basta una cámara»: un solo caso por lugar, anclado en la foto de mayor
# confianza; la foto descartada de la otra cámara no aparece sola en «Descartadas por la IA» ni se borra en la limpieza.
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from evidencias import limpieza
from ia import services as ia
from ia.models import AiStatus
from notificaciones.models import Notification
from revision import services as rv
from revision.models import Case, ReviewStatus
from web.tests import factories as F

BAJA = dict(F.BOX, confidence=0.40)
MEDIA = dict(F.BOX, confidence=0.70)
ALTA = dict(F.BOX, confidence=0.90)


def analizar(cap, boxes):
    ia.enqueue_analysis(cap)
    task = ia.claim_next_task("test")
    return ia.save_analysis_result(task, list(boxes), 3000, 4000, 120, "v1", {"ok": True})


class DosCamaras(TestCase):
    def setUp(self):
        self.w = F.world()
        self.w.model.review_threshold = 0.65
        self.w.model.auto_confirm_threshold = 0.85
        self.w.model.save(update_fields=["review_threshold", "auto_confirm_threshold"])
        self.c1 = F.capture(self.w, role="CAMERA_1")
        self.c2 = F.capture(self.w, role="CAMERA_2", sequence=self.c1.sequence)

    def test_una_descarta_y_la_otra_ve_indicio_un_solo_caso_del_lugar(self):
        t1, caso1 = analizar(self.c1, (BAJA,))
        self.assertIsNone(caso1)
        self.assertEqual(t1.status, AiStatus.DESCARTADO_POR_IA)
        _, caso = analizar(self.c2, (MEDIA,))
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(caso.capture_id, self.c2.pk)
        self.assertEqual(caso.status, ReviewStatus.PENDIENTE_REVISION)
        # la foto descartada de la cámara 1 ya no aparece sola: es parte del caso del lugar
        self.client.force_login(self.w.esp)
        r = self.client.get(reverse("web:descartadas_ia"))
        self.assertEqual(r.context["page"].paginator.count, 0)
        r = self.client.get(reverse("web:captura", args=[self.c1.pk]))
        self.assertContains(r, "La otra cámara fotografió el mismo lugar")
        self.assertNotContains(r, "Abrir caso para revisión")

    def test_dos_indicios_no_duplican_el_caso_y_manda_la_mayor_confianza(self):
        _, caso = analizar(self.c1, (MEDIA,))
        _, caso_b = analizar(self.c2, (ALTA,))
        self.assertEqual(caso.pk, caso_b.pk)
        self.assertEqual(Case.objects.count(), 1)
        caso_b.refresh_from_db()
        self.assertEqual(caso_b.capture_id, self.c2.pk)       # la foto principal pasa a ser la de 0.90
        self.assertEqual(caso_b.max_confidence, 0.90)
        self.assertEqual(caso_b.status, ReviewStatus.CONFIRMADO_POR_IA)  # basta una cámara para confirmar
        self.assertEqual(Notification.objects.filter(case=caso_b).count(),
                         Notification.objects.count())  # un solo aviso por lugar

    def test_la_segunda_con_menos_confianza_respalda_sin_cambiar(self):
        _, caso = analizar(self.c1, (ALTA,))
        _, caso_b = analizar(self.c2, (MEDIA,))
        self.assertEqual(caso.pk, caso_b.pk)
        caso.refresh_from_db()
        self.assertEqual(caso.capture_id, self.c1.pk)
        self.assertEqual(Case.objects.count(), 1)

    def test_las_dos_bajas_se_descartan(self):
        analizar(self.c1, (BAJA,))
        analizar(self.c2, ())
        self.assertFalse(Case.objects.exists())
        self.client.force_login(self.w.esp)
        r = self.client.get(reverse("web:descartadas_ia"))
        self.assertEqual(r.context["page"].paginator.count, 2)

    def test_una_sola_foto_usa_las_tres_franjas(self):
        caso = F.analyzed(self.w, boxes=(ALTA,))[2]  # secuencia con una sola cámara
        caso.refresh_from_db()
        self.assertEqual(caso.status, ReviewStatus.CONFIRMADO_POR_IA)

    def test_abrir_a_mano_la_otra_camara_devuelve_el_caso_del_lugar(self):
        analizar(self.c1, (BAJA,))
        _, caso = analizar(self.c2, (MEDIA,))
        mismo, creado = rv.open_manual_case(self.c1.pk, self.w.esp)
        self.assertFalse(creado)
        self.assertEqual(mismo.pk, caso.pk)

    def test_la_limpieza_no_borra_la_otra_camara_de_un_lugar_con_caso(self):
        from datetime import timedelta

        from django.utils import timezone

        from evidencias.models import Capture

        analizar(self.c1, (BAJA,))
        analizar(self.c2, (MEDIA,))
        Capture.objects.update(captured_at=timezone.now() - timedelta(days=60))
        self.assertFalse(limpieza.descartadas_qs(30).filter(pk=self.c1.pk).exists())


class UnirCasosAntiguos(TestCase):
    def test_aplicar_triage_une_los_casos_duplicados_de_un_lugar(self):
        w = F.world()  # sin umbrales: como antes, cada cámara abrió su caso
        c1 = F.capture(w, role="CAMERA_1")
        c2 = F.capture(w, role="CAMERA_2", sequence=c1.sequence)
        analizar(c1, (MEDIA,))
        Case.objects.create(**{f.attname: getattr(Case.objects.get(), f.attname) for f in Case._meta.fields
                               if f.attname not in ("id", "capture_id", "max_confidence")},
                            capture_id=c2.pk, max_confidence=0.9)
        self.assertEqual(Case.objects.count(), 2)
        call_command("aplicar_triage", "--simular", stdout=open("/dev/null", "w"))
        self.assertEqual(Case.objects.count(), 2)
        call_command("aplicar_triage", "--revision", "0.65", stdout=open("/dev/null", "w"))
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(Case.objects.get().capture_id, c2.pk)
