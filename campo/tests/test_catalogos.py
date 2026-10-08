# campo/tests/test_catalogos.py — v1.2 (ADR-W-006): reglas de campo/services.py (IDs, validaciones, cascadas, auditoría).
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from auditoria.models import AuditEvent
from campo import services as cat
from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from web.tests import factories as F


class Base(TestCase):
    def setUp(self):
        self.w = F.world()
        self.u = self.w.sup  # el supervisor también gestiona catálogos

    def assertCampo(self, ctx, campo):
        self.assertIn(campo, ctx.exception.message_dict)


class PermisosEIds(Base):
    def test_solo_administrador_y_supervisor(self):
        for user in (self.w.esp, self.w.op):
            with self.assertRaises(PermissionDenied):
                cat.crear_lote(user, "SWG 9", "Prueba")
        self.assertTrue(cat.crear_lote(self.w.admin, "SWG 9", "Prueba"))

    def test_id_de_lote_sin_espacios_ni_tildes_y_sin_reutilizar(self):
        self.assertEqual(cat.crear_lote(self.u, "Ñuño 1", "Lote norte").pk, "NUNO1")
        FieldLot.objects.create(id="SWG7", code="otro", name="x", active=False)
        self.assertEqual(cat.crear_lote(self.u, "SWG 7", "Siete").pk, "SWG7-2")
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_lote(self.u, "swg 1", "Repetido")
        self.assertCampo(ctx, "code")

    def test_lote_editado_conserva_id(self):
        lot = cat.editar_lote(self.u, "SWG1", "SWG 1 Norte", "Lote uno")
        self.assertEqual((lot.pk, lot.code), ("SWG1", "SWG 1 Norte"))
        self.assertTrue(AuditEvent.objects.filter(action="CATALOGO_EDITADO", entity_id="SWG1").exists())


class Hileras(Base):
    def test_alta_en_bloque_salta_existentes_y_crea_segmento_completo(self):
        creadas, saltadas = cat.crear_hileras(self.u, "SWG1", 4, 7, 300)
        self.assertEqual((creadas, saltadas), ([4, 7], [5, 6]))
        seg = FieldSegment.objects.get(pk="SWG1-H04-S1")
        self.assertEqual((seg.code, seg.start_plant, seg.end_plant), ("H04 completa", 1, 300))
        self.assertEqual(set(Marker.objects.filter(row_id="SWG1-H04").values_list("pk", "position")),
                         {("SWG1-H04-INI", "INICIO"), ("SWG1-H04-FIN", "FIN")})
        ev = AuditEvent.objects.get(action="CATALOGO_LOTE_HILERAS")
        self.assertEqual(ev.after["creadas"], [4, 7])

    def test_alta_en_bloque_valida(self):
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_hileras(self.u, "SWG1", 9, 3, 300)
        self.assertCampo(ctx, "hasta")
        with self.assertRaises(ValidationError):
            cat.crear_hileras(self.u, "SWG1", 1, 1000, 300)

    def test_completar_no_reutiliza_ids_inactivos(self):
        FieldSegment.objects.create(id="SWG1-H06-S1", row=self.w.row_b, code="viejo", start_plant=1, end_plant=10,
                                    active=False)
        Marker.objects.create(id="SWG1-H06-INI", row=self.w.row_b, code="viejo", position="INICIO", active=False)
        n = cat.completar_hileras_sin_segmento(self.u, "SWG1")
        self.assertEqual(n, 1)  # H05 ya tenía un segmento activo
        self.assertTrue(FieldSegment.objects.filter(pk="SWG1-H06-S2", active=True).exists())
        self.assertTrue(Marker.objects.filter(pk="SWG1-H06-M1", position="INICIO", active=True).exists())

    def test_no_baja_plantas_por_debajo_de_un_segmento_activo(self):
        with self.assertRaises(ValidationError) as ctx:
            cat.editar_hilera(self.u, "SWG1-H05", 100)  # SWG1-S1 llega a la planta 204
        self.assertCampo(ctx, "plant_count")
        self.assertEqual(cat.editar_hilera(self.u, "SWG1-H05", 300).plant_count, 300)


