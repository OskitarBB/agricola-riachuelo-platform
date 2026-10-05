# ia/tests/test_inferencia.py — Decodificación de salidas YOLO (ONNX), NMS, recortes, detector ONNX con una sesión
# falsa (sin pesos reales) y el worker_ia de punta a punta en modo --once.
import io
import tempfile
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from ia import services as ia
from ia.inference import DetectorNoDisponible, abrir_imagen, cargar_detector
from ia.models import AiStatus, AiTask
from notificaciones.models import Notification, NotificationStatus
from revision import services as rv
from revision.models import Case, ReviewStatus
from web.tests import factories as F

try:
    import numpy as np
    import onnxruntime  # noqa: F401
    HAY_ONNX = True
except ImportError:  # requirements-ia.txt no instalado: se omiten estas pruebas
    HAY_ONNX = False


def jpeg(w, h, exif_orientation=None):
    img = Image.new("RGB", (w, h), (40, 110, 60))
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


@skipUnless(HAY_ONNX, "Falta numpy/onnxruntime (pip install -r requirements-ia.txt)")
class Decodificacion(SimpleTestCase):
    def test_formato_yolov8_con_nms_por_clase(self):
        from ia.inference.onnx import decode

        # (1, 4 + 2 clases, 4 propuestas): dos cajas casi iguales de la clase 0, una de la clase 1 y una débil
        out = np.zeros((1, 6, 4), dtype=np.float32)
        out[0, :4, 0] = [100, 100, 40, 40]
        out[0, 4, 0] = 0.9
        out[0, :4, 1] = [102, 101, 40, 40]
        out[0, 4, 1] = 0.7
        out[0, :4, 2] = [300, 300, 50, 50]
        out[0, 5, 2] = 0.8
        out[0, :4, 3] = [500, 500, 10, 10]
        out[0, 4, 3] = 0.1
        boxes, scores, cls = decode(out, conf=0.25, iou=0.45, num_classes=2)
        self.assertEqual(len(boxes), 2)
        self.assertEqual(sorted(cls.tolist()), [0, 1])
        i = int(np.where(cls == 0)[0][0])
        self.assertAlmostEqual(float(scores[i]), 0.9, places=5)
        self.assertEqual(boxes[i].tolist(), [80.0, 80.0, 120.0, 120.0])  # cx, cy, w, h → x1, y1, x2, y2

    def test_formato_end2end_sin_nms(self):
        from ia.inference.onnx import decode

        out = np.array([[[10, 20, 50, 80, 0.88, 0], [0, 0, 5, 5, 0.05, 0]] + [[0] * 6] * 6], dtype=np.float32)
        boxes, scores, cls = decode(out, conf=0.25, iou=0.45)
        self.assertEqual((len(boxes), boxes[0].tolist(), int(cls[0])), (1, [10, 20, 50, 80], 0))

    def test_forma_inesperada_explica_el_problema(self):
        from ia.inference.onnx import decode

        with self.assertRaisesRegex(ValueError, "forma inesperada"):
            decode(np.zeros((1, 3, 3), dtype=np.float32), conf=0.25, iou=0.45)

    def test_recortes_cubren_toda_la_foto(self):
        from ia.inference.onnx import tiles

        self.assertEqual(tiles(600, 800, 0, 0.2), [(0, 0, 600, 800)])
        recortes = tiles(3000, 4000, 1280, 0.2)
        self.assertEqual(max(x2 for _, _, x2, _ in recortes), 3000)
        self.assertEqual(max(y2 for _, _, _, y2 in recortes), 4000)
        self.assertTrue(all(x2 - x1 == 1280 and y2 - y1 == 1280 for x1, y1, x2, y2 in recortes))

    def test_letterbox_mantiene_proporcion(self):
        from ia.inference.onnx import letterbox

        x, r, dx, dy = letterbox(Image.new("RGB", (300, 400)), 640)
        self.assertEqual((x.shape, round(r, 3), dx, dy), ((1, 3, 640, 640), 1.6, 80, 0))

    def test_orientacion_exif_se_aplica_antes_de_analizar(self):
        img = abrir_imagen(jpeg(400, 300, exif_orientation=6))  # foto vertical guardada «acostada»
        self.assertEqual(img.size, (300, 400))


