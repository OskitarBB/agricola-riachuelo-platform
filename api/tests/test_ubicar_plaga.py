# api/tests/test_ubicar_plaga.py — QUÉ HACE: v1.3 (ADR-W-007) prueba GET /api/v1/mobile/pest-reports («Ubicar plaga»):
# qué alertas salen (confirmadas, posibles y en revisión; no descartadas), los datos de ubicación y capas del fundo, y
# que el especialista ingresa a la app solo para esto (las rutas de monitoreo le responden 403 ROLE_NOT_ALLOWED).
from api.tests.test_api import API, Base
from campo import services as cat
from revision import services as rv
from revision.models import ReviewStatus
from web.tests import factories as F


class UbicarPlaga(Base):
    def setUp(self):
        super().setUp()
        _, _, self.pendiente = F.analyzed(self.w)
        _, _, self.confirmado = F.analyzed(self.w)
        rv.decide_case(self.confirmado.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias",
                       "chanchito_blanco")
        _, _, self.posible = F.analyzed(self.w)
        rv.decide_case(self.posible.pk, self.w.esp, ReviewStatus.POSIBLE_PLAGA, "")
        _, _, self.descartado = F.analyzed(self.w)
        rv.decide_case(self.descartado.pk, self.w.esp, ReviewStatus.DESCARTADO, "")
        cat.crear_punto(self.w.admin, "Almacén", "ALMACEN", -14.0277, -75.6995)

    def test_operador_ve_alertas_sin_descartados(self):
        self.autenticar("op@x.pe")
        r = self.c.get(f"{API}/mobile/pest-reports")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        ids = {x["caseId"]: x for x in d["reports"]}
        self.assertEqual(set(ids), {str(self.pendiente.pk), str(self.confirmado.pk), str(self.posible.pk)})
        c = ids[str(self.confirmado.pk)]
        self.assertEqual((c["status"], c["label"], c["lot"]["code"], c["row"]["number"]),
                         (ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "chanchito_blanco", "SWG 1", 5))
        self.assertEqual((c["lat"], c["lon"], c["locationSource"]), (-14.0601, -75.7302, "GPS"))
        self.assertTrue(c["thumbnailUrl"].startswith("https://"))
        self.assertEqual(c["segment"]["startPlant"], 180)
        self.assertEqual([p["name"] for p in d["farm"]["points"]], ["Almacén"])
        self.assertIn("center", d["farm"])

    def test_especialista_entra_solo_a_ubicar_plaga(self):
        self.autenticar("esp@x.pe")
        self.assertEqual(self.c.get(f"{API}/mobile/pest-reports").status_code, 200)
        r = self.c.post(f"{API}/sessions", {}, format="json")
        self.assertError(r, 403, "ROLE_NOT_ALLOWED")

    def test_supervisor_sigue_sin_app_y_sin_token_401(self):
        self.assertError(self.login("sup@x.pe"), 403, "ROLE_NOT_ALLOWED")
        self.assertEqual(self.c.get(f"{API}/mobile/pest-reports").status_code, 401)
