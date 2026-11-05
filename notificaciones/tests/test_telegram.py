# notificaciones/tests/test_telegram.py — v1.5 (ADR-W-011): avisos por Telegram (canal por destinatario, mensaje con
# lugar, botones y foto con cajas, clasificación de errores de la Bot API y formulario de destinatarios).
import io
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from notificaciones import services as notif
from notificaciones.models import Notification, NotificationStatus
from notificaciones.telegram import BotApiClient, ConsoleClient, Mensaje, TelegramError
from revision import services as rv
from revision.models import ReviewStatus
from web.forms import RecipientForm
from web.tests import factories as F

ALTA = dict(F.BOX, confidence=0.91)


class FakeTelegram:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send(self, m):
        if self.fail:
            raise self.fail
        self.sent.append(m)
        return str(len(self.sent))


def jpeg(w=3000, h=4000):
    out = io.BytesIO()
    Image.new("RGB", (w, h), (40, 120, 60)).save(out, "JPEG")
    return out.getvalue()


@override_settings(PUBLIC_BASE_URL="https://monitoreo.ejemplo.pe", TELEGRAM_CON_FOTO=True)
class AvisosTelegram(TestCase):
    def setUp(self):
        self.w = F.world()
        _, _, self.case = F.analyzed(self.w)
        self.jefe = F.recipient("Jefe de fundo", phone="", telegram_chat_id="123456789")
        F.recipient("Solo WhatsApp", phone="+51987654321")
        rv.decide_case(self.case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias en el envés")

    def test_canal_por_destinatario(self):
        tg = Notification.objects.get(recipient=self.jefe)
        self.assertEqual((tg.channel, tg.recipient_chat, tg.recipient_phone), ("TELEGRAM", "123456789", ""))
        self.assertEqual(Notification.objects.exclude(pk=tg.pk).get().channel, "WHATSAPP")

    def test_mensaje_con_lugar_observacion_y_botones(self):
        m = notif.build_telegram_message(Notification.objects.get(recipient=self.jefe))
        self.assertIn("Caso confirmado por el especialista", m.texto)
        self.assertIn("Lote <b>SWG 1</b> · hilera <b>5</b>", m.texto)
        self.assertIn("Colonias en el envés", m.texto)
        self.assertIn("máx. 0,81", m.texto)  # coma decimal para personas (W-16)
        self.assertEqual(m.botones[0], ("Ver caso", f"https://monitoreo.ejemplo.pe/casos/{self.case.pk}/"))
        self.assertEqual(m.chat_id, "123456789")

    @override_settings(PUBLIC_BASE_URL="http://127.0.0.1:8000")
    def test_sin_https_el_enlace_va_en_el_texto(self):
        m = notif.build_telegram_message(Notification.objects.get(recipient=self.jefe))
        self.assertEqual(m.botones, [])
        self.assertIn("http://127.0.0.1:8000/casos/", m.texto)

    def test_envio_por_cada_canal_con_foto(self):
        tg, wa = FakeTelegram(), mock.Mock(send=mock.Mock(return_value="wamid.1"))
        with mock.patch("notificaciones.services.foto_para_aviso", return_value=b"jpeg"):
            enviados = notif.process_pending_notifications({"TELEGRAM": tg, "WHATSAPP": wa}, "w1")
        self.assertEqual(enviados, 2)
        self.assertEqual(tg.sent[0].foto, b"jpeg")
        self.assertEqual(wa.send.call_count, 1)
        self.assertFalse(Notification.objects.exclude(status=NotificationStatus.ENVIADO).exists())

    def test_sin_foto_igual_se_envia(self):
        tg = FakeTelegram()
        with mock.patch("notificaciones.services.foto_para_aviso", side_effect=OSError("nube caída")):
            notif.process_pending_notifications({"TELEGRAM": tg}, "w1")
        self.assertIsNone(tg.sent[0].foto)
        self.assertEqual(Notification.objects.get(recipient=self.jefe).status, NotificationStatus.ENVIADO)

    def test_canal_sin_cliente_espera_en_la_cola(self):
        notif.process_pending_notifications({"WHATSAPP": mock.Mock(send=mock.Mock(return_value="x"))}, "w1")
        self.assertEqual(Notification.objects.get(recipient=self.jefe).status, NotificationStatus.PENDIENTE_ENVIO)

    def test_error_definitivo_de_telegram(self):
        notif.process_pending_notifications({"TELEGRAM": FakeTelegram(fail=TelegramError("HTTP 403", retryable=False))},
                                            "w1")
        self.assertEqual(Notification.objects.get(recipient=self.jefe).status, NotificationStatus.ERROR_ENVIO)

    def test_foto_con_cajas_reducida(self):
        with mock.patch("evidencias.nube.download_original", return_value=jpeg()):
            data = notif.foto_para_aviso(self.case, ancho=800)
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "JPEG")
        self.assertLessEqual(max(img.size), 800)
        # la caja (100,200)-(400,520) sobre 3000 px queda en (20,40)-(80,104) a 600 px: su borde superior es amarillo
        self.assertTrue(any(img.getpixel((50, y))[0] > 200 and img.getpixel((50, y))[2] < 120 for y in range(37, 45)))
        self.assertLess(img.getpixel((50, 70))[0], 120)  # dentro de la caja se ve la foto

    def test_consola_no_envia(self):
        self.assertTrue(ConsoleClient().send(Mensaje(chat_id="1", texto="<b>Hola</b>")).startswith("console-"))


