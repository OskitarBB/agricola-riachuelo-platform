# campo/tests/test_mapa_satelital.py — QUÉ HACE: v1.3 (ADR-W-007) prueba la edición del mapa satelital: contorno de
# lotes, inicio y fin de hileras (crea los marcadores si faltan), puntos con nombre, permisos y la vista JSON.
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import AuditEvent
from campo import services as cat
from campo.models import Marker, MarkerPosition, PointOfInterest
from revision.services import case_location
from web.tests import factories as F

ANILLO = [[-75.7000, -14.0280], [-75.6990, -14.0280], [-75.6990, -14.0272], [-75.7000, -14.0272]]


class EdicionDelMapa(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_contorno_valido_se_cierra_y_se_audita(self):
        lot = cat.fijar_contorno_lote(self.w.sup, "SWG1", {"type": "Polygon", "coordinates": [ANILLO]})
        ring = lot.geometry["coordinates"][0]
        self.assertEqual((len(ring), ring[0]), (5, ring[-1]))
        self.assertTrue(AuditEvent.objects.filter(action="LOTE_CONTORNO").exists())
        lot = cat.fijar_contorno_lote(self.w.admin, "SWG1", None)
        self.assertIsNone(lot.geometry)

    def test_contorno_invalido(self):
        for g in ({"type": "Point", "coordinates": [0, 0]}, {"type": "Polygon", "coordinates": [ANILLO[:2]]},
                  {"type": "Polygon", "coordinates": [[[0, 95], [1, 1], [2, 2]]]}):
            with self.assertRaises(ValidationError):
                cat.fijar_contorno_lote(self.w.sup, "SWG1", g)

    def test_solo_admin_y_supervisor(self):
        for u in (self.w.esp, self.w.op):
            with self.assertRaises(PermissionDenied):
                cat.fijar_contorno_lote(u, "SWG1", None)
            with self.assertRaises(PermissionDenied):
                cat.crear_punto(u, "Almacén", "ALMACEN", -14.02, -75.69)

    def test_inicio_y_fin_crea_marcadores_y_sirven_de_ubicacion(self):
        r = cat.fijar_extremos_hilera(self.w.sup, self.w.row.pk, [-14.0279, -75.6999], [-14.0273, -75.6991])
        self.assertEqual({r["inicio"].position, r["fin"].position}, {MarkerPosition.INICIO, MarkerPosition.FIN})
        self.assertEqual((r["inicio"].lat, r["inicio"].lon), (-14.0279, -75.6999))
        # segunda vez: actualiza los mismos marcadores
        cat.fijar_extremos_hilera(self.w.sup, self.w.row.pk, [-14.0278, -75.6998], None)
        self.assertEqual(Marker.objects.filter(row=self.w.row, position=MarkerPosition.INICIO).count(), 1)
        # una foto sin GPS en ese marcador toma su coordenada
        cap = F.capture(self.w, gps=False, marker=False)
        cap.sequence.marker = r["inicio"]
        cap.sequence.save()
        loc = case_location(cap)
        self.assertEqual((loc["lat"], loc["location_source"]), (-14.0278, "MARCADOR"))

    def test_puntos_con_nombre(self):
        p = cat.crear_punto(self.w.admin, " Almacén  principal ", "ALMACEN", -14.0277, -75.6995, "Junto al portón")
        self.assertEqual(p.name, "Almacén principal")
        cat.editar_punto(self.w.sup, p.pk, "Almacén 1", "ALMACEN", -14.0276, -75.6995)
        cat.eliminar_punto(self.w.sup, p.pk)
        self.assertFalse(PointOfInterest.objects.get(pk=p.pk).active)
        with self.assertRaises(ValidationError):
            cat.crear_punto(self.w.admin, "", "OTRO", -14, -75)


class VistasDelMapa(TestCase):
    def setUp(self):
        self.w = F.world()

    def post(self, user, cuerpo):
        c = Client(enforce_csrf_checks=False)
        c.force_login(user)
        return c.post(reverse("web:mapa_editar"), json.dumps(cuerpo), content_type="application/json")

    def test_capas_y_edicion_por_json(self):
        r = self.post(self.w.sup, {"accion": "contorno", "lote": "SWG1",
                                   "geometry": {"type": "Polygon", "coordinates": [ANILLO]}})
        self.assertEqual(r.status_code, 200)
        capas = r.json()["capas"]
        self.assertEqual(capas["center"], [-14.027806, -75.699222])
        self.assertTrue(next(l for l in capas["lots"] if l["id"] == "SWG1")["geometry"])
        r = self.post(self.w.admin, {"accion": "punto_crear", "name": "Pozo 2", "kind": "POZO", "lat": -14.02,
                                     "lon": -75.69})
        self.assertEqual([p["name"] for p in r.json()["capas"]["points"]], ["Pozo 2"])
        r = self.post(self.w.admin, {"accion": "hilera", "hilera": self.w.row.pk, "inicio": [-14.0279, -75.6999],
                                     "fin": [-14.0273, -75.6991]})
        fila = next(h for h in r.json()["capas"]["rows"] if h["id"] == self.w.row.pk)
        self.assertEqual(fila["ini"], [-14.0279, -75.6999])

    def test_errores_y_permisos(self):
        r = self.post(self.w.sup, {"accion": "punto_crear", "name": "X", "kind": "NADA", "lat": 0, "lon": 0})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.post(self.w.esp, {"accion": "contorno", "lote": "SWG1", "geometry": None}).status_code,
                         403)
        c = Client()
        c.force_login(self.w.esp)
        self.assertEqual(c.get(reverse("web:mapa_capas")).status_code, 200)
        self.assertNotContains(c.get(reverse("web:mapa")), "Inicio y fin de hileras")
        c.force_login(self.w.sup)
        self.assertContains(c.get(reverse("web:mapa")), "Inicio y fin de hileras")

    def test_csrf_obligatorio(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.w.sup)
        r = c.post(reverse("web:mapa_editar"), json.dumps({"accion": "contorno", "lote": "SWG1", "geometry": None}),
                   content_type="application/json")
        self.assertEqual(r.status_code, 403)