class Segmentos(Base):
    def test_rango_solape_y_codigo(self):
        row = "SWG1-H05"  # 385 plantas; SWG1-S1 = 180..204
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_segmento(self.u, row, "S2", 200, 220)
        self.assertCampo(ctx, "start_plant")
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_segmento(self.u, row, "S2", 300, 400)
        self.assertCampo(ctx, "end_plant")
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_segmento(self.u, row, "swg 1-s1", 1, 50)
        self.assertCampo(ctx, "code")
        seg = cat.crear_segmento(self.u, row, "S2", 1, 179)
        self.assertEqual(seg.pk, "SWG1-H05-S1")  # primer ID libre con el formato del servidor

    def test_un_inactivo_no_bloquea(self):
        cat.desactivar(self.u, "segmento", "SWG1-S1")
        self.assertTrue(cat.crear_segmento(self.u, "SWG1-H05", "SWG 1-S1", 180, 204))

    def test_dividir_reemplaza_y_conserva_historia(self):
        nuevos = cat.dividir_hilera(self.u, "SWG1-H05", partes=3)
        self.assertEqual([(s.start_plant, s.end_plant) for s in nuevos], [(1, 129), (130, 257), (258, 385)])
        self.assertFalse(FieldSegment.objects.get(pk="SWG1-S1").active)
        self.assertFalse(Marker.objects.get(pk="SWG1-M1").active)  # marcador del segmento anterior
        posiciones = list(Marker.objects.filter(row_id="SWG1-H05", active=True).order_by("code")
                          .values_list("code", "position"))
        self.assertEqual(posiciones, [("H05 S1 inicio", "INICIO"), ("H05 S2 inicio", "INTERMEDIO"),
                                      ("H05 S3 inicio", "INTERMEDIO"), ("H05 fin", "FIN")])
        self.assertEqual(cat.rangos_division(10, cada=4), [(1, 4), (5, 8), (9, 10)])


class Marcadores(Base):
    def test_validaciones(self):
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_marcador(self.u, "SWG1-H05", "M9", "INICIO", lat=-14.0)
        self.assertCampo(ctx, "lat")
        seg_otra = FieldSegment.objects.create(id="SWG2-X", row=self.w.row2, code="X", start_plant=1, end_plant=5)
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_marcador(self.u, "SWG1-H05", "M9", "INICIO", segment_id=seg_otra.pk)
        self.assertCampo(ctx, "segment")
        with self.assertRaises(ValidationError) as ctx:
            cat.crear_marcador(self.u, "SWG1-H05", "m1", "INICIO")
        self.assertCampo(ctx, "code")
        m = cat.crear_marcador(self.u, "SWG1-H05", "M9", "FIN", segment_id="SWG1-S1", lat=-14.1, lon=-75.7)
        self.assertEqual((m.pk, m.segment_id), ("SWG1-H05-M1", "SWG1-S1"))


class DesactivarYReactivar(Base):
    def test_cascada_y_orden_de_reactivacion(self):
        cat.desactivar(self.u, "segmento", "SWG1-S1")
        self.assertFalse(Marker.objects.get(pk="SWG1-M1").active)
        with self.assertRaises(ValidationError):
            cat.reactivar(self.u, "marcador", "SWG1-M1")  # su segmento sigue inactivo
        cat.reactivar(self.u, "segmento", "SWG1-S1")
        cat.reactivar(self.u, "marcador", "SWG1-M1")
        cat.desactivar(self.u, "lote", "SWG1")
        cat.desactivar(self.u, "hilera", "SWG1-H05")
        with self.assertRaises(ValidationError):
            cat.reactivar(self.u, "hilera", "SWG1-H05")
        cat.reactivar(self.u, "lote", "SWG1")
        cat.reactivar(self.u, "hilera", "SWG1-H05")
        acciones = list(AuditEvent.objects.filter(action__startswith="CATALOGO_").values_list("action", flat=True))
        self.assertIn("CATALOGO_DESACTIVADO", acciones)
        self.assertIn("CATALOGO_REACTIVADO", acciones)

    def test_aviso_si_hay_sesion_en_curso_y_nada_se_borra(self):
        F.make_pass(self.w, self.w.row, "LATERAL_B", status="ACTIVE")
        from monitoreo.models import MonitoringSession

        MonitoringSession.objects.filter(pk=self.w.session.pk).update(status="ACTIVE")
        self.assertEqual(cat.desactivar(self.u, "hilera", "SWG1-H05"), 1)
        self.assertTrue(FieldRow.objects.filter(pk="SWG1-H05").exists())
