# ia/tests/test_exportar_dataset.py — QUÉ HACE: prueba el comando exportar_dataset (fotos y revisados), con la
# descarga reemplazada por un JPEG en memoria: nombres de archivo, etiquetas YOLO, cajas rechazadas y negativas.
import csv
import io
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from PIL import Image

from revision import services as rev
from revision.models import ReviewStatus
from web.tests import factories as F

FUMAGINA = {"class_name": "melaza_fumagina", "confidence": 0.55, "x_min": 1500, "y_min": 2000, "x_max": 1800,
            "y_max": 2600}


class ExportarDataset(TestCase):
    def setUp(self):
        self.w = F.world()
        self.w.model.classes = ["chanchito_blanco", "melaza_fumagina"]
        self.w.model.save(update_fields=["classes"])
        self.dir = Path(tempfile.mkdtemp())

    def exportar(self, *args):
        out = StringIO()
        call_command("exportar_dataset", *args, "--salida", str(self.dir), "--sin-imagenes", stdout=out)
        return out.getvalue()

    def test_revisados_confirmado_sin_cajas_rechazadas_y_descartado_negativo(self):
        cap1, task1, case1 = F.analyzed(self.w, boxes=(F.BOX, FUMAGINA))
        rechazada = task1.detections.get(class_name="melaza_fumagina")
        rev.decide_case(case1.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA,
                        observation="Colonia en el tronco", confirmed_class="chanchito_blanco",
                        rejected_detection_ids=[rechazada.pk])
        cap2, _, case2 = F.analyzed(self.w)
        rev.decide_case(case2.pk, self.w.esp, ReviewStatus.DESCARTADO, observation="Residuo de azufre")
        cap3, _, case3 = F.analyzed(self.w)  # pendiente: no se exporta

        salida = self.exportar("--modo", "revisados")
        self.assertIn("2 foto(s)", salida)
        self.assertIn("1 con cajas confirmadas, 1 negativas", salida)
        etiquetas = {p.stem: p.read_text() for p in (self.dir / "labels").glob("*.txt")}
        self.assertEqual(len(etiquetas), 2)
        nombre1 = f"SWG1-H05__{str(cap1.sequence_id)[:8]}__{str(cap1.capture_id)[:8]}"
        # BOX: x 100-400, y 200-520 en una imagen de 3000 x 4000 → centro (250, 360), tamaño 300 x 320
        self.assertEqual(etiquetas[nombre1].strip(), "0 0.083333 0.090000 0.100000 0.080000")
        nombre2 = f"SWG1-H05__{str(cap2.sequence_id)[:8]}__{str(cap2.capture_id)[:8]}"
        self.assertEqual(etiquetas[nombre2], "")
        filas = list(csv.DictReader(open(self.dir / "metadatos.csv", encoding="utf-8")))
        self.assertEqual({f["decision"] for f in filas}, {"CONFIRMADO_POR_ESPECIALISTA", "DESCARTADO"})
        self.assertNotIn(str(cap3.capture_id), {f["capture_id"] for f in filas})
        self.assertIn("1: melaza_fumagina", (self.dir / "data.yaml").read_text())

    def test_confirmado_manual_sin_cajas_no_es_negativa(self):
        cap, _, _ = F.analyzed(self.w, boxes=())  # la IA no sugirió nada (SIN_INDICIOS_IA)
        case, _ = rev.open_manual_case(cap.pk, self.w.esp)
        rev.decide_case(case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, observation="Colonia oculta")
        salida = self.exportar("--modo", "revisados")
        self.assertIn("1 confirmadas sin cajas", salida)
        self.assertEqual(list((self.dir / "labels").glob("*.txt")), [])

    def test_modo_fotos_filtra_por_hilera_y_no_escribe_etiquetas(self):
        F.capture(self.w)
        otra = F.make_pass(self.w, self.w.row2, "LATERAL_B")
        F.capture(self.w, monitoring_pass=otra)
        salida = self.exportar("--modo", "fotos", "--hilera", "SWG2-H01")
        self.assertIn("1 foto(s)", salida)
        self.assertFalse((self.dir / "labels").exists())
        filas = list(csv.DictReader(open(self.dir / "metadatos.csv", encoding="utf-8")))
        self.assertEqual([f["hilera"] for f in filas], ["SWG2-H01"])

    def test_descarga_guarda_jpeg_orientado_y_un_error_no_detiene(self):
        F.capture(self.w)
        F.capture(self.w)
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), (90, 140, 60)).save(buf, format="JPEG")
        err = StringIO()
        with mock.patch("evidencias.nube.download_original", side_effect=[buf.getvalue(), TimeoutError("red")]):
            call_command("exportar_dataset", "--modo", "fotos", "--salida", str(self.dir), stdout=StringIO(),
                         stderr=err)
        fotos = list((self.dir / "images").glob("*.jpg"))
        self.assertEqual(len(fotos), 1)
        with Image.open(fotos[0]) as im:
            self.assertEqual((im.format, im.size), ("JPEG", (40, 30)))
        self.assertIn("no se pudo bajar", err.getvalue())