class SesionFalsa:
    """Imita onnxruntime.InferenceSession: devuelve una caja en coordenadas del tensor letterbox (640×640)."""

    def __init__(self, *args, **kwargs):
        pass

    def get_inputs(self):
        return [SimpleNamespace(name="images", shape=[1, 3, 640, 640])]

    def run(self, _outputs, feeds):
        out = np.zeros((1, 5, 3), dtype=np.float32)  # una sola clase
        out[0, :, 0] = [320, 320, 64, 64, 0.77]
        return [out]


@skipUnless(HAY_ONNX, "Falta numpy/onnxruntime (pip install -r requirements-ia.txt)")
class DetectorOnnxConSesionFalsa(TestCase):
    def setUp(self):
        self.w = F.world()
        self.pesos = tempfile.NamedTemporaryFile(suffix=".onnx")
        self.pesos.write(b"modelo")
        self.pesos.flush()

    def tearDown(self):
        self.pesos.close()

    def test_cajas_vuelven_a_pixeles_de_la_foto_original(self):
        cap = F.capture(self.w)
        task = ia.enqueue_analysis(cap)
        with override_settings(MODEL_PATH=self.pesos.name), \
                mock.patch("onnxruntime.InferenceSession", SesionFalsa), \
                mock.patch("evidencias.nube.download_original", return_value=jpeg(1200, 1600)):
            det = cargar_detector(self.w.model, "onnx")
            r = det.analyze(task)
        self.assertEqual((r.width, r.height, len(r.boxes)), (1200, 1600, 1))
        b = r.boxes[0]
        # escala 640/1600 = 0.4; relleno horizontal (640 − 480) / 2 = 80 → caja centrada de 160 px en la foto
        self.assertEqual((b["x_min"], b["y_min"], b["x_max"], b["y_max"]), (520.0, 720.0, 680.0, 880.0))
        self.assertEqual((b["class_name"], b["confidence"]), ("chanchito_blanco", 0.77))

    def test_sin_pesos_el_detector_no_esta_disponible(self):
        with override_settings(MODEL_PATH="/no/existe.onnx"), self.assertRaises(DetectorNoDisponible):
            cargar_detector(self.w.model, "onnx")


class WorkerIa(TestCase):
    def setUp(self):
        self.w = F.world()

    @override_settings(IA_SIMULADO_PROBABILIDAD=1.0)
    def test_once_analiza_abre_casos_y_envia_avisos(self):
        caps = [F.capture(self.w) for _ in range(3)]
        for c in caps:
            ia.enqueue_analysis(c)
        F.recipient("Jefe de fundo")
        with mock.patch("evidencias.nube.download_original", return_value=jpeg(900, 1200)):
            call_command("worker_ia", "--once", "--detector", "simulado", "--sleep", "0")
        self.assertEqual(AiTask.objects.filter(status=AiStatus.INDICIO_SUGERIDO_POR_IA).count(), 3)
        self.assertEqual(Case.objects.count(), 3)
        case = Case.objects.first()
        rv.decide_case(case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias en el racimo")
        call_command("worker_ia", "--once", "--detector", "simulado", "--sleep", "0")  # ConsoleClient en dev
        self.assertEqual(Notification.objects.get().status, NotificationStatus.ENVIADO)

    def test_once_encola_fotos_que_quedaron_sin_tarea(self):
        cap = F.capture(self.w)  # confirmada sin tarea (p. ej. sin modelo activo en ese momento)
        with mock.patch("evidencias.nube.download_original", return_value=jpeg(900, 1200)):
            call_command("worker_ia", "--once", "--detector", "simulado", "--sleep", "0")
        self.assertIn(AiTask.objects.get(capture=cap).status, (AiStatus.SIN_INDICIOS_IA, AiStatus.INDICIO_SUGERIDO_POR_IA))

    def test_simulado_usa_el_tamano_informado_si_no_puede_leer_la_foto(self):
        ia.enqueue_analysis(F.capture(self.w))
        with mock.patch("evidencias.nube.download_original", side_effect=TimeoutError("descarga")), \
                mock.patch("ia.inference.simulado.nube.es_simulado", return_value=False):
            call_command("worker_ia", "--once", "--detector", "simulado", "--sleep", "0")
        task = AiTask.objects.get()
        # el simulado usa el tamaño informado si no puede leer la foto: el análisis termina igual
        self.assertIn(task.status, (AiStatus.SIN_INDICIOS_IA, AiStatus.INDICIO_SUGERIDO_POR_IA))
