# ADR-W-011 — Avisos por Telegram con foto, texto y enlace

05/11/2026 · Estado: aceptada por Oscar · Autor: Claude (asistente de desarrollo)

**Contexto.** Los avisos de casos confirmados (por el especialista o por la IA con alta confianza, ADR-W-007) estaban
hechos para WhatsApp Cloud API, que exige cuenta de empresa en Meta, número verificado y plantillas aprobadas
(Q-W08). Eso no avanzó. Telegram ofrece una Bot API gratuita que se activa en minutos con @BotFather.

**Decisión.**

1. **Solo Telegram:** `notification_recipients.telegram_chat_id` es obligatorio y el celular queda solo como dato de
   contacto. Se retiró el cliente de WhatsApp (`notificaciones/whatsapp.py`, variables `WHATSAPP_*`). La migración
   `notificaciones/0005` pasa a Telegram los avisos de WhatsApp que seguían pendientes (o los anula si el destinatario
   no tiene chat); los ya enviados quedan como historial.
   `notifications.channel` guarda el canal y `recipient_chat` copia el chat al encolar (auditoría). Migración
   aditiva `notificaciones/0004`.
2. **Mensaje:** foto del caso con las cajas de la IA dibujadas (la descarga el worker del original firmado, la reduce a
   1600 px y no la guarda: W-10), lugar (lote, hilera, lado, segmento, marcador), fecha, cajas y confianza máxima, la
   observación del especialista y los botones «Ver caso» (la web, con inicio de sesión) y «Cómo llegar» (si hay GPS).
   El texto de la IA dice «sugiere indicios» (W-11). Si la foto falla, el aviso sale igual sin foto.
3. **Cambio respecto de DW-26:** antes el aviso nunca llevaba la foto. Oscar decidió que en Telegram sí la lleve
   (más práctico en campo). Se puede volver a solo texto con `TELEGRAM_CON_FOTO=false`.
4. **Envío:** solo el worker (la web nunca llama a Telegram). Errores 429/5xx/red se reintentan con espera;
   400/401/403 (chat inexistente, token inválido, bot bloqueado) quedan en «Error de envío». El token nunca se escribe
   en la consola ni en la base. `ConsoleClient` en desarrollo o sin token.
5. **Ayudas:** `python manage.py telegram estado | chats | prueba <chat>`; checks `riachuelo.W007` y `riachuelo.W010`.

**Consecuencias.** Las fotos de los casos confirmados quedan en los chats o grupos de Telegram de los destinatarios.
Guía de uso: `docs/TELEGRAM.md`.
