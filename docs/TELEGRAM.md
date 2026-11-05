# Avisos por Telegram — cómo activarlos (v1.5, ADR-W-011)

## 1. Crear el bot (5 minutos, desde el celular)
1. En Telegram busca **@BotFather** (tiene la insignia azul) y escribe `/newbot`.
2. Nombre visible: `Riachuelo Alertas`. Usuario (debe terminar en `bot`): por ejemplo `riachuelo_alertas_bot`.
3. BotFather responde con el **token** (`123456789:AA…`). Es una contraseña: no lo compartas ni lo subas a Git.
4. Opcional: `/setuserpic` (logo) y `/setdescription` («Avisos de casos de la plataforma Riachuelo»).

## 2. Poner el token en el VPS
```bash
cd /srv/riachuelo/deploy
nano .env.piloto        # agrega o completa: TELEGRAM_BOT_TOKEN=123456789:AA...
bash actualizar.sh      # reinicia web y worker con el token
docker compose exec web python manage.py telegram estado   # → «Bot listo: @riachuelo_alertas_bot»
```

## 3. Conectar a cada persona (o un grupo)
1. Cada persona abre `https://t.me/<usuario_del_bot>` y pulsa **Iniciar**. Para un grupo: agrega el bot al grupo y
   escribe cualquier mensaje.
2. En el VPS: `docker compose exec web python manage.py telegram chats` → muestra el número de cada chat (los grupos
   empiezan con `-100`). Telegram guarda estos mensajes solo 24 horas: si no sale nadie, que vuelvan a escribirle.
3. Prueba: `docker compose exec web python manage.py telegram prueba <número>`.
4. En la web: **Administración → Destinatarios de avisos** → Nuevo (o Editar): pega el número en «Chat de Telegram»,
   elige los lotes (vacío = todos), marca «Aceptó recibir avisos» y guarda.

## 4. Qué llega
Cuando el especialista confirma un caso, o la IA lo confirma sola con alta confianza: la foto con las cajas de la IA,
lote · hilera · lado, segmento y marcador, fecha, cajas y confianza, y los botones **Ver caso** (pide iniciar sesión)
y **Cómo llegar** (Google Maps, si la foto tiene GPS). El estado de cada aviso se ve en **Avisos** de la web.

## Problemas comunes
- **No llega nada:** `docker compose logs --tail 50 worker` (busca «Telegram»). «HTTP 401»: token mal copiado.
  «HTTP 403»: la persona bloqueó el bot o no pulsó Iniciar. «HTTP 400 chat not found»: número de chat equivocado.
- **Sin foto:** si la foto no se pudo descargar de Cloudinary el aviso sale igual, sin foto. Para mandar siempre solo
  texto: `TELEGRAM_CON_FOTO=false` en `.env.piloto` y `bash actualizar.sh`.
