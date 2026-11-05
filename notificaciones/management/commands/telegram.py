# notificaciones/management/commands/telegram.py — Ayudas para conectar los avisos de Telegram (v1.5, ADR-W-011).
#   python manage.py telegram estado          → comprueba el token y muestra el nombre del bot
#   python manage.py telegram chats           → chats que escribieron al bot (o grupos donde lo agregaron) y su número
#   python manage.py telegram prueba <chat>   → envía un mensaje de prueba a ese chat
# Corre en el servidor (el token nunca va al navegador, W-09). No cambia nada en la base.
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notificaciones.telegram import BotApiClient, Mensaje, TelegramError


class Command(BaseCommand):
    help = "Comprueba el bot de Telegram, lista los chats y envía un mensaje de prueba."

    def add_arguments(self, parser):
        parser.add_argument("accion", choices=["estado", "chats", "prueba"])
        parser.add_argument("chat", nargs="?", help="Número del chat (solo para «prueba»)")

    def handle(self, *args, accion, chat=None, **opts):
        try:
            bot = BotApiClient()
            if accion == "estado":
                yo = bot.get_me()
                self.stdout.write(self.style.SUCCESS(f"Bot listo: @{yo.get('username')} ({yo.get('first_name')})"))
                self.stdout.write(f"Enlace para que cada persona lo inicie: https://t.me/{yo.get('username')}")
            elif accion == "chats":
                self._chats(bot)
            else:
                if not chat:
                    raise CommandError("Indica el número del chat: python manage.py telegram prueba 123456789")
                texto = ("✅ <b>Prueba de la plataforma Riachuelo</b>\nEste chat recibirá los avisos de casos "
                         "confirmados por la IA o por el especialista.")
                link = settings.PUBLIC_BASE_URL.rstrip("/")
                botones = [("Abrir la plataforma", link)] if link.startswith("https://") else []
                mid = bot.send(Mensaje(chat_id=chat, texto=texto, botones=botones))
                self.stdout.write(self.style.SUCCESS(f"Mensaje de prueba enviado (id {mid})."))
        except TelegramError as exc:
            raise CommandError(f"Telegram respondió: {exc}") from None

    def _chats(self, bot):
        vistos = {}
        for u in bot.get_updates():
            m = u.get("message") or u.get("my_chat_member") or {}
            c = m.get("chat") or {}
            if c.get("id") is not None:
                nombre = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
                vistos[c["id"]] = (c.get("type", "?"), nombre or "—", c.get("username") or "")
        if not vistos:
            self.stdout.write(self.style.WARNING(
                "Nadie le escribió al bot todavía. Abre el bot en Telegram, pulsa «Iniciar» (o agrégalo a un grupo y "
                "escribe algo) y vuelve a correr este comando. Telegram guarda estos mensajes solo 24 horas."))
            return
        self.stdout.write("Chat                  Tipo        Nombre")
        for cid, (tipo, nombre, usuario) in vistos.items():
            extra = f" (@{usuario})" if usuario else ""
            self.stdout.write(f"{cid:<21} {tipo:<11} {nombre}{extra}")
        self.stdout.write("Copia el número de la columna «Chat» en Web → Destinatarios de avisos.")
