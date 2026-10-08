# Contexto completo de la plataforma web Riachuelo (estado al 08/10/2026)

Documento de traspaso para continuar el trabajo en otro chat. Describe lo que ya está hecho, lo que se usa, lo que está funcionando en producción, cómo se hacen y se publican los cambios, y todo lo que falta. Está escrito para que alguien (persona o IA) sin historial previo pueda retomar el proyecto sin preguntar nada.

Proyecto de Claude asociado: "integrador II". Documentos relacionados en el proyecto: claude/CONTEXTO_SISTEMA_2026-10-08.md (estado de la app móvil), claude/HANDOFF_APP_MOVIL.md, claude/HANDOFF_CATALOGOS_WEB.md, claude/DESPLIEGUE_VPS.md, claude/REPORTE_AVANCE_WEB.md, claude/ARQUITECTURA_DATOS.md, MAESTRO_WEB_v1.0.pdf, MAESTRO_APP_MOVIL_v2.0.pdf, Curso Integrador II.pdf.


## 1. Qué es el sistema

Plataforma de monitoreo fitosanitario para el fundo de Agrícola Riachuelo (Chincha, Ica, Perú). Tiene tres piezas:

1. App móvil (Expo / React Native, Android). La usan los operadores de campo. Recorren las hileras de los lotes con hasta 3 celulares (cámaras), toman fotos de ambos laterales de cada hilera (LATERAL_A y LATERAL_B), miden la calidad de la foto en el propio celular, guardan todo sin internet en SQLite local y después sincronizan con el servidor.
2. Plataforma web (Django). La usan especialistas fitosanitarios, supervisores y administradores. Muestra los casos (fotos con indicios sugeridos por la IA), permite al especialista confirmar, marcar evidencia insuficiente o descartar, muestra el mapa, el plano de hileras, las sesiones de monitoreo, reportes, auditoría, y permite administrar cuentas, celulares, destinatarios de avisos y catálogos del fundo.
3. Worker de IA (proceso Django aparte, python manage.py worker_ia). Toma las fotos de una cola en la base de datos, las analiza con el modelo YOLO (exportado a ONNX), guarda las cajas detectadas y abre casos de revisión. También envía los avisos de WhatsApp después de que el especialista confirma un caso.

La misma aplicación Django sirve la web (HTML con HTMX) y la API REST /api/v1 que consume la app móvil.

Principios del dominio que no cambian:

- La IA solo "sugiere indicios". Nunca diagnostica. La decisión final siempre es del especialista humano.
- Los colores en la web indican el estado de revisión del caso, nunca la gravedad.
- Toda acción importante queda en la auditoría (tabla audit_events, solo inserción).
- La app nunca tiene credenciales de Supabase, Cloudinary ni WhatsApp. Solo habla con Django.


## 2. Situación actual de la web (resumen de estado)

En producción y funcionando:

- URL pública: https://monitoreo.agricolariachuelo.org
- Certificado HTTPS de Let's Encrypt emitido y con renovación automática (lo maneja Traefik).
- Base de datos: Supabase PostgreSQL, proyecto riachuelo-piloto (región São Paulo, sa-east-1, plan Free), sin datos de demostración.
- Fotos: Cloudinary (cloud wd9meyw0), clave API dedicada al piloto, prefijo de carpetas "piloto".
- Contenedores Docker en un VPS de Hostinger: riachuelo-web-1 (web + API) y riachuelo-worker-1 (worker de IA y avisos).
- Cuenta de administrador creada (con createsuperuser).
- Catálogo piloto cargado: lotes SWG1 (31 hileras), SWG2 (16 hileras), SWG5 (36 hileras), total 83 hileras. Cada hilera tiene un segmento "-S1" llamado "Hxx completa" y marcadores "-INI" y "-FIN". Ninguno tiene coordenadas todavía. Se cargaron con un script ejecutado por SSH el 07/10.
- Versiones de la web entregadas: v1.0 (web completa según el Maestro Web), v1.1 (alta de cuentas "Nueva cuenta" y reglas de tipos de cuenta, ADR-W-005), v1.2 (gestión de catálogos desde la web, ADR-W-006).
- 170 pruebas automáticas pasan.

Funciona pero en modo provisional:

- IA: no hay modelo YOLO entrenado. El worker está corriendo pero no analiza fotos; las fotos que lleguen quedan esperando y se analizarán solas cuando se active el modelo.
- WhatsApp: en modo consola (ConsoleClient). Los avisos no se envían; se escriben en el log del worker.
- Mapa: funciona técnicamente (Leaflet + OpenStreetMap), pero no hay ubicaciones reales cargadas: los lotes no tienen contorno, los marcadores no tienen coordenadas y las hileras/segmentos no tienen posición geográfica. Ver sección 12.
- Subida de fotos: está habilitada la subida por ticket v2.0 (la que usa la app 0.4.x) y también la compatibilidad multipart v1 (API_SUBIDA_MULTIPART=true), que se debe apagar cuando se confirme que la app solo usa el ticket.

Pendiente por confirmar:

- Que la versión v1.2 (catálogos) ya esté subida a GitHub y aplicada en el VPS. Si no se hizo, seguir la sección 5 (git add, commit, push y luego en el VPS git pull y actualizar.sh). La migración campo/0003_catalogo_activo se aplica sola al arrancar el contenedor web.
- Sincronización real de la app con el servidor en campo (la fase 4 de sincronización de la app está hecha, pero falta la prueba real en el fundo).


## 3. Tecnología y versiones

Servidor (requirements.txt, versiones comprobadas el 03 y 04/10/2026):

- Python 3.12 (imagen Docker python:3.12-slim-bookworm). En local se acepta Python 3.10 a 3.14.
- Django 5.2.17 (LTS). No subir a Django 6.x mientras djangorestframework-simplejwt no declare soporte.
- djangorestframework 3.18.1
- djangorestframework-simplejwt 5.5.1 (access 15 minutos, refresh 14 días, rotación de refresh y lista negra de tokens revocados)
- drf-spectacular 0.30.0 (esquema OpenAPI en /api/v1/schema)
- django-htmx 1.29.0
- whitenoise 6.12.0 (estáticos con hash y comprimidos, CompressedManifest)
- cloudinary 1.46.2 (SDK de Python)
- psycopg[binary] 3.3.6 (PostgreSQL)
- gunicorn 26.2.0 (solo Linux)
- django-environ 0.14.0 (lee .env)
- requests 2.34.2
- Pillow 12.3.0 (orientación EXIF y tamaño de la foto analizada)

Dependencias de IA (requirements-ia.txt, ya instaladas dentro de la imagen Docker porque INSTALAR_IA=1):

- numpy >= 2.0
- onnxruntime >= 1.20
- ultralytics >= 8.3 está comentado; solo se usaría con IA_DETECTOR=yolo (licencia AGPL-3.0).

Navegador (sin CDN, sin npm, sin frameworks de JavaScript, regla W-01):

- HTMX 2.0.11, copiado en web/static/web/vendor/
- Leaflet 1.9.4, copiado en web/static/web/vendor/ (se le quitó la línea sourceMappingURL porque rompía collectstatic)
- Íconos Lucide en un sprite SVG (web/static/web/iconos.svg)
- Fuente Inter servida localmente (web/static/web/fuentes/)
- Sonidos de aviso (web/static/web/sonidos/) y animaciones en CSS
- JavaScript propio: app.js (general, avisos, confirmaciones, vistas previas de catálogos), caso.js (visor de la foto con cajas), mapa.js (mapa)
- Estilos: app.css (diseño responsivo)

Idioma y hora: LANGUAGE_CODE es-pe, TIME_ZONE America/Lima (se guarda en UTC y se muestra en hora de Lima).

Servicios externos:

- Supabase: solo PostgreSQL gestionado. No se usan Data API (PostgREST), GraphQL, Supabase Auth, Storage, Realtime ni Queues.
- Cloudinary: almacenamiento y entrega de fotos.
- Meta WhatsApp Cloud API: pendiente.
- OpenStreetMap: teselas del mapa (tile.openstreetmap.org).
- Hostinger: dominio y VPS.
- GitHub: repositorio del código.
- Let's Encrypt: certificado HTTPS (vía Traefik).


## 4. Estructura del repositorio

Repositorio GitHub: OskitarBB/agricola-riachuelo-platform (público). Rama de trabajo: prueba2. El compañero de equipo creó el repositorio; Oscar es colaborador.

Carpeta local en la PC de Oscar: C:\Users\oscos\Videos\agricola-riachuelo-platform

Carpeta en el VPS: /srv/riachuelo (clon del repositorio, permisos 700).

Contenido de la raíz:

