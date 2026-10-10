# web/tests/test_descartadas_ia.py — QUÉ HACE: v1.3.2 prueba la página «Descartadas por la IA»: muestra las fotos que
# la IA descartó (indicio débil o sin indicios) y sin caso, filtra por resultado y deja abrir la foto para rescatarla.
from django.test import TestCase
from django.urls import reverse

from ia.models import AiStatus
from revision import services as rv
from web.tests import factories as F

BAJA = dict(F.BOX, confidence=0.35)
MEDIA = dict(F.BOX, confidence=0.66)


class DescartadasIA(TestCase):
    def setUp(self):
        self.w = F.world()
        self.w.model.review_threshold = 0.50
        self.w.model.auto_confirm_threshold = 0.85
        self.w.model.save(update_fields=["review_threshold", "auto_confirm_threshold"])
        self.debil = F.analyzed(self.w, boxes=(BAJA,))[0]       # DESCARTADO_POR_IA
        self.nada = F.analyzed(self.w, boxes=())[0]             # SIN_INDICIOS_IA
        self.caso = F.analyzed(self.w, boxes=(MEDIA,))[0]       # abre caso: no debe aparecer
        self.client.force_login(self.w.esp)
        self.url = reverse("web:descartadas_ia")

    def ids(self, resp):
        return {t.capture_id for t in resp.context["page"].object_list}

    def test_lista_las_descartadas_y_no_las_que_tienen_caso(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ids(r), {self.debil.pk, self.nada.pk})
        self.assertContains(r, "Descartado por la IA")
        self.assertContains(r, "máx. 0,35")

    def test_filtra_por_resultado(self):
        r = self.client.get(self.url, {"tipo": AiStatus.DESCARTADO_POR_IA})
        self.assertEqual(self.ids(r), {self.debil.pk})
        r = self.client.get(self.url, {"tipo": AiStatus.SIN_INDICIOS_IA})
        self.assertEqual(self.ids(r), {self.nada.pk})

    def test_al_rescatarla_sale_de_la_lista(self):
        rv.open_manual_case(self.debil.pk, self.w.esp)
        self.assertEqual(self.ids(self.client.get(self.url)), {self.nada.pk})

    def test_la_foto_muestra_confianza_y_umbral_y_el_boton_de_rescate(self):
        r = self.client.get(reverse("web:captura", args=[self.debil.pk]))
        self.assertContains(r, "umbral de revisión 0,50")
        self.assertContains(r, "Abrir caso para revisión")

    def test_la_bandeja_enlaza_a_las_descartadas(self):
        self.assertContains(self.client.get(reverse("web:bandeja")), self.url)

    def test_el_operador_no_entra(self):
        self.client.force_login(self.w.op)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_la_bandeja_carga_la_franja_aparte_y_sigue_en_6_consultas(self):
        r = self.client.get(reverse("web:bandeja"))
        self.assertContains(r, reverse("web:descartadas_resumen"))
        r = self.client.get(reverse("web:descartadas_resumen"), {"lote": "SWG1", "estado": "POR_REVISAR", "orden": "antiguos", "origen": ""})
        self.assertContains(r, "2 fotos sin caso")
        self.assertContains(r, "máx. 0,35")
        self.assertContains(r, "?lote=SWG1")
        r = self.client.get(reverse("web:descartadas_resumen"), {"lote": "SWG2"})
        self.assertContains(r, "La IA no descartó fotos")

    def test_el_estado_descartadas_de_la_bandeja_lleva_a_la_lista(self):
        r = self.client.get(reverse("web:bandeja"), {"estado": "DESCARTADAS_IA", "lote": "SWG1"})
        self.assertRedirects(r, self.url + "?lote=SWG1")
