# notificaciones/telegram.py — Avisos por Telegram (v1.5, ADR-W-011). Lo usa solo el worker (la web nunca llama a
# Telegram). En desarrollo ConsoleClient escribe en la consola cómo quedaría el mensaje; con TELEGRAM_BOT_TOKEN se usa
# BotApiClient: Bot API oficial (https://api.telegram.org/bot<token>/sendPhoto o sendMessage).
#
# El mensaje lleva la foto del caso con las cajas de la IA dibujadas, el lugar (lote, hilera, lado, segmento,
# marcador), la fecha y los botones «Ver caso» (abre la web con inicio de sesión) y «Cómo llegar» (si hay GPS).
import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.utils.module_loading import import_string

from notificaciones.errores import AvisoError

log = logging.getLogger("riachuelo.telegram")

API = "https://api.telegram.org"
MAX_CAPTION = 1024  # límite de Telegram para el texto de una foto
MAX_TEXT = 4096  # límite de Telegram para un mensaje de texto


class TelegramError(AvisoError):
    pass


@dataclass
class Mensaje:
    chat_id: str
    texto: str  # HTML de Telegram: <b>, <i>, <a href>
    botones: list = field(default_factory=list)  # [(texto, url https)]
    foto: bytes | None = None
    nombre_foto: str = "caso.jpg"


def texto_plano(html):
    return re.sub(r"<[^>]+>", "", html).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class ConsoleClient:
    """Desarrollo: no envía nada; muestra en la consola del worker cómo quedaría el mensaje."""

    def send(self, m):
        foto = f" con foto ({len(m.foto) // 1024} KB)" if m.foto else " (sin foto)"
        cuerpo = texto_plano(m.texto).replace("\n", "\n      │ ")
        botones = "".join(f"\n      │ [{t}] {u}" for t, u in m.botones)
        log.info("Telegram (SIMULADO, no se envía) al chat %s%s:\n      │ %s%s", m.chat_id, foto, cuerpo, botones)
        return f"console-{uuid.uuid4()}"


class BotApiClient:
    """Bot API de Telegram. El token lo da @BotFather y vive solo en el servidor (W-09)."""

    def __init__(self, token=None, timeout=None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.timeout = timeout or settings.TELEGRAM_TIMEOUT
        if not self.token:
            raise TelegramError("Falta TELEGRAM_BOT_TOKEN", retryable=False)

    def _limpio(self, texto):
        return str(texto).replace(self.token, "<token>")  # el token nunca va a la consola ni a la base

    def _post(self, metodo, data=None, files=None):
        import requests

        try:
            resp = requests.post(f"{API}/bot{self.token}/{metodo}", data=data or {}, files=files, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TelegramError(f"Red: {self._limpio(exc)[:300]}") from None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 429 or resp.status_code >= 500:
            espera = (body.get("parameters") or {}).get("retry_after")
            raise TelegramError(f"HTTP {resp.status_code}: {body.get('description', '')}"
                                + (f" (esperar {espera} s)" if espera else ""))
        if resp.status_code >= 400 or not body.get("ok"):
            # 400 chat inexistente o texto inválido, 401 token inválido, 403 el bot fue bloqueado: no se reintenta.
            raise TelegramError(f"HTTP {resp.status_code}: {self._limpio(body.get('description') or resp.text[:200])}",
                                retryable=False)
        return body["result"]

    def send(self, m):
        data = {"chat_id": m.chat_id, "parse_mode": "HTML"}
        if m.botones:
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "url": u}] for t, u in m.botones]})
        if m.foto:
            data["caption"] = m.texto[:MAX_CAPTION]
            r = self._post("sendPhoto", data, files={"photo": (m.nombre_foto, m.foto, "image/jpeg")})
        else:
            data.update(text=m.texto[:MAX_TEXT], link_preview_options=json.dumps({"is_disabled": True}))
            r = self._post("sendMessage", data)
        return str(r["message_id"])

    # --------------------------------------------------------------- ayudas del comando `python manage.py telegram`
    def get_me(self):
        return self._post("getMe")

    def get_updates(self):
        return self._post("getUpdates", {"allowed_updates": json.dumps(["message", "my_chat_member"])})


def get_client():
    return import_string(settings.TELEGRAM_CLIENT)()
