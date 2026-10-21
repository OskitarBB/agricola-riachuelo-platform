# campo/tests/test_segmentos_fijos.py — v1.4 (ADR-W-010): cantidad fija de segmentos por hilera, largo en metros,
# reparto estándar, estandarizar un lote, coordenadas al dividir y el comando crear_lotes_estandar.
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from auditoria.models import AuditEvent
from campo import services as cat
from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from web.tests import factories as F
from web.tests.test_views import login


class Base(TestCase):
    def setUp(self):
        self.w = F.world()
        self.u = self.w.sup

    def rangos(self, row_id):
        return list(FieldSegment.objects.filter(row_id=row_id, active=True).order_by("start_plant")
                    .values_list("start_plant", "end_plant"))


class Limite(Base):
    @override_settings(SEGMENTOS_POR_HILERA=2)
    def test_crear_segmento_no_pasa_la_cantidad_fija(self):
        cat.crear_segmento(self.u, "SWG1-H05", "S2", 1, 100)  # ya tenía SWG1-S1: quedan 2 de 2
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_segmento(self.u, "SWG1-H05", "S3", 300, 310)
        self.assertIn("cantidad fija", " ".join(ctx.exception.messages))

    @override_settings(SEGMENTOS_POR_HILERA=1)
    def test_reactivar_tampoco_pasa_el_limite(self):
        cat.desactivar(self.u, "segmento", "SWG1-S1")
        cat.crear_segmento(self.u, "SWG1-H05", "S2", 1, 50)
        with self.assertRaises(ValidationError):
            cat.reactivar(self.u, "segmento", "SWG1-S1")

    def test_dividir_respeta_el_maximo(self):
        with self.assertRaises(ValidationError):
            cat.dividir_hilera(self.u, "SWG1-H05", partes=11)
        with self.assertRaises(ValidationError):
            cat.dividir_hilera(self.u, "SWG1-H05", cada=10)  # 385 plantas → 39 segmentos
        nuevos = cat.dividir_hilera(self.u, "SWG1-H05", partes=10)
        self.assertEqual(len(nuevos), 10)
        self.assertTrue(cat.estado_segmentos(FieldRow.objects.get(pk="SWG1-H05"))["estandar"])


class RepartoEstandar(Base):
    def test_alta_por_largo_crea_10_segmentos_de_20_m(self):
        creadas, _ = cat.crear_hileras(self.u, "SWG2", 2, 3, None, largo_m=200, division="estandar")
        self.assertEqual(creadas, [2, 3])
        row = FieldRow.objects.get(pk="SWG2-H02")
        self.assertEqual((row.plant_count, row.length_m), (133, 200))  # 200 m / 1,5 m
        rangos = self.rangos(row.pk)
        self.assertEqual(len(rangos), 10)
        self.assertEqual(rangos[0], (1, 14))
        self.assertEqual(rangos[-1], (121, 133))
        self.assertTrue(all(b + 1 == c for (_, b), (c, _) in zip(rangos, rangos[1:])))  # contiguos, sin huecos
        marcadores = list(Marker.objects.filter(row=row, active=True).order_by("pk").values_list("code", "position"))
        self.assertEqual(len(marcadores), 11)
        self.assertEqual(marcadores[0], ("H02 S1 inicio", "INICIO"))
        self.assertIn(("H02 S10 inicio", "INTERMEDIO"), marcadores)
        self.assertIn(("H02 fin", "FIN"), marcadores)
        estado = cat.estado_segmentos(row)
        self.assertEqual((estado["n"], estado["total"], estado["estandar"], estado["metros_por_segmento"]),
                         (10, 10, True, 20.0))
        ev = AuditEvent.objects.filter(action="CATALOGO_LOTE_HILERAS", entity_id="SWG2").latest("pk")
        self.assertEqual((ev.after["largoM"], ev.after["division"]), (200, "estandar"))

    def test_largo_invalido_y_plantas_requeridas(self):
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_hileras(self.u, "SWG2", 5, 5, None, largo_m=0)
        self.assertIn("plantas", ctx.exception.message_dict)
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_hileras(self.u, "SWG2", 5, 5, None, largo_m=99999)
        self.assertIn("largo_m", ctx.exception.message_dict)

    def test_estado_detecta_huecos_y_exceso(self):
        estado = cat.estado_segmentos(self.w.row)  # SWG1-S1 = 180..204 de 385 plantas
        self.assertEqual(estado["huecos"], [(1, 179), (205, 385)])
        self.assertFalse(estado["estandar"])

    def test_editar_hilera_con_largo(self):
        row = cat.editar_hilera(self.u, "SWG1-H05", 385, 560)
        self.assertEqual(row.length_m, 560)
        ev = AuditEvent.objects.filter(action="CATALOGO_EDITADO", entity_id="SWG1-H05").latest("pk")
        self.assertEqual(ev.after, {"length_m": 560})
        with self.assertRaises(ValidationError):
            cat.editar_hilera(self.u, "SWG1-H05", 385, 0)
        self.assertEqual(cat.editar_hilera(self.u, "SWG1-H05", 385).length_m, 560)  # sin largo: no se toca


