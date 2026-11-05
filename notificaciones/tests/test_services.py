# notificaciones/tests/test_services.py — Cola de avisos (CU8): encolar en la decisión, enviar con el worker,
# reintentar con espera, error definitivo y arriendo entre workers. v1.5: el canal es Telegram (ADR-W-011).
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from notificaciones import services as notif
from notificaciones.models import Notification, NotificationStatus
from notificaciones.telegram import TelegramError
from revision import services as rv
from revision.models import CaseNotificationStatus, ReviewStatus
from web.tests import factories as F


class FakeClient:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send(self, mensaje):
        if self.fail:
            raise self.fail
        self.sent.append(mensaje)
        return str(len(self.sent))


@override_settings(PUBLIC_BASE_URL="https://riachuelo.example.pe", TELEGRAM_CON_FOTO=False)
class ColaDeAvisos(TestCase):
    def setUp(self):
        self.w = F.world()
        _, _, self.case = F.analyzed(self.w)
        F.recipient("Jefe de fundo", telegram_chat_id="123456789")
        rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias")
        self.n = Notification.objects.get()

    def test_se_encola_por_telegram(self):
        self.assertEqual((self.n.channel, self.n.recipient_chat), ("TELEGRAM", "123456789"))

    def test_mensaje_con_ubicacion_y_enlace_al_caso(self):
        m = notif.build_telegram_message(self.n)
        self.assertIn("hilera <b>5</b>", m.texto)
        self.assertIn("segmento SWG 1-S1 · marcador M1", m.texto)
        self.assertEqual(m.botones[0][1], f"https://riachuelo.example.pe/casos/{self.case.pk}/")

    def test_envio_exitoso(self):
        client = FakeClient()
        self.assertEqual(notif.process_pending_notifications(client, "w1"), 1)
        self.n.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual((self.n.status, self.n.provider_message_id, self.n.attempts), (NotificationStatus.ENVIADO, "1", 1))
        self.assertEqual(self.case.notification_status, CaseNotificationStatus.ENVIADO)
        self.assertEqual(notif.process_pending_notifications(client, "w1"), 0)  # no se reenvía

    def test_error_temporal_reintenta_con_espera_y_luego_falla(self):
        client = FakeClient(fail=TelegramError("HTTP 503"))
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
        notif.process_pending_notifications(FakeClient(fail=TelegramError("HTTP 403", retryable=False)), "w1")
        self.n.refresh_from_db()
        self.assertEqual((self.n.status, self.n.attempts), (NotificationStatus.ERROR_ENVIO, 1))

    def test_aviso_tomado_no_lo_toma_otro_worker(self):
        self.assertIsNotNone(notif.claim_next_notification("w1"))
        self.assertIsNone(notif.claim_next_notification("w2"))  # arrendado (locked_until)

    def test_avisos_antiguos_de_whatsapp_no_se_envian(self):
        Notification.objects.update(channel="WHATSAPP")
        self.assertIsNone(notif.claim_next_notification("w1"))

    def test_sin_token_el_worker_no_tiene_cliente(self):
        with override_settings(TELEGRAM_CLIENT="notificaciones.telegram.BotApiClient", TELEGRAM_BOT_TOKEN=""):
            self.assertIsNone(notif.cliente_de_aviso())
        with mock.patch("notificaciones.telegram.get_client", return_value=FakeClient()):
            self.assertIsInstance(notif.cliente_de_aviso(), FakeClient)
