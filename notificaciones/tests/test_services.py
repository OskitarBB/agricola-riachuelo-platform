from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from notificaciones import services as notif
from notificaciones.models import Notification, NotificationStatus
from notificaciones.whatsapp import CloudApiClient, WhatsAppError
from revision import services as rv
from revision.models import CaseNotificationStatus, ReviewStatus
from web.tests import factories as F


class FakeClient:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send(self, payload):
        if self.fail:
            raise self.fail
        self.sent.append(payload)
        return f"wamid.{len(self.sent)}"


@override_settings(PUBLIC_BASE_URL="https://riachuelo.example.pe", WHATSAPP_TEMPLATE="caso_confirmado",
                   WHATSAPP_TEMPLATE_LANG="es")
class AvisosWhatsApp(TestCase):
    def setUp(self):
        self.w = F.world()
        _, _, self.case = F.analyzed(self.w)
        F.recipient("Jefe de fundo", phone="+51987654321")
        rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias")
        self.n = Notification.objects.get()

    def test_plantilla_con_ubicacion_y_enlace_al_caso(self):
        p = notif.build_whatsapp_payload(self.n)
        self.assertEqual(p["to"], "51987654321")
        self.assertEqual(p["type"], "template")
        self.assertEqual(p["template"]["name"], "caso_confirmado")
        params = [x["text"] for x in p["template"]["components"][0]["parameters"]]
        self.assertEqual(params[:4], ["SWG 1", "5", "Lateral A", "segmento SWG 1-S1 · marcador M1"])
        self.assertEqual(params[5], f"https://riachuelo.example.pe/casos/{self.case.pk}/")
        self.assertTrue(all("\n" not in t and "\t" not in t for t in params))
        self.assertNotIn("cloudinary", str(p))  # nunca la imagen: solo el enlace al caso (requiere login)

    def test_envio_exitoso(self):
        client = FakeClient()
        self.assertEqual(notif.process_pending_notifications(client, "w1"), 1)
        self.n.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual((self.n.status, self.n.provider_message_id, self.n.attempts),
                         (NotificationStatus.ENVIADO, "wamid.1", 1))
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.ENVIADO)
        self.assertEqual(notif.process_pending_notifications(client, "w1"), 0)  # no se reenvía

    def test_error_temporal_reintenta_con_espera_y_luego_falla(self):
        client = FakeClient(fail=WhatsAppError("HTTP 503"))
        notif.process_pending_notifications(client, "w1")
        self.n.refresh_from_db()
        self.assertEqual((self.n.status, self.n.attempts), (NotificationStatus.PENDIENTE_ENVIO, 1))
        self.assertGreater(self.n.available_at, timezone.now())
        for _ in range(notif.MAX_ATTEMPTS):
            Notification.objects.update(available_at=timezone.now() - timedelta(seconds=1))
            notif.process_pending_notifications(client, "w1")
        self.n.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual((self.n.status, self.n.attempts), (NotificationStatus.ERROR_ENVIO, notif.MAX_ATTEMPTS))
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.ERROR_ENVIO)
        self.assertEqual(self.case.status, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA)  # la decisión no cambia

    def test_error_definitivo_no_reintenta(self):
        notif.process_pending_notifications(FakeClient(fail=WhatsAppError("HTTP 400", retryable=False)), "w1")
        self.n.refresh_from_db()
        self.assertEqual((self.n.status, self.n.attempts), (NotificationStatus.ERROR_ENVIO, 1))

    def test_aviso_tomado_no_lo_toma_otro_worker(self):
        self.assertIsNotNone(notif.claim_next_notification("w1"))
        self.assertIsNone(notif.claim_next_notification("w2"))  # arrendado (locked_until)

    @override_settings(WHATSAPP_TOKEN="t", WHATSAPP_PHONE_ID="123", WHATSAPP_GRAPH_VERSION="v99.0")
    def test_cliente_cloud_api_clasifica_errores(self):
        client = CloudApiClient()
        for code, retryable in ((429, True), (503, True), (400, False), (401, False)):
            resp = mock.Mock(status_code=code, text="{}")
            with mock.patch("requests.post", return_value=resp):
                with self.assertRaises(WhatsAppError) as ctx:
                    client.send({"to": "51"})
            self.assertEqual(ctx.exception.retryable, retryable, code)
        ok = mock.Mock(status_code=200, json=lambda: {"messages": [{"id": "wamid.X"}]})
        with mock.patch("requests.post", return_value=ok) as post:
            self.assertEqual(client.send({"to": "51"}), "wamid.X")
        self.assertEqual(post.call_args.args[0], "https://graph.facebook.com/v99.0/123/messages")