class Estandarizar(Base):
    def test_solo_cambia_las_hileras_fuera_del_estandar(self):
        cat.crear_hileras(self.u, "SWG1", 7, 7, None, largo_m=200, division="estandar")
        antes_h07 = set(FieldSegment.objects.filter(row_id="SWG1-H07", active=True).values_list("pk", flat=True))
        cambiadas = cat.estandarizar_lote(self.u, "SWG1")
        self.assertEqual(cambiadas, [5, 6])
        self.assertEqual(set(FieldSegment.objects.filter(row_id="SWG1-H07", active=True)
                             .values_list("pk", flat=True)), antes_h07)
        self.assertEqual(len(self.rangos("SWG1-H05")), 10)
        self.assertFalse(FieldSegment.objects.get(pk="SWG1-S1").active)  # la historia se conserva (inactivo)
        self.assertTrue(AuditEvent.objects.filter(action="CATALOGO_LOTE_SEGMENTOS", entity_id="SWG1").exists())
        self.assertEqual(cat.estandarizar_lote(self.u, "SWG1"), [])  # segunda vez: nada que hacer

    def test_al_dividir_se_reutilizan_e_interpolan_las_coordenadas(self):
        cat.completar_hileras_sin_segmento(self.u, "SWG2")  # SWG2-H01 completa con -INI y -FIN
        cat.fijar_extremos_hilera(self.u, "SWG2-H01", inicio=(-14.0, -75.0), fin=(-14.0, -75.01))
        cat.dividir_hilera(self.u, "SWG2-H01", partes=10)
        activos = {m.code: m for m in Marker.objects.filter(row_id="SWG2-H01", active=True)}
        self.assertEqual((activos["H01 S1 inicio"].lat, activos["H01 S1 inicio"].lon), (-14.0, -75.0))
        self.assertEqual(activos["H01 fin"].lon, -75.01)
        s6 = FieldSegment.objects.get(row_id="SWG2-H01", active=True, code="H01 S6")
        esperado = round(-75.0 + (s6.start_plant - 1) / 250 * -0.01, 7)
        self.assertAlmostEqual(activos["H01 S6 inicio"].lon, esperado, places=6)

    def test_desde_la_web(self):
        c = login(Client(), self.u)
        r = c.post(reverse("web:catalogo_lote", args=["SWG1"]), {"accion": "estandarizar"}, follow=True)
        self.assertContains(r, "2 hilera(s) quedaron con sus 10 segmentos")
        r = c.get(reverse("web:catalogo_hilera", args=["SWG1-H05"]))
        self.assertContains(r, "10 de 10 segmentos")
        self.assertContains(r, "ya tiene sus 10 segmentos")


class ComandoLotesEstandar(Base):
    def test_crea_lotes_hileras_y_segmentos_y_es_idempotente(self):
        out = StringIO()
        call_command("crear_lotes_estandar", lotes=2, hileras=3, usuario=self.w.admin.email, stdout=out)
        self.assertEqual(list(FieldLot.objects.filter(pk__startswith="LOTE").order_by("pk")
                              .values_list("pk", "code")), [("LOTE01", "LOTE 01"), ("LOTE02", "LOTE 02")])
        self.assertEqual(FieldRow.objects.filter(lot_id="LOTE01", plant_count=133, length_m=200).count(), 3)
        self.assertEqual(FieldSegment.objects.filter(row__lot_id="LOTE02", active=True).count(), 30)
        self.assertEqual(Marker.objects.filter(row__lot_id="LOTE02", active=True).count(), 33)
        self.assertIn("2 lote(s) y 6 hilera(s) nuevas", out.getvalue())
        call_command("crear_lotes_estandar", lotes=2, hileras=4, stdout=StringIO())  # agrega solo la hilera 4
        self.assertEqual(FieldRow.objects.filter(lot_id="LOTE01").count(), 4)
        self.assertEqual(FieldSegment.objects.filter(row__lot_id="LOTE01", active=True).count(), 40)
        self.assertEqual(FieldLot.objects.filter(pk__startswith="LOTE").count(), 2)
        self.assertTrue(FieldLot.objects.filter(pk="SWG1", active=True).exists())  # no toca los demás lotes

    def test_simular_no_escribe(self):
        out = StringIO()
        call_command("crear_lotes_estandar", simular=True, stdout=out)
        self.assertIn("LOTE 01 a LOTE 10", out.getvalue())
        self.assertFalse(FieldLot.objects.filter(pk__startswith="LOTE").exists())
