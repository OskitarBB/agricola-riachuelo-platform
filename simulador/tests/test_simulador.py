# simulador/tests/test_simulador.py — Flujo completo de la app contra la laptop sin Cloudinary real (solo APP_ENV=dev):
# login → sesión → pasada → secuencia → ticket → subida al Cloudinary simulado → confirmación → worker → caso.
import hashlib
import io
import json
import shutil
import tempfile
import uuid
from unittest import skipUnless

from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import NoReverseMatch, reverse
from PIL import Image
from rest_framework.test import APIClient

from api.tests.test_api import API, Base, SyncMixin
from evidencias import nube
from evidencias.models import Capture
from revision.models import Case
from ia.models import AiStatus, AiTask


def _simulador_montado():
    try:
        reverse("simulador:subir", args=["x"])
        return True
    except NoReverseMatch:
        return False


def jpeg(w=600, h=800, color=(60, 120, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=85)
    return buf.getvalue()


@skipUnless(_simulador_montado(), "Las rutas /dev/ solo existen con APP_ENV=dev")
class CloudinarySimulado(SyncMixin, Base):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="riachuelo-media-")
        self.ajustes = override_settings(CLOUDINARY_URL="", APP_ENV="dev", MEDIA_ROOT=self.media)
        self.ajustes.enable()
        nube.configurar()
        self.assertEqual(nube.modo(), nube.SIMULADO)
        super().setUp()
        self.preparar_ids()

    def tearDown(self):
        self.ajustes.disable()
        nube.configurar()  # vuelve al modo de las pruebas (Cloudinary «real» con credenciales ficticias)
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def subir(self, ticket, data):
        url = ticket["url"].replace("http://testserver", "")
        return Client().post(url, {**ticket["fields"], "file": io.BytesIO(data)}, format="multipart")

    def test_flujo_completo_en_la_laptop(self):
        self.preparar()
        data = jpeg()
        md5 = hashlib.md5(data).hexdigest()
        r = self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(len(data), md5), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        ticket = r.json()["upload"]
        self.assertIn("/dev/cloudinary/v1_1/riachuelo-simulado/image/upload", ticket["url"])

        r = self.subir(ticket, data)
        self.assertEqual(r.status_code, 200, r.content)
        res = r.json()
        self.assertEqual((res["public_id"], res["bytes"], res["width"]), (ticket["publicId"], len(data), 600))

        cloud = {"publicId": res["public_id"], "version": res["version"], "signature": res["signature"],
                 "bytes": res["bytes"], "format": res["format"], "width": res["width"], "height": res["height"],
                 "etag": res["etag"]}
        r = self.c.post(f"{API}/captures/upload", {"metadata": self.metadata(len(data), md5), "cloudinary": cloud},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)

        with override_settings(IA_SIMULADO_PROBABILIDAD=1.0):  # fuerza un indicio para ver el caso en la bandeja
            call_command("worker_ia", "--once", "--detector", "simulado", "--sleep", "0")
        task = AiTask.objects.get(capture_id=self.cid)
        self.assertEqual(task.status, AiStatus.INDICIO_SUGERIDO_POR_IA)
        self.assertEqual((task.image_width, task.image_height), (600, 800))  # tamaño real de la foto subida
        case = Case.objects.get(capture_id=self.cid)

        web = Client()
        web.force_login(self.w.esp)
        r = web.get(reverse("web:caso", args=[case.pk]))
        self.assertContains(r, "/dev/media/revision/")
        foto = web.get(nube.signed_image_url(case.capture, "miniatura"))
        self.assertEqual((foto.status_code, foto["Content-Type"], foto["X-Foto-Demo"]), (200, "image/jpeg", "0"))
        self.assertEqual(Image.open(io.BytesIO(foto.content)).width, 400)  # c_limit,w_400 de «miniatura»

    def test_subida_con_firma_alterada_o_sin_archivo(self):
        self.preparar()
        data = jpeg()
        r = self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(len(data), "b" * 32), format="json")
        ticket = r.json()["upload"]
        malo = dict(ticket, fields=dict(ticket["fields"], public_id=ticket["publicId"] + "x"))
        self.assertEqual(self.subir(malo, data).status_code, 401)
        r = Client().post(ticket["url"].replace("http://testserver", ""), ticket["fields"])
        self.assertEqual(r.status_code, 400)

    def test_overwrite_false_devuelve_el_recurso_existente(self):
        self.preparar()
        data = jpeg()
        ticket = self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(len(data), "c" * 32),
                             format="json").json()["upload"]
        primero = self.subir(ticket, data).json()
        segundo = self.subir(ticket, jpeg(color=(200, 0, 0))).json()
        self.assertEqual((segundo["version"], segundo["existing"]), (primero["version"], True))

    def test_fotos_exigen_sesion_de_la_web(self):
        url = reverse("simulador:foto", args=["miniatura", "riachuelo/dev/x/y/z"])
        self.assertEqual(Client().get(url).status_code, 403)
        op = Client()
        op.force_login(self.w.op)  # el operador no usa la web
        self.assertEqual(op.get(url).status_code, 403)
        esp = Client()
        esp.force_login(self.w.esp)
        r = esp.get(url)
        self.assertEqual((r.status_code, r["X-Foto-Demo"]), (200, "1"))  # sin archivo: foto de demostración

    def test_no_existe_con_cloudinary_real(self):
        with override_settings(CLOUDINARY_URL="cloudinary://123456789012345:secreto@nube-real"):
            nube.configurar()
            r = APIClient().post(reverse("simulador:subir", args=["riachuelo-simulado"]), {})
            self.assertEqual(r.status_code, 404)
        nube.configurar()

    def test_app_v1_sube_por_multipart_a_la_laptop(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.preparar()
        data = jpeg(480, 640)
        meta = self.metadata(len(data), hashlib.md5(data).hexdigest())
        r = self.c.post(f"{API}/captures/upload", {"metadata": json.dumps(meta),
                                                  "file": SimpleUploadedFile("f.jpg", data, "image/jpeg")},
                        format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        cap = Capture.objects.get(pk=self.cid)
        self.assertTrue(nube.ruta_simulada(cap.cloudinary_public_id).exists())
        self.assertEqual((cap.cloudinary_width, cap.cloudinary_height), (480, 640))