@override_settings(PUBLIC_BASE_URL="https://monitoreo.ejemplo.pe")
class AlertaIaPorTelegram(TestCase):
    def test_texto_de_la_ia_no_diagnostica(self):
        w = F.world()
        w.model.auto_confirm_threshold = 0.75
        w.model.save(update_fields=["auto_confirm_threshold"])
        F.recipient("Jefe", phone="", telegram_chat_id="-1001234567890")
        _, _, case = F.analyzed(w, boxes=(ALTA,))
        m = notif.build_telegram_message(Notification.objects.get(case=case))
        self.assertIn("la IA sugiere indicios", m.texto)
        self.assertNotIn("diagnóstico", m.texto.lower())
        self.assertEqual(m.chat_id, "-1001234567890")


@override_settings(TELEGRAM_BOT_TOKEN="123:SECRETO", TELEGRAM_TIMEOUT=5)
class ClienteBotApi(TestCase):
    def test_clasifica_errores_y_oculta_el_token(self):
        cli = BotApiClient()
        for code, retryable in ((429, True), (502, True), (400, False), (401, False), (403, False)):
            resp = mock.Mock(status_code=code, json=lambda c=code: {"ok": False, "description": f"error {c} 123:SECRETO"})
            with mock.patch("requests.post", return_value=resp):
                with self.assertRaises(TelegramError) as ctx:
                    cli.send(Mensaje(chat_id="1", texto="x"))
            self.assertEqual(ctx.exception.retryable, retryable, code)
            if not retryable:
                self.assertNotIn("SECRETO", str(ctx.exception))

    def test_foto_va_por_sendphoto_y_texto_por_sendmessage(self):
        ok = mock.Mock(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 77}})
        with mock.patch("requests.post", return_value=ok) as post:
            self.assertEqual(BotApiClient().send(Mensaje(chat_id="1", texto="x", foto=b"j",
                                                         botones=[("Ver caso", "https://x")])), "77")
            self.assertTrue(post.call_args.args[0].endswith("/sendPhoto"))
            self.assertIn("photo", post.call_args.kwargs["files"])
            BotApiClient().send(Mensaje(chat_id="1", texto="x"))
            self.assertTrue(post.call_args.args[0].endswith("/sendMessage"))

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_sin_token_no_arranca(self):
        with self.assertRaises(TelegramError):
            BotApiClient()


class FormularioDestinatario(TestCase):
    def test_pide_telegram_o_celular(self):
        base = {"full_name": "Ana", "role_label": "JEFE_FUNDO", "active": True}
        self.assertFalse(RecipientForm(base).is_valid())
        self.assertTrue(RecipientForm({**base, "telegram_chat_id": "123456789"}).is_valid())
        self.assertFalse(RecipientForm({**base, "telegram_chat_id": "abc"}).is_valid())
        self.assertTrue(RecipientForm({**base, "phone_e164": "+51987654321"}).is_valid())