- AGENTS.md y CLAUDE.md: instrucciones para agentes de IA (leer el Maestro Web, reglas W-01 a W-24, qué ejecutar al terminar).
- README.md
- Dockerfile y .dockerignore: imagen única para web y worker.
- manage.py
- iniciar.bat: arranque local en Windows (llama a scripts/iniciar.ps1).
- requirements.txt y requirements-ia.txt
- .env.example: plantilla de variables para desarrollo local.
- .gitignore: excluye .env, db.sqlite3, media/, staticfiles/, .venv/, .vscode/, *.log, pesos de IA (*.pt, *.onnx, ia/inference/weights/*), respaldos/.
- riachuelo-plataforma.tar.gz: paquete viejo del primer despliegue (antes de usar git en el VPS). Ya no se usa.

Aplicaciones Django:

- config/: settings.py, urls.py, wsgi.py, asgi.py, restricciones.py (genera los CHECK de estados en la base).
- cuentas/: usuarios, roles, celulares (devices), solicitudes de restablecimiento de contraseña. services.py tiene validate_roles, account_kind y create_account (v1.1). validators.py.
- campo/: catálogos del fundo (lotes, hileras, segmentos, marcadores, perfiles de calidad). services.py (v1.2) tiene toda la lógica de gestión de catálogos.
- monitoreo/: sesiones de monitoreo, celulares de la sesión, pasadas, cambios de marcador, secuencias de captura, incidencias.
- evidencias/: capturas (metadatos de foto en Cloudinary) y resultados de calidad. services.py confirma la subida y encola el análisis.
- ia/: configuración de modelos, cola de tareas, detecciones. ia/inference/ tiene onnx.py, yolo.py, simulado.py y weights/LEEME.md. management/commands/worker_ia.py es el worker.
- revision/: casos de revisión y decisiones humanas. services.py calcula la ubicación del caso (case_location).
- notificaciones/: destinatarios, lotes por destinatario, avisos; cliente de WhatsApp (ConsoleClient y CloudApiClient).
- auditoria/: audit_events y seguridad_bd.py (RLS y REVOKE después de cada migrate).
- api/: API REST. api/v1/urls.py, views.py, serializers, authentication.py (JWT + X-Device-Id), errors.py, schema.py.
- web/: la plataforma web. views.py, urls.py, queries.py (consultas de pantallas), forms.py, permissions.py (matriz de permisos), messages.py (textos), templates/web/, static/web/, management/commands/ (sembrar_demo, medir_rendimiento).
- diagnostico/: comando diagnostico, comprobar_bd, respaldo, mantenimiento; middleware de registro de peticiones con traceId; arranque.py y checks.py.
- simulador/: herramientas para simular la app en desarrollo.

Carpeta deploy/ (despliegue en el VPS):

- docker-compose.yml
- instalar.sh (primera instalación; detecta Traefik en modo host y crea la red riachuelo-proxy)
- actualizar.sh (reconstruye y reinicia; muestra los logs si la web no arranca)
- desinstalar.sh (borra todo lo de la plataforma sin tocar OpenClaw ni Traefik)
- env.piloto.plantilla (plantilla de secretos del VPS)
- LEEME.md (guía de operación)
- modelos/ (aquí va modelo.onnx; montado de solo lectura en los contenedores)
- En el VPS, además, existen .env (variables de compose sin secretos, generadas por instalar.sh) y .env.piloto (secretos, permiso 600). Ninguno de los dos está en Git.

Carpeta scripts/: iniciar.ps1 (Windows), iniciar.sh (Linux/Mac), empaquetar.sh (genera el tar.gz; ya no es necesario con git).

Carpeta docs/:

- ARQUITECTURA_DATOS.md (base de datos, Cloudinary, seguridad, configuración manual)
- INTEGRACION_APP.md (cómo se conecta la app con la API)
- REPORTE_AVANCE.md (bitácora de avance, regla W-24)
- adr/ADR-W-001 a ADR-W-006
- img/arquitectura_produccion.png (diagrama de arquitectura en producción, sin OpenClaw)
- Plataforma_Riachuelo_como_funciona.pdf (presentación de 79 diapositivas)


## 5. Cómo se hacen los cambios: VS Code, Git, GitHub y VPS

El código vive en tres lugares que se mantienen iguales con Git:

1. La PC de Oscar (VS Code), donde se editan los archivos.
2. GitHub (OskitarBB/agricola-riachuelo-platform, rama prueba2), el punto de encuentro del equipo.
3. El VPS (/srv/riachuelo), donde corre la plataforma real.

Los cambios siempre van en esta dirección: PC, luego GitHub, luego VPS. Nunca se edita código directamente en el VPS (solo el archivo de secretos .env.piloto y la carpeta modelos/).

### 5.1 Antes de empezar a trabajar (en la PC)

Abrir la carpeta C:\Users\oscos\Videos\agricola-riachuelo-platform en VS Code. Abrir la terminal integrada (Ctrl + ñ o menú Terminal, New Terminal) y traer lo último que haya subido el equipo:

```
git pull
```

Comprobar que se está en la rama correcta:

```
git branch
```

Debe aparecer marcada prueba2. Si no, cambiar con git checkout prueba2.

### 5.2 Hacer los cambios

Editar los archivos en VS Code (o pedirle a una IA que los edite en la carpeta). Para probar en local, ver la sección 18 (iniciar.bat). Antes de subir, ejecutar las comprobaciones (con el entorno virtual .venv activo o usando .venv\Scripts\python.exe):

```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Si se cambió un modelo de datos (models.py), hay que crear la migración con python manage.py makemigrations y subir también el archivo de migración nuevo. Las migraciones se aplican solas en el VPS al arrancar el contenedor web.

### 5.3 Guardar en Git y subir a GitHub (en la PC)

```
git pull
git add -A
git commit -m "descripción corta del cambio"
git push
```

Explicación:

- git pull: por si el compañero subió algo mientras tanto. Si Git avisa de conflicto, resolverlo en VS Code (aparecen las dos versiones del archivo marcadas) y luego git add -A y git commit.
- git add -A: marca todos los archivos cambiados, nuevos y borrados.
- git commit -m: crea el punto de guardado con un mensaje.
- git push: lo sube a GitHub en la rama prueba2.

También se puede hacer desde el panel de control de código fuente de VS Code (ícono de ramas a la izquierda): escribir el mensaje, botón Commit y luego Sync Changes. El resultado es el mismo.

El archivo .env (secretos de desarrollo) nunca se sube: está en .gitignore. Tampoco se suben db.sqlite3, media/, .venv/, pesos del modelo (.pt, .onnx) ni respaldos.

### 5.4 Actualizar el VPS para que los cambios lleguen a la web real

Entrar al VPS de una de dos formas:

- Desde el panel de Hostinger: VPS, botón de terminal del navegador (consola web).
- Desde la terminal de la PC: ssh root@179.198.103.82 (pide la contraseña de root; la escribe Oscar, nunca se pega en el chat).

Luego ejecutar:

```
cd /srv/riachuelo && git pull && bash deploy/actualizar.sh
```

Qué hace actualizar.sh, paso a paso:

1. docker compose build web: reconstruye la imagen riachuelo-plataforma:latest con el código nuevo (instala dependencias solo si cambió requirements; ejecuta collectstatic).
2. docker compose up -d --remove-orphans: reinicia web y worker con la imagen nueva.
3. Al arrancar, el contenedor web ejecuta python manage.py migrate --noinput (aplica migraciones nuevas) y luego gunicorn.
4. Espera hasta 200 segundos a que el chequeo de salud (/api/v1/health) diga healthy.
5. Si la web no arranca, muestra las últimas 60 líneas del log de la web y termina con error.
6. Si arranca, muestra docker compose ps, borra imágenes viejas (docker image prune) y ejecuta el diagnóstico (python manage.py diagnostico --sin-color).

Tarda entre 1 y 2 minutos. Durante ese tiempo la web puede no responder unos segundos.

Este es siempre el mismo comando para cualquier cambio de código. También se usa después de editar .env.piloto (secretos o configuración) o de copiar el modelo de IA a deploy/modelos/.

Si en el VPS git pull se queja de cambios locales (no debería pasar porque no se edita código allí), revisar con git status. Los archivos .env y .env.piloto no están en Git, así que no se pisan.

### 5.5 Verificar después de actualizar

- Abrir https://monitoreo.agricolariachuelo.org y entrar.
- En el VPS: cd /srv/riachuelo/deploy y docker compose ps (ambos contenedores deben estar Up; web en healthy).
- Ver la consola: docker compose logs -f --tail 50 web worker (Ctrl + C para salir).
- Diagnóstico completo: docker compose exec web python manage.py diagnostico


## 6. Cómo está desplegado actualmente

### 6.1 Servidor

- Proveedor: Hostinger, plan VPS KVM 1.
- Sistema: Ubuntu 24.04.
- Recursos: 1 vCPU, 3,8 GB de RAM, 48 GB de disco.
- IP pública: 179.198.103.82
- El VPS se comparte con OpenClaw, un proyecto personal de Oscar que no tiene relación con Riachuelo. La plataforma no toca OpenClaw ni su configuración. OpenClaw no aparece en el diagrama de arquitectura.
- Acceso: root, por SSH o por la consola web de Hostinger. El usuario ejecuta los comandos; la IA nunca pide ni escribe la contraseña de root.

### 6.2 Dominio y DNS

- Dominio: agricolariachuelo.org, comprado en Hostinger.
- Subdominio de la plataforma: monitoreo.agricolariachuelo.org
- Registro DNS: tipo A, nombre monitoreo, apunta a 179.198.103.82, TTL 300. Lo creó el soporte de Hostinger porque el editor DNS del panel mostraba el error "Order not found".
- Servidores de nombres: lunar.dns-parking.com y solar.dns-parking.com (los de Hostinger).
- Durante el proceso de reclamo del dominio apareció un mensaje engañoso de "no disponible"; se resolvió con soporte.

### 6.3 Proxy y HTTPS (Traefik)

- En el VPS ya corría un Traefik (contenedor traefik-mzks-traefik-1) instalado con OpenClaw. Ocupa los puertos 80 y 443.
- Traefik está en modo de red host. Entrypoints: websecure (443) y web (80). Resolvedor de certificados: letsencrypt.
- La plataforma no instala otro proxy ni modifica Traefik. Se conecta mediante la red Docker riachuelo-proxy (la crea instalar.sh) y etiquetas (labels) en el contenedor web.
- Reglas de Traefik (labels del servicio web): router riachuelo para Host(monitoreo.agricolariachuelo.org) en websecure con TLS y certresolver letsencrypt hacia el puerto 8000 del contenedor; router riachuelo-http en web (80) con redirección permanente a https.
- Si el certificado falla (por ejemplo, el DNS aún no había propagado y Let's Encrypt devolvió NXDOMAIN), se fuerza un nuevo intento con: cd /srv/riachuelo/deploy && docker compose up -d --force-recreate web

### 6.4 Contenedores (proyecto Docker Compose "riachuelo")

Imagen: riachuelo-plataforma:latest, construida desde el Dockerfile del repositorio. Una sola imagen para los dos servicios.

Servicio web (contenedor riachuelo-web-1):

- Comando: python manage.py migrate --noinput y luego gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 4 --worker-tmp-dir /dev/shm --timeout 60 --graceful-timeout 20 --forwarded-allow-ips=*
- Sirve la web, la API /api/v1, Django Admin en /gestion/ y los estáticos (WhiteNoise).
- Límites: 700 MB de RAM, 0,8 CPU.
- Chequeo de salud cada 30 segundos contra http://127.0.0.1:8000/api/v1/health (con cabeceras Host y X-Forwarded-Proto https), 3 reintentos, 90 segundos de gracia al arrancar.
- Redes: proxy (riachuelo-proxy, para Traefik) e interna.

Servicio worker (contenedor riachuelo-worker-1):

- Comando: python manage.py worker_ia
- Analiza fotos (cuando haya modelo) y envía avisos. Nunca atiende HTTP.
- Límites: 1,2 GB de RAM (margen para el modelo ONNX), 0,7 CPU.
- Espera a que web esté healthy (así las migraciones ya están aplicadas).
- Red: solo interna. stop_grace_period 30 s.

Aislamiento y seguridad comunes a ambos:

- Usuario sin privilegios riachuelo (uid y gid 10001).
- Sistema de archivos de solo lectura (read_only), con /tmp en memoria de 64 MB.
- cap_drop ALL (sin capacidades de Linux) y no-new-privileges.
- restart: unless-stopped (se levantan solos si el VPS reinicia).
- Logs json-file con tope de 10 MB por archivo y 3 archivos.
- Volumen ./modelos montado en /app/modelos de solo lectura (para el modelo YOLO).
- Variables: env_file .env.piloto.

Dockerfile:

- Base python:3.12-slim-bookworm.
- Variables PYTHONDONTWRITEBYTECODE, PYTHONUNBUFFERED, PYTHONUTF8, PIP_NO_CACHE_DIR.
- Crea el usuario riachuelo 10001.
- Instala requirements.txt y, con ARG INSTALAR_IA=1, también requirements-ia.txt (onnxruntime y numpy ya quedan listos).
- Copia el código y ejecuta collectstatic con valores ficticios (no usa la base ni secretos).
- Crea /app/modelos. USER riachuelo. Expone 8000.
- .dockerignore evita que .env, .venv, media, db.sqlite3, etc. entren a la imagen.

### 6.5 Variables de entorno del VPS (/srv/riachuelo/deploy/.env.piloto)

Se editan con nano /srv/riachuelo/deploy/.env.piloto y se aplican con bash /srv/riachuelo/deploy/actualizar.sh. Nombres de las variables (los valores secretos nunca se escriben en el chat ni en Git):

- APP_ENV=piloto (exige HTTPS, Cloudinary y PostgreSQL; prohíbe datos de demostración)
- DJANGO_DEBUG=false
- DJANGO_SECRET_KEY (la generó instalar.sh)
- ALLOWED_HOSTS=monitoreo.agricolariachuelo.org
- CSRF_TRUSTED_ORIGINS=https://monitoreo.agricolariachuelo.org
- PUBLIC_BASE_URL=https://monitoreo.agricolariachuelo.org (se usa en el enlace de los avisos de WhatsApp)
- DATABASE_URL (cadena del Session pooler de Supabase, puerto 5432; contraseña solo letras y números)
- DB_SSLMODE=require
- DB_LIMITE_MB=500 (plan Free; 8192 si se pasa a Pro)
- CLOUDINARY_URL (formato cloudinary://api_key:api_secret@cloud_name, con valores reales; al inicio se copió por error el texto de ejemplo del panel y se corrigió)
- CLOUDINARY_ENV_PREFIX=piloto
- API_SUBIDA_MULTIPART=true (compatibilidad de subida v1; pasar a false cuando la app use solo el ticket v2.0)
- IA_DETECTOR=onnx
- MODEL_PATH=modelos/modelo.onnx
- WHATSAPP_CLIENT=notificaciones.whatsapp.ConsoleClient
- WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_GRAPH_VERSION (vacíos)
- WHATSAPP_TEMPLATE=caso_confirmado, WHATSAPP_TEMPLATE_LANG=es
- LOG_LEVEL=INFO, LOG_REQUESTS=true, LOG_SLOW_MS=1500, LOG_COLOR=0

Archivo /srv/riachuelo/deploy/.env (sin secretos, lo genera instalar.sh): DOMINIO, TRAEFIK_NETWORK (riachuelo-proxy), TRAEFIK_ENTRY_HTTPS (websecure), TRAEFIK_ENTRY_HTTP (web), TRAEFIK_CERTRESOLVER (letsencrypt).

### 6.6 Comandos de operación en el VPS

Todos desde cd /srv/riachuelo/deploy:

- docker compose ps: estado de los contenedores.
- docker compose logs -f --tail 50 web worker: consola en vivo (Ctrl + C para salir). Cada petición sale en una línea con su traceId.
- docker compose exec web python manage.py diagnostico: revisa configuración, base, RLS, permisos, TLS, trigger de auditoría, CHECK, espacio usado, Cloudinary, IA y WhatsApp.
- docker compose exec web python manage.py diagnostico --red: igual, incluyendo pruebas de red.
- docker compose restart worker: reinicia solo el worker.
- docker compose exec web python manage.py createsuperuser: crea un administrador (ya se creó el primero).
- docker compose exec web python manage.py respaldo: respaldo pg_dump (pendiente de probar en el VPS; ver pendientes).
- docker compose exec web python manage.py mantenimiento: limpia sesiones, tokens vencidos y caché vieja.
- bash actualizar.sh: aplica cambios de código, de .env.piloto o del modelo.
- bash desinstalar.sh: retira la plataforma al terminar el proyecto (borra contenedores, imágenes y /srv/riachuelo; OpenClaw y Traefik quedan intactos). Después quitar el registro DNS monitoreo en Hostinger.

### 6.7 Instalación inicial (ya hecha, solo como referencia)

1. Clonar el repositorio en /srv/riachuelo (al principio se usó un tar.gz; ahora es un clon de git en la rama prueba2).
2. bash /srv/riachuelo/deploy/instalar.sh (crea .env.piloto desde la plantilla y se detiene).
3. nano /srv/riachuelo/deploy/.env.piloto (pegar DATABASE_URL y CLOUDINARY_URL).
4. bash /srv/riachuelo/deploy/instalar.sh (construye, levanta y diagnostica).
5. docker compose exec web python manage.py createsuperuser.

### 6.8 Errores que ya ocurrieron en el despliegue y cómo se resolvieron

- collectstatic fallaba porque leaflet.js tenía una línea sourceMappingURL que apuntaba a un archivo inexistente. Se quitó la línea del archivo vendorizado.
- instalar.sh no detectaba la red de Traefik porque Traefik está en modo host. Se corrigió: ahora detecta el modo host y crea la red riachuelo-proxy.
- CLOUDINARY_URL se pegó con el texto de ejemplo del panel (con los marcadores en vez de la clave real). El usuario lo corrigió con los valores reales.
- El certificado falló al principio con NXDOMAIN porque el DNS aún no existía. Se resolvió con docker compose up -d --force-recreate web después de que el registro A estuvo activo.
- actualizar.sh ahora muestra los logs si la web no arranca, para no quedar a ciegas.


## 7. Cómo se ejecuta (flujo en tiempo de ejecución)

Petición desde un navegador o desde la app:

1. El cliente resuelve monitoreo.agricolariachuelo.org a 179.198.103.82.
2. Traefik recibe en 443 (o en 80 y redirige a 443), termina TLS con el certificado de Let's Encrypt y reenvía al contenedor riachuelo-web-1 en el puerto 8000 por la red riachuelo-proxy.
3. Gunicorn (2 procesos, 4 hilos cada uno) pasa la petición a Django.
4. El middleware de diagnóstico asigna un traceId, registra la petición en la consola y avisa si tarda más de 1500 ms.
5. Rutas:
   - /api/v1/... : API REST de la app (JWT + cabecera X-Device-Id).
   - /gestion/ : Django Admin (solo superusuario/administrador, para configuración avanzada: modelos de IA, contornos de lote, etc.).
   - /static/... : estáticos servidos por WhiteNoise.
   - el resto: la web (sesión de Django con cookie, CSRF, HTMX).
6. Django lee y escribe en Supabase PostgreSQL por el Session pooler (puerto 5432, TLS).
7. Las fotos nunca pasan por la base: se guardan en Cloudinary y la base solo guarda su identificador. La web genera URLs firmadas al mostrar cada foto.

Worker (riachuelo-worker-1), bucle continuo:

1. Comprueba si hay un modelo de IA activo (tabla model_configs con active=True). Si no hay, avisa una vez en el log y no analiza; sigue enviando avisos pendientes.
2. Si hay modelo, lo carga con el detector configurado (IA_DETECTOR=onnx, archivo MODEL_PATH).
3. Cada 60 segundos encola las fotos aceptadas por calidad que quedaron sin tarea del modelo activo (enqueue_missing), por ejemplo las que llegaron cuando no había modelo.
4. Toma la siguiente tarea de la tabla ai_tasks con SELECT ... FOR UPDATE SKIP LOCKED (arrendamiento con locked_until, reintentos con attempts).
5. Descarga el original de Cloudinary, aplica la orientación EXIF, ejecuta el modelo, guarda las detecciones (cajas en píxeles de la imagen analizada) y el estado de la tarea.
6. Si hay cajas, abre un caso de revisión (review_cases) con origen IA y copia la ubicación (lote, hilera, lateral, segmento, marcador, coordenadas).
7. Envía los avisos de WhatsApp pendientes (hoy solo los imprime en el log porque está ConsoleClient).
8. Si no hay trabajo, espera 3 segundos.

La web se actualiza sola con HTMX: la bandeja de casos cada 15 segundos y la actividad en vivo cada 20 segundos (sondeo, sin websockets ni Supabase Realtime).


## 8. Base de datos (Supabase PostgreSQL)

### 8.1 Proyectos

- riachuelo-piloto: el de producción. Región São Paulo (sa-east-1). Plan Free. Sin datos de demostración. Es el que usa el VPS.
- Proyecto de desarrollo: separado, en región us-west-2, con datos de demostración. Se usa desde la PC para probar como en el piloto (opcional; en local también se puede usar SQLite).

Nunca se mezclan datos de prueba con evidencia del piloto.

### 8.2 Conexión

- Supabase, botón Connect, Direct, Session pooler, puerto 5432 (IPv4). No se usa el transaction pooler (6543) porque no admite sentencias preparadas.
- Formato: postgresql://postgres.REF:CONTRASEÑA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
- La contraseña de la base debe tener solo letras y números (24 o más caracteres) para no romper la URL.
- DB_SSLMODE=require.
- Django se conecta como dueño de las tablas.

### 8.3 Qué se usa y qué no de Supabase

- PostgreSQL gestionado: sí.
- Session pooler: sí.
- Data API (PostgREST) y GraphQL: no. Nadie fuera del servidor lee la base.
- Supabase Auth: no. El login es de Django.
- Supabase Storage: no. Las fotos van a Cloudinary. No se crean buckets.
- Realtime: no. La web usa HTMX.
- Queues (pgmq): no. La cola es la tabla ai_tasks.
- Las claves anon/publishable y service_role no se usan en ningún lado y nunca se copian a la app ni al navegador.

### 8.4 Tablas (38 en total: 26 del dominio y 12 técnicas de Django)

Todas las crea python manage.py migrate. Nunca se crean ni editan tablas desde el Table Editor o SQL Editor de Supabase.

Cuentas (app cuentas):

- users: id UUID, correo, estado de cuenta (PENDIENTE_APROBACION, ACTIVO, RECHAZADO, BLOQUEADO), aprobación, contraseña temporal / cambio obligatorio (must_change_password), aceptación del aviso de privacidad.
- user_roles: roles de cada usuario (ADMINISTRADOR, OPERADOR_CAMPO, ESPECIALISTA_FITOSANITARIO, SUPERVISOR). Una cuenta puede tener varios roles según las reglas de la sección 14.
- devices: celulares registrados (device_id UUID generado por la app al instalarse), plataforma, revocable desde la web.
- password_reset_requests: solicitudes de restablecimiento de contraseña desde la app.

Catálogos (app campo):

- field_lots: id (por ejemplo SWG1), code (SWG 1), name, active, geometry (JSON GeoJSON opcional: Polygon o MultiPolygon en WGS84; hoy vacío).
- field_rows: id (SWG1-H01), lot, number, plant_count, active. Único por (lote, número).
- field_segments: id, row, code, start_plant, end_plant, is_pilot, active (agregado en v1.2). CHECK start_plant <= end_plant. No tiene coordenadas.
- markers: id, row, segment (opcional), code, description, position (INICIO, FIN, INTERMEDIO), lat, lon (opcionales; hoy vacíos), active (agregado en v1.2).
- quality_profiles: version (Q0, Q1...), params JSON, published_at. Perfil de calidad de foto que baja a la app.

Monitoreo (app monitoreo; IDs UUID generados en la app para que los reenvíos sean idempotentes):

- monitoring_sessions: recorrido de monitoreo (estado; SYNCED es solo local en la app).
- session_devices: celulares/cámaras de la sesión.
- monitoring_passes: pasada por lateral (LATERAL_A o LATERAL_B) de una hilera, con dirección y estado.
- marker_changes: cambios de marcador durante la pasada.
- capture_sequences: secuencia de captura (agrupa las fotos simultáneas de las cámaras), con segment, marker, lat, lon, gps_accuracy_m.
- incidents: incidencias reportadas (tipo, severidad, creada por).

Evidencia (app evidencias):

- captures: capture_id UUID de la app, columnas cloudinary_public_id (único), version, bytes, format, width, height, estado de calidad, contexto de repetición (retake_context), confirmed_at. No se guarda ninguna URL.
- quality_results: calidad medida en el celular.

IA (app ia):

- model_configs: name, version (única), weights_uri, weights_sha256, classes (lista en el orden del entrenamiento), conf_threshold (0,25 por defecto), iou_threshold (0,45), imgsz (640), tiling (JSON), active. Índice parcial único: solo un modelo activo.
- ai_tasks: task_id, capture, model_config, status (PENDIENTE_DE_ANALISIS, EN_ANALISIS, INDICIO_SUGERIDO_POR_IA, SIN_INDICIOS_IA, ERROR_DE_ANALISIS), requested_at, available_at, locked_until, locked_by, attempts, started_at, finished_at, processing_ms, model_version, image_width, image_height, error_message, raw_output. Única por (captura, modelo).
- detections: cajas sugeridas en píxeles con su confianza y el resultado de la revisión.

Revisión (app revision):

- review_cases: un caso por foto. origin (IA o MANUAL), status (PENDIENTE_REVISION, CONFIRMADO_POR_ESPECIALISTA, EVIDENCIA_INSUFICIENTE, DESCARTADO), notification_status, detections_count, max_confidence, y la ubicación copiada al abrir el caso: session, pass_id, sequence, lot, row, lateral_code, segment, marker, lat, lon, gps_accuracy_m, location_source (GPS, MARCADOR, NINGUNA), captured_at, opened_at, decided_at, decided_by. Índices para bandeja (status, opened_at), plano (lot, row, status) y fecha (captured_at).
- human_reviews: decisión del especialista. Nunca se edita ni se borra; una corrección crea otra fila (supersedes). Índice parcial único: una sola decisión vigente por caso.

Avisos (app notificaciones):

- notification_recipients: destinatarios de WhatsApp (etiqueta de rol, teléfono).
- notification_recipient_lots: qué lotes recibe cada destinatario.
- notifications: un aviso por (decisión, destinatario), con estado de envío.

Auditoría (app auditoria):

- audit_events: solo inserción. Usuario, acción, objeto, trace_id, fecha.

Tablas técnicas de Django: django_session, django_migrations, django_content_type, django_admin_log, auth_* (permisos y grupos), users_groups, users_user_permissions, token_blacklist_outstandingtoken y token_blacklist_blacklistedtoken (refresh revocados de la app) y web_cache (caché en base de datos).

### 8.5 Integridad garantizada por la base

- Claves UUID generadas en la app para sesiones, pasadas, secuencias, capturas e incidencias: los reintentos de sincronización no duplican.
- Claves foráneas con PROTECT en evidencia, casos y decisiones: no se puede borrar una captura con caso ni un usuario con decisiones.
- UNIQUE en cloudinary_public_id, (decisión, destinatario), (captura, modelo), (pasada, número de secuencia), (lote, número de hilera), entre otros.
- Índices parciales únicos: un solo modelo activo; una sola decisión vigente por caso.
- 44 restricciones CHECK de estados (generadas por config/restricciones.py): ningún campo con estados controlados puede tener un valor inexistente, aunque se edite desde un panel. Desde v1.2 se suman las columnas active.
- CHECK de rangos: lat entre -90 y 90, lon entre -180 y 180, gps_accuracy_m >= 0, confianza entre 0 y 1, cajas con x_min < x_max, segmento con start_plant <= end_plant.
- Transacciones: captura y tarea de IA se crean juntas; decisión y avisos se crean juntos.
- Trigger de auditoría de solo inserción: UPDATE y DELETE sobre audit_events se rechazan, salvo poner user_id en NULL si se elimina una cuenta (auditoria/migrations/0004).
- Coordenadas en double precision (unos 15 dígitos), suficiente para 6 decimales de GPS (unos 10 cm).

### 8.6 Seguridad de la base

Después de cada migrate, auditoria/seguridad_bd.py:

- Activa RLS (Row Level Security) sin políticas en todas las tablas: los roles anon y authenticated de Supabase no ven ninguna fila.
- Revoca a anon y authenticated los permisos sobre tablas, secuencias, funciones y el uso del esquema public.
- Quita los privilegios por defecto para que una tabla nueva nunca nazca expuesta.
- Django, como dueño de las tablas, no queda restringido por RLS (no se usa FORCE).

El Security Advisor de Supabase muestra avisos "RLS enabled, no policy" de nivel INFO. Son intencionales. No se deben crear políticas.

### 8.7 Configuración manual del panel de Supabase (estado)

1. Un proyecto por entorno, región São Paulo: hecho para el piloto.
2. Contraseña larga solo con letras y números: hecho.
3. Session pooler en DATABASE_URL con DB_SSLMODE=require: hecho.
4. Desactivar Data API o quitar public de Exposed schemas: obligatorio en piloto (verificar que quedó hecho).
5. Enforce SSL on incoming connections: recomendado (verificar).
6. Network Restrictions solo con la IP del VPS (179.198.103.82): PENDIENTE.
7. Desactivar Allow new users to sign up en Authentication: recomendado (verificar).
8. No crear buckets ni publicaciones de Realtime: cumplido.
9. No crear ni editar tablas desde el panel: cumplido.
10. Plan Pro para el piloto (backups diarios, sin pausa por inactividad): PENDIENTE. Hoy está en Free.
11. No usar claves anon/service_role: cumplido.

### 8.8 Migraciones relevantes

- Todas las migraciones iniciales de cada app (38 tablas).
- auditoria/migrations/0004: trigger de solo inserción con excepción para user_id NULL.
- campo/migrations/0003_catalogo_activo (v1.2): agrega active (por defecto True) a field_segments y markers.
- En el piloto se aplican solas al arrancar el contenedor web.

### 8.9 Capacidad, respaldo y mantenimiento

- Medido con datos sintéticos (docs/perf/datos_sinteticos.sql): 100 000 fotos con análisis y unos 19 000 casos ocupan unos 103 MB, alrededor de 1 KB por foto. El plan Free (500 MB) alcanza para unas 300 000 fotos. El límite real está en los créditos de Cloudinary.
- DB_LIMITE_MB hace que el diagnóstico avise al llegar al 80 % del plan.
- Respaldo: python manage.py respaldo genera respaldos/riachuelo-ENTORNO-FECHA.dump (pg_dump formato custom). Semanal en Free. PENDIENTE configurarlo y probarlo desde el VPS (requiere pg_dump en la imagen o en el host y una carpeta con escritura, porque el contenedor es de solo lectura).
- Restaurar: pg_restore --no-owner --no-privileges -d "DATABASE_URL" archivo.dump y luego migrate.
- Mantenimiento semanal: python manage.py mantenimiento (en Free además evita la pausa por inactividad del proyecto).
- Revisión tras cambios: python manage.py diagnostico --red.
- Retención: no se borra evidencia (R-11) hasta que el equipo decida la política (pregunta abierta Q-05).


## 9. Cloudinary (fotos)

### 9.1 Cuenta y configuración

- Cloud name: wd9meyw0.
- Clave API dedicada al piloto (distinta de la de desarrollo). El secreto solo está en .env.piloto del VPS.
- CLOUDINARY_ENV_PREFIX=piloto (en desarrollo: dev).
- Plan Free: 25 créditos al mes; unas 1 000 fotos consumen unos 10 créditos. Tamaño máximo por foto: 10 MB (CLOUDINARY_MAX_UPLOAD_BYTES=10485760).

### 9.2 Estructura de carpetas e identificadores

- Ruta: riachuelo/{prefijo}/{sesión}/{pasada}/{captura}, por ejemplo riachuelo/piloto/UUID_SESION/UUID_PASADA/UUID_CAPTURA.
- public_id = captureId (el UUID que genera la app).
- Tipo de entrega: authenticated. Sin URL firmada la foto no se ve.

### 9.3 Qué se guarda en la base

Solo cloudinary_public_id, version, bytes, format, width y height en la tabla captures. Nunca una URL. Las URLs firmadas se generan al mostrar cada pantalla (regla W-10).

### 9.4 Transformaciones con nombre (creadas en el panel)

- miniatura = c_limit,w_400,q_auto (listas, bandeja, tarjetas)
- revision = c_limit,w_1600,q_auto (visor del caso)

Recomendado en el panel: Strict transformations activado (nadie puede pedir otros tamaños ni gastar créditos) y no crear upload presets sin firma (toda subida va firmada por Django).

### 9.5 Cómo sube la app las fotos

Flujo v2.0 (ticket), el que usa la app 0.4.x:

1. La app pide POST /api/v1/captures/{captureId}/upload-ticket. Django responde con una firma de Cloudinary válida solo para ese public_id, carpeta y tipo authenticated.
2. La app sube la foto directamente a Cloudinary con esa firma (la foto no pasa por el VPS).
3. La app confirma con POST /api/v1/captures/upload (metadatos, calidad). Django verifica en Cloudinary, guarda la captura y, si la calidad es aceptable, crea la tarea de IA en la misma transacción.

Flujo v1 (multipart, compatibilidad, ADR-W-003): la app envía la foto a Django y Django la sube a Cloudinary. Habilitado con API_SUBIDA_MULTIPART=true. Se debe pasar a false cuando se confirme que la app ya no lo usa.

### 9.6 Cómo se ven las fotos

- La web genera URLs firmadas con las transformaciones miniatura o revision.
- En el plan Free las URLs firmadas no caducan; por eso el aviso de WhatsApp enlaza al caso en la web (que pide login) y nunca a la imagen.
- El worker descarga el original para analizarlo.

### 9.7 Desarrollo sin Cloudinary

Con CLOUDINARY_URL vacío y APP_ENV=dev se usa el "Cloudinary simulado" (ADR-W-001): las fotos quedan en la carpeta media/ de la PC. En piloto está prohibido; Cloudinary es obligatorio.


## 10. Inteligencia artificial (YOLO): estado y lo que falta

### 10.1 Estado actual

- El modelo YOLO todavía no está entrenado. No existe best.pt ni modelo.onnx.
- No hay ninguna fila activa en model_configs en el piloto.
- La configuración del VPS ya está preparada: IA_DETECTOR=onnx, MODEL_PATH=modelos/modelo.onnx, onnxruntime y numpy instalados en la imagen, carpeta /srv/riachuelo/deploy/modelos/ montada en /app/modelos.
- El worker corre y, al no haber modelo activo, escribe en el log que no hay modelo y no analiza. No inventa resultados.
- Cuando la app confirma una foto sin modelo activo, la captura se guarda igual (sin tarea; se registra un error en el log). Cuando se active un modelo, el worker encola automáticamente (cada 60 segundos) todas las fotos aceptadas que quedaron sin tarea y las analiza.
- Mientras tanto, el especialista puede abrir un caso manualmente desde la foto (captura, botón abrir caso, origen MANUAL).

### 10.2 Detectores disponibles en el código

- simulado (ia/inference/simulado.py): genera cajas de prueba. Solo para desarrollo (IA_SIMULADO_PROBABILIDAD=0.2 significa 20 % de fotos con indicio).
- onnx (ia/inference/onnx.py): el que se usará en el piloto. Usa onnxruntime en CPU. Hace letterbox a imgsz, decodifica la salida de YOLO con forma (4 + clases, N), aplica NMS, devuelve cajas en píxeles de la foto original. Soporta tiling (recortes con solapamiento y NMS global) para plagas pequeñas.
- yolo (ia/inference/yolo.py): usa ultralytics directamente (pesos .pt u .onnx). No está instalado por la licencia AGPL-3.0.

### 10.3 Qué hay que hacer para entrenar (trabajo del equipo de IA)

- Reunir y etiquetar fotos reales tomadas con la app en el fundo (indicios de la plaga objetivo; el nombre de ejemplo en el código es "yolo11n-chanchito", es decir, chanchito blanco / cochinilla).
- Definir la lista de clases y su orden exacto.
- Entrenar con Ultralytics YOLO (por ejemplo yolo11n o yolo11s) con imgsz 640 (o mayor si las plagas son muy pequeñas, o usar tiling).
- Elegir umbral de confianza e IoU según la validación.
- Exportar a ONNX en la máquina del equipo de IA:

```
yolo export model=best.pt format=onnx imgsz=640
```

### 10.4 Pasos exactos para activar el modelo en el VPS

1. Copiar el archivo al VPS con el nombre modelo.onnx. Desde la PC:

```
scp modelo.onnx root@179.198.103.82:/srv/riachuelo/deploy/modelos/
```

   El archivo no se sube a Git (está en .gitignore).

2. En https://monitoreo.agricolariachuelo.org/gestion/ entrar como administrador, sección Modelos de IA, crear una configuración:
   - name: por ejemplo yolo11n-chanchito
   - version: única, por ejemplo 2026.10-v1
   - weights_uri: modelos/modelo.onnx
   - weights_sha256: opcional (sha256sum modelo.onnx)
   - classes: lista JSON en el mismo orden del entrenamiento
   - conf_threshold: por ejemplo 0.25
   - iou_threshold: por ejemplo 0.45
   - imgsz: 640 (el mismo del export)
   - tiling: vacío, o {"tile": 1280, "overlap": 0.2} si las plagas son pequeñas
   - active: marcado (solo puede haber uno activo)

3. En el VPS:

```
cd /srv/riachuelo && bash deploy/actualizar.sh
```

4. Verificar: docker compose logs -f worker debe mostrar "Detector «onnx» listo con el modelo ..." con las clases y el umbral. En la web, pantalla IA (/ia/) muestra la cola y el estado. Las fotos que estaban esperando se analizan solas.

Para cambiar de modelo más adelante: copiar el nuevo .onnx, crear una nueva configuración con otra versión, marcarla activa (desmarcar la anterior) y ejecutar actualizar.sh. El worker detecta el cambio de versión y recarga el detector. Desde la pantalla IA el administrador puede reencolar tareas con error.

### 10.5 Recursos

El worker tiene 1,2 GB de RAM y 0,7 CPU. Un YOLO nano o small en ONNX en CPU entra con margen. Si se usa tiling o un modelo grande, vigilar el tiempo por foto (processing_ms en ai_tasks) y la RAM (docker stats).


## 11. WhatsApp (avisos)

- Estado: modo consola (WHATSAPP_CLIENT=notificaciones.whatsapp.ConsoleClient). Cuando un especialista confirma un caso, se crean los avisos para los destinatarios del lote, y el worker los imprime en su log en lugar de enviarlos.
- Para envío real se necesita: cuenta de Meta Business con WhatsApp Cloud API, WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_GRAPH_VERSION (por ejemplo v23.0), y una plantilla aprobada por Meta llamada caso_confirmado en español con 6 parámetros: lote, hilera, lateral, ubicación, decisión y enlace al caso.
- Luego cambiar WHATSAPP_CLIENT=notificaciones.whatsapp.CloudApiClient en .env.piloto y ejecutar actualizar.sh.
- Destinatarios: se administran en la web en Administración, Destinatarios (/administracion/destinatarios/), con sus lotes. Todavía no hay destinatarios reales cargados.
- El enlace del aviso siempre apunta al caso en la web (PUBLIC_BASE_URL), nunca a la foto.


## 12. Mapa y ubicaciones: cómo funciona y lo que falta

### 12.1 Cómo funciona hoy

- Pantalla Mapa (/mapa/), permiso mapa.ver (administrador, especialista, supervisor).
- Leaflet 1.9.4 local con teselas de OpenStreetMap. Centro por defecto: Chincha, Ica (-13.4099, -76.1323), zoom 15, solo si aún no hay casos con coordenadas.
- Los datos llegan de /mapa/datos/ como GeoJSON (comprimido con gzip). Por defecto muestra los últimos 30 días. Máximo 5 000 puntos (MAPA_MAX_FEATURES); si hay más, avisa que está truncado.
- Un punto por caso. El color es el estado de revisión: pendiente amarillo (#d9a21b), confirmado rojo (#d92d20), evidencia insuficiente morado (#7a5af8), descartado gris (#667085). Borde punteado = ubicación aproximada por marcador.
- El popup muestra lote, hilera, lateral, segmento, marcador, fecha, fuente de ubicación, precisión GPS y enlace al caso.
- También dibuja el contorno de los lotes que tengan geometry (GeoJSON).
- Muestra cuántos casos no tienen ubicación (sinUbicacion).
- Filtros iguales a la bandeja (fechas, lote, estado, etc.).

Cómo se decide la ubicación de un caso (revision/services.py, case_location), al abrir el caso:

1. Si la foto es una repetición, se usa el contexto de repetición que mandó la app (segmentId, markerId, lat, lon, gpsAccuracyM).
2. Si no, se usa la secuencia de captura (segment, marker, lat, lon, gps_accuracy_m).
3. Si hay lat y lon del GPS del celular: location_source = GPS.
4. Si no hay GPS pero el marcador tiene lat y lon: se usan las del marcador, location_source = MARCADOR (aproximada).
5. Si no hay ninguna: location_source = NINGUNA. El caso no aparece en el mapa (solo cuenta en "sin ubicación"), pero sí aparece en la bandeja y en el plano.

Plano de hileras (/plano/): es un esquema sin coordenadas. Por lote dibuja cada hilera como una barra y los segmentos activos dentro de ella según sus plantas (posición y ancho en porcentaje calculados en la consulta), con el conteo de casos por estado y si la hilera está cubierta (ambos laterales cerrados en el periodo). El plano no depende de GPS y funciona hoy.

### 12.2 Lo que falta (ubicación real del fundo)

Hoy no hay ninguna ubicación geográfica real del fundo cargada en el sistema:

- Lotes (field_lots.geometry): ninguno tiene contorno. Falta el polígono GeoJSON de SWG1, SWG2 y SWG5 (y de los demás lotes cuando se agreguen).
- Hileras (field_rows): no tienen ningún campo de ubicación. No se sabe dónde empieza y termina cada hilera en el terreno ni su orientación.
- Segmentos (field_segments): no tienen coordenadas; solo plantas de inicio y fin.
- Marcadores (markers): tienen campos lat y lon, pero están vacíos en los 83 pares -INI/-FIN (pregunta abierta Q-01: marcadores reales con coordenadas).
- Consecuencia: si el GPS del celular no da ubicación (o la app no la envía), el caso no se puede ubicar en el mapa. Si el GPS sí funciona, el punto aparece, pero sin el contorno del lote ni las hileras de referencia.

### 12.3 Cómo se pueden cargar ubicaciones hoy (sin desarrollo nuevo)

- Coordenadas de marcadores: en la web, Administración, Catálogos, entrar al lote, entrar a la hilera, editar el marcador y escribir latitud y longitud (formulario MarcadorForm). También desde /gestion/ (Marcadores). Se recomienda tomar las coordenadas en el terreno con un GPS o celular parado en el inicio y el fin de cada hilera (6 decimales).
- Contorno del lote: en /gestion/, Lotes, campo geometry, pegar un GeoJSON de tipo Polygon en WGS84 (orden longitud, latitud). Ejemplo de forma:

```
{"type": "Polygon", "coordinates": [[[-76.1330, -13.4100], [-76.1310, -13.4100], [-76.1310, -13.4085], [-76.1330, -13.4085], [-76.1330, -13.4100]]]}
```

  El primer y último punto deben ser iguales. Se puede dibujar en geojson.io sobre la imagen satelital y copiar solo la geometría.

### 12.4 Lo que habría que desarrollar (pendiente, no hecho)

- Importación CSV de catálogos y coordenadas (lote, hilera, plantas, marcador, lat, lon) desde Administración, Catálogos. Quedó para cuando lleguen los marcadores reales.
- Editor del contorno del lote dentro de Catálogos (hoy solo en /gestion/).
- Dibujar las hileras en el mapa como líneas entre el marcador -INI y el -FIN, y los segmentos como tramos proporcionales a sus plantas.
- Estimar la ubicación de un caso sin GPS interpolando entre INI y FIN según la planta o segmento.
- Requisito nuevo de la app: "Ubicar plaga en el mapa" (indicado en CONTEXTO_SISTEMA_2026-10-08). Necesita una decisión de diseño (ADR-W-007) y probablemente un endpoint nuevo en la API para que la app marque o consulte la ubicación de la plaga. No está empezado.


## 13. Web: pantallas, rutas y permisos

Roles con acceso a la web: ADMINISTRADOR (A), ESPECIALISTA_FITOSANITARIO (E), SUPERVISOR (S). OPERADOR_CAMPO no entra a la web.

Matriz de permisos (web/permissions.py, única fuente de verdad):

- dashboard.ver: A, E, S
- bandeja.ver: A, E, S
- caso.ver: A, E, S
- caso.decidir: E
- caso.corregir: E
- caso.abrir_manual: E
- mapa.ver: A, E, S
- sesiones.ver: A, E, S
- reportes.exportar: A, E, S
- notificaciones.ver: A, E, S
- ia.ver: A, E
- ia.reencolar: A
- usuarios.gestionar: A
- dispositivos.gestionar: A
- destinatarios.gestionar: A
- catalogos.gestionar: A, S (v1.2)
- auditoria.ver: A

Rutas (web/urls.py):

- /ingresar/ : inicio de sesión
- /salir/ : cerrar sesión
- /cuenta/contrasena/ : cambiar contraseña (obligatorio si la cuenta tiene contraseña temporal)
- / : panel principal (dashboard)
- /actividad/ : actividad en vivo (sondeo HTMX cada 20 s)
- /casos/ : bandeja de casos (refresco cada 15 s; exactamente 6 consultas a la base)
- /casos/UUID/ : detalle del caso con visor de foto y cajas
- /casos/UUID/decidir/ : decisión del especialista (confirmar, evidencia insuficiente, descartar)
- /casos/UUID/corregir/ : corrección de una decisión (crea otra fila en human_reviews)
- /capturas/UUID/ : detalle de una foto
- /capturas/UUID/abrir-caso/ : abrir caso manual desde una foto
- /mapa/ y /mapa/datos/ : mapa y su GeoJSON
- /plano/ : plano de hileras por lote
- /sesiones/ y /sesiones/UUID/ : sesiones de monitoreo y su detalle
- /reportes/ y /reportes/casos.csv : reportes y exportación CSV
- /notificaciones/ : avisos enviados o pendientes
- /administracion/destinatarios/ y /administracion/destinatarios/ID/ : destinatarios de WhatsApp
- /administracion/usuarios/ : cuentas (aprobar, rechazar, bloquear, roles)
- /administracion/usuarios/nueva/ : Nueva cuenta (v1.1)
- /administracion/usuarios/UUID/ACCION/ : acciones sobre una cuenta
- /administracion/catalogos/ : catálogos (v1.2)
- /administracion/catalogos/lote/ID/ : detalle de lote
- /administracion/catalogos/hilera/ID/ : detalle de hilera
- /administracion/dispositivos/ y /administracion/dispositivos/UUID/revocar/ : celulares y revocación
- /ia/ y /ia/tareas/UUID/reencolar/ : estado de la IA y reencolar tareas
- /auditoria/ : auditoría
- /gestion/ : Django Admin (configuración avanzada: modelos de IA, contornos de lote, perfiles de calidad)
- /api/v1/... : API de la app

Características de la web: diseño responsivo (celular, tableta, escritorio), animaciones, sonidos de aviso cuando llegan casos nuevos, avisos tipo toast, reporte automático de errores de JavaScript y de red, página 403 propia, modo demo en desarrollo (sembrar_demo).


## 14. Cuentas y roles (v1.1, ADR-W-005)

- Roles fijos: ADMINISTRADOR, OPERADOR_CAMPO, ESPECIALISTA_FITOSANITARIO, SUPERVISOR.
- Roles de la web: ADMINISTRADOR, ESPECIALISTA_FITOSANITARIO, SUPERVISOR. Se pueden combinar entre sí.
- Roles de la app: OPERADOR_CAMPO y ADMINISTRADOR.
- OPERADOR_CAMPO va siempre solo (cuenta exclusiva de la app; no se combina con roles de la web).
- El administrador usa la web y la app.
- Estados de cuenta: PENDIENTE_APROBACION, ACTIVO, RECHAZADO, BLOQUEADO.

Cómo se crean:

- Primer administrador: docker compose exec web python manage.py createsuperuser (ya hecho).
- Operadores de campo: se registran ellos mismos desde la app (POST /api/v1/auth/register) y quedan pendientes. El administrador los aprueba en Administración, Usuarios, asignando "Operador de campo". También se pueden crear con Nueva cuenta, tipo App móvil.
- Especialistas, supervisores y otros administradores: el administrador los crea en Administración, Usuarios, Nueva cuenta, tipo Plataforma web. La cuenta queda activa con una contraseña temporal que se muestra una sola vez; al primer ingreso se obliga a cambiarla.
- No hay registro público en la web.
- Django Admin (/gestion/) ya no crea usuarios.
- Pendiente: crear las cuentas reales de especialistas y supervisores.
- Pregunta abierta: si el aviso de privacidad también debe aceptarse en la web para las cuentas que crea el administrador.

Seguridad de acceso: límite de intentos de login, CSRF en la web, sesión con cookie (SESSION_COOKIE_AGE configurable, 8 horas por defecto en el ejemplo), JWT en la app con X-Device-Id, celulares revocables, cambio obligatorio de contraseña temporal.


## 15. Catálogos (v1.2, ADR-W-006)

- Ubicación: Administración, Catálogos. Permiso: administrador y supervisor.
- Lotes: crear y editar (el id se genera a partir del código, por ejemplo "SWG 1" da SWG1).
- Hileras: crear en bloque (desde número, hasta número, plantas por hilera; máximo 300 por vez), opcionalmente con segmento completo y marcadores de inicio y fin. Las que ya existen se saltan.
- "Completar hileras sin segmento": crea el segmento completo y los marcadores para las hileras que no lo tengan.
- Editar hilera (plantas). El id, el lote y el número no cambian.
- Segmentos: crear, editar, "Dividir en segmentos" (en N partes iguales o cada K plantas, con marcadores opcionales). Vista previa de la división en la página (app.js).
- Marcadores: crear y editar, con coordenadas opcionales (latitud, longitud) y descripción.
- "Eliminar" significa desactivar. Nunca se borra nada. Se puede reactivar.
- Al desactivar, la web avisa si hay sesiones en curso que usan ese elemento.
- IDs generados por el servidor, estables: hilera {lote}-H{nn} (SWG1-H05), segmento {hilera}-S{k}, marcadores de hilera completa -INI y -FIN, otros marcadores -M{k}. Conviven con los -S1, -INI y -FIN creados por el script del 07/10.
- La app recibe los cambios al tocar Actualizar en su pantalla de Catálogos: el bootstrap ya no envía segmentos ni marcadores inactivos, y ambos traen el campo active.
- La sincronización sigue aceptando IDs desactivados (para no perder datos de celulares que estaban sin internet).
- El plano solo dibuja segmentos activos; los casos de segmentos desactivados siguen contando en la hilera.
- Cada operación queda en auditoría: CATALOGO_CREADO, CATALOGO_EDITADO, CATALOGO_DESACTIVADO, CATALOGO_REACTIVADO, LOTE_HILERAS.
- En /gestion/ los catálogos no se pueden borrar y el id es de solo lectura al editar.
- Contorno del lote: sigue solo en /gestion/.
- Importación CSV: pendiente.

Archivos: campo/services.py (lógica), web/forms.py (LoteForm, HilerasForm, HileraForm, SegmentoForm, DividirForm, MarcadorForm), web/views.py (catalogos, catalogo_lote, catalogo_hilera con acciones editar, hileras, completar, desactivar, reactivar, segmento_nuevo, segmento_editar, dividir, marcador_nuevo, marcador_editar), web/queries.py (catalogo_lotes, catalogo_lote, catalogo_hilera), plantillas catalogos.html, catalogo_lote.html, catalogo_hilera.html, enlace en el menú lateral bajo Administración.


## 16. API /api/v1 (contrato con la app)

La app llama sin barra final (también se acepta con barra). Autenticación JWT Bearer más cabecera X-Device-Id. Errores con código, mensaje, errores por campo y traceId.

- GET /api/v1/health : salud (lo usa el chequeo de Docker)
- POST /api/v1/auth/register : registro de operador (queda pendiente de aprobación)
- POST /api/v1/auth/login : login (devuelve access y refresh)
- POST /api/v1/auth/refresh : renovar token (rotación)
- POST /api/v1/auth/logout : revocar refresh
- GET /api/v1/auth/me : datos de la cuenta
- POST /api/v1/auth/change-password : cambiar contraseña
- POST /api/v1/auth/password-reset-requests : solicitar restablecimiento
- GET /api/v1/mobile/bootstrap : catálogos activos (lots, rows, segments, markers con lat y lon, lateralCodes), perfil de calidad publicado, catalogVersion y serverTime
- POST /api/v1/sessions : crear o actualizar sesión (idempotente por sessionId)
- POST /api/v1/sessions/UUID/passes : crear o actualizar pasada (idempotente por passId)
- POST /api/v1/sessions/UUID/sequences/batch : secuencias (hasta 200 por petición)
- POST /api/v1/sessions/UUID/incidents/batch : incidencias
- POST /api/v1/captures/UUID/upload-ticket : ticket firmado para subir a Cloudinary (v2.0)
- POST /api/v1/captures/upload : confirmación de captura (o subida multipart v1 si API_SUBIDA_MULTIPART=true)
- GET /api/v1/captures/UUID : estado de una captura
- GET /api/v1/schema : esquema OpenAPI

Detalles en docs/INTEGRACION_APP.md y en el Maestro App Móvil, secciones 15 y 28.


## 17. App móvil (estado según CONTEXTO_SISTEMA_2026-10-08)

- Versión 0.4.6, configuración CFG-7, Expo SDK 57.
- Rama de la app: fase4-sincronizacion.
- Cuenta de EAS (compilación): oscar2020. Paquete Android: pe.riachuelo.monitoreo.
- Fase 4 (sincronización) terminada en código. Falta confirmar una sincronización real con el piloto en el campo.
- Usa el ticket v2.0 para subir fotos.
- Apunta a https://monitoreo.agricolariachuelo.org.
- Requisito nuevo pendiente: "Ubicar plaga en el mapa".
- Para conectar la app desde otro chat del mismo proyecto se dejó claude/HANDOFF_APP_MOVIL.md.


## 18. Desarrollo local (PC con Windows)

- Doble clic en iniciar.bat (o .\iniciar.bat en la terminal). Llama a scripts/iniciar.ps1, que:
  1. Busca Python 3.10 a 3.14 y crea el entorno virtual .venv.
  2. Instala dependencias.
  3. Crea .env desde .env.example con una clave secreta nueva (solo la primera vez).
  4. Aplica migraciones y, la primera vez, carga datos de demostración.
  5. Ejecuta el diagnóstico.
  6. Abre el worker de IA en otra ventana y la web en esta: http://127.0.0.1:8000
- Opciones: -Demo (recarga datos de demostración), -IA (instala onnxruntime y numpy), -SinWorker (solo web y API), -Puerto 8080.
- En dev: APP_ENV=dev, base SQLite si DATABASE_URL está vacío (o el proyecto Supabase de desarrollo), Cloudinary simulado si CLOUDINARY_URL está vacío (o Cloudinary con prefijo dev), IA_DETECTOR=simulado, WhatsApp en consola.
- El celular puede conectarse a la laptop por la IP de la red local (en dev se aceptan todos los hosts).
- sembrar_demo solo en dev. En piloto está prohibido (solo se permitiría sembrar_demo --solo-catalogos con catálogos reales).
- En Linux o Mac: scripts/iniciar.sh.


## 19. Pruebas y comprobaciones

Antes de cada subida:

```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

- 170 pruebas pasan (cuentas, campo con test_catalogos, api con test_api, web con test_views y test_extras, ia, revision, notificaciones, auditoria, diagnostico).
- web/tests/test_extras.py comprueba que no haya JavaScript en línea.
- Las pruebas de la web comprueban permisos de cada pantalla y que la bandeja haga exactamente 6 consultas.
- Pruebas de catálogos: creación en bloque, IDs, división, desactivación, reactivación, bootstrap sin inactivos, sincronización que acepta IDs desactivados.
- python manage.py medir_rendimiento: mide tiempos de pantallas con datos sintéticos.
- Después de cada tarea agregar una entrada en docs/REPORTE_AVANCE.md con el formato de la sección 23.2 del Maestro Web (regla W-24).


## 20. Reglas de la web que no se deben romper (Maestro Web, W-01 a W-24)

- W-01: sin CDN, npm ni frameworks de JavaScript. HTMX y Leaflet están en web/static/web/vendor/.
- W-07: toda vista lleva @web_view("permiso").
- W-10: no guardar URLs de fotos; generar URLs firmadas al mostrar.
- W-11: la IA "sugiere indicios", nunca diagnostica (también en textos).
- W-12: los colores indican el estado de revisión, nunca la gravedad.
- W-16: los números en atributos HTML o CSS se escriben sin localizar (filtros |pctnum o |stringformat), porque es-pe usa coma decimal.
- W-17: sin JavaScript en línea (ni script sin src ni onclick). El comportamiento va en app.js, caso.js o mapa.js.
- W-21: dependencias nuevas justificadas en el reporte de avance.
- W-22: sembrar_demo prohibido en piloto.
- W-24: reporte de avance al terminar cada tarea.
- La bandeja hace exactamente 6 consultas: no agregar consultas en base.html ni en context processors.
- data-confirmar solo funciona en formularios (no en botones sueltos).
- Los textos para el usuario van en web/messages.py.
- El servicio vuelve a comprobar las reglas críticas aunque la vista ya las compruebe (RN-W01).
- Las decisiones de revisión nunca se editan ni borran; las correcciones crean otra fila.
- Catálogos: nunca borrar, solo desactivar; los IDs no cambian.
- Las tablas solo se crean o cambian con migraciones de Django.


## 21. Decisiones de arquitectura (ADR) de la web

- ADR-W-001: Cloudinary simulado en desarrollo.
- ADR-W-002: actividad en vivo por sondeo HTMX (sin websockets ni Realtime).
- ADR-W-003: compatibilidad de subida multipart v1.
- ADR-W-004: integridad en la base (CHECK de estados y rangos, trigger de auditoría).
- ADR-W-005: alta de cuentas y tipos de cuenta (Nueva cuenta, operador solo, roles web combinables).
- ADR-W-006: gestión de catálogos desde la web (desactivar en vez de borrar, IDs del servidor, bootstrap sin inactivos).
- Próximo previsto: ADR-W-007 para "Ubicar plaga en el mapa" (y, si se hace, la importación CSV y las ubicaciones de hileras).


## 22. Seguridad y restricciones de trabajo (obligatorias para cualquier chat o persona que continúe)

- Los secretos (DATABASE_URL, CLOUDINARY_URL, DJANGO_SECRET_KEY, tokens de WhatsApp, contraseña de root) solo van en .env (PC) o .env.piloto (VPS). Nunca se pegan en el chat ni se suben a Git.
- Nunca usar las claves anon ni service_role de Supabase.
- Ningún secreto en el navegador ni en la app.
- sembrar_demo prohibido en el piloto.
- La IA no escribe ni pide la contraseña de root; el usuario ejecuta los comandos en el VPS.
- Si una clave se filtra: rotarla en el panel correspondiente, actualizar .env.piloto y ejecutar actualizar.sh.
- No modificar OpenClaw ni Traefik.
- No crear políticas RLS ni tablas desde el panel de Supabase.


## 23. Pendientes (lista completa)

IA:

1. Entrenar el modelo YOLO con fotos reales etiquetadas del fundo, definir clases y umbrales.
2. Exportar a ONNX, copiar a /srv/riachuelo/deploy/modelos/modelo.onnx, crear la configuración activa en /gestion/ y ejecutar actualizar.sh (sección 10.4).
3. Verificar tiempos y memoria del worker con el modelo real.

Mapa y ubicaciones:

4. Tomar en el terreno las coordenadas reales de los marcadores -INI y -FIN de las 83 hileras (Q-01) y cargarlas.
5. Dibujar y cargar el contorno GeoJSON de los lotes SWG1, SWG2 y SWG5.
6. Desarrollar la importación CSV de catálogos y coordenadas.
7. Opcional: editor de contorno en Catálogos, dibujo de hileras y segmentos en el mapa, ubicación estimada por interpolación cuando no hay GPS.
8. Requisito "Ubicar plaga en el mapa": escribir ADR-W-007, diseñar el endpoint de la API y la pantalla correspondiente.

Avisos:

9. Configurar WhatsApp Cloud API (token, phone ID, versión de Graph, plantilla caso_confirmado aprobada) y cambiar a CloudApiClient.
10. Cargar los destinatarios reales con sus lotes.

Cuentas:

11. Crear las cuentas de especialistas y supervisores con Nueva cuenta.
12. Decidir si el aviso de privacidad también se pide en la web para cuentas creadas por el administrador.

Base de datos e infraestructura:

13. Restringir el acceso de red de Supabase a la IP del VPS (179.198.103.82).
14. Verificar en Supabase: Data API desactivada o public fuera de Exposed schemas, Enforce SSL, sign up de Auth desactivado.
15. Pasar el proyecto del piloto a Supabase Pro (backups diarios, sin pausa por inactividad), y entonces DB_LIMITE_MB=8192.
16. Configurar respaldos con pg_dump desde el VPS (semanal) y probar una restauración.
17. Programar python manage.py mantenimiento semanal (por ejemplo con cron del host ejecutando docker compose exec).
18. Firewall del VPS: el puerto 3000 de OpenClaw está expuesto y el firewall está inactivo. Activar ufw permitiendo 22, 80 y 443 (con cuidado de no cortar el SSH).
19. Definir la política de retención de evidencia (Q-05).

App e integración:

20. Confirmar una sincronización real de la app en campo contra el piloto.
21. Cuando se confirme que la app usa solo el ticket v2.0, poner API_SUBIDA_MULTIPART=false en .env.piloto y ejecutar actualizar.sh.
22. Confirmar que v1.2 está subida a GitHub y aplicada en el VPS (si no, git add, commit, push y en el VPS git pull y actualizar.sh).

Cloudinary:

23. Verificar Strict transformations activado y que no existan upload presets sin firma.
24. Revisar créditos cada semana (plan Free, 25 al mes).

Documentación:

25. Mantener docs/REPORTE_AVANCE.md actualizado y actualizar el informe del curso con la correspondencia de tablas (docs/ARQUITECTURA_DATOS.md, sección 3).


## 24. Datos de referencia rápida

- Web: https://monitoreo.agricolariachuelo.org
- Django Admin: https://monitoreo.agricolariachuelo.org/gestion/
- Salud: https://monitoreo.agricolariachuelo.org/api/v1/health
- Esquema API: https://monitoreo.agricolariachuelo.org/api/v1/schema
- VPS: Hostinger KVM 1, Ubuntu 24.04, IP 179.198.103.82, acceso root por SSH o consola web de Hostinger
- Código en el VPS: /srv/riachuelo; despliegue en /srv/riachuelo/deploy
- Secretos en el VPS: /srv/riachuelo/deploy/.env.piloto (permiso 600)
- Modelo de IA en el VPS: /srv/riachuelo/deploy/modelos/modelo.onnx
- Contenedores: riachuelo-web-1, riachuelo-worker-1; Traefik: traefik-mzks-traefik-1; red: riachuelo-proxy
- GitHub: OskitarBB/agricola-riachuelo-platform, rama prueba2
- Carpeta local: C:\Users\oscos\Videos\agricola-riachuelo-platform
- Supabase piloto: riachuelo-piloto, sa-east-1, Session pooler 5432, plan Free
- Cloudinary: cloud wd9meyw0, prefijo piloto, fotos authenticated, transformaciones miniatura y revision
- Comando para publicar cambios (PC): git pull, git add -A, git commit -m "mensaje", git push
- Comando para actualizar el VPS: cd /srv/riachuelo && git pull && bash deploy/actualizar.sh
- Catálogo piloto: SWG1 31 hileras, SWG2 16, SWG5 36 (83 en total), sin coordenadas
- Estado IA: sin modelo; worker esperando
- Estado WhatsApp: consola
- Pruebas: 170 pasan
