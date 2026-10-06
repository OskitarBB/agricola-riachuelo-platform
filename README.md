# Agrícola Riachuelo · Plataforma de monitoreo fitosanitario de la vid

Plataforma **Django 5.2** que recibe lo que sincroniza la app móvil (API `/api/v1`), guarda la evidencia en
**Supabase (PostgreSQL)** y **Cloudinary**, analiza las fotos con el **worker de IA (YOLO)** y deja los indicios en la
**web de revisión** para que el especialista decida. Al confirmar un caso, el worker avisa por **WhatsApp** al
jefe de fundo y al supervisor de zona.

```
App móvil (Expo) ──JSON /api/v1──▶ Django (web + API) ──▶ Supabase PostgreSQL (RLS)
      │                                 │  ▲
      └──foto (ticket firmado)──▶ Cloudinary   │  cola ai_tasks (SELECT … FOR UPDATE SKIP LOCKED)
                                        ▼  │
                             worker_ia (YOLO/ONNX) ──▶ WhatsApp Cloud API (solo tras confirmar)
```

Construida según `MAESTRO_WEB_v1.0` y `MAESTRO_APP_MOVIL_v2.0` (§15 API y §28 arquitectura). Las reglas W-01 a W-24
se respetan: HTML del servidor + HTMX, sin CDN ni frameworks de JavaScript, sin JavaScript en línea, permisos en
cada vista y colores que indican el **estado de revisión, nunca la gravedad**.

---

## 1. Probarla en tu computadora (Windows)

Requisitos: **Python 3.12** (o 3.10–3.13) desde <https://www.python.org/downloads/>. Al instalarlo, marca
**«Add python.exe to PATH»**. No hace falta instalar PostgreSQL: sin `DATABASE_URL` se usa SQLite.

1. Abre la carpeta del proyecto y haz **doble clic en `iniciar.bat`**. También puedes ejecutar `.\iniciar.bat`
   desde una terminal.
2. La primera vez el script crea `.venv`, instala las dependencias, crea `.env` con una clave secreta nueva,
   aplica las migraciones y carga los **datos de demostración**.
3. Se abren dos ventanas:
   - **web y API**: <http://127.0.0.1:8000/>
   - **worker de IA**: analiza las fotos y envía los avisos.
4. Ingresa con una cuenta de prueba. La contraseña de todas es **`Demo2026`**:

| Cuenta | Rol | Qué puede hacer |
|---|---|---|
| `especialista@demo.pe` | Especialista fitosanitario | Revisa y decide casos (atajos C, D, I y Ctrl+Enter) |
| `supervisor@demo.pe` | Supervisor | Ve casos, mapa, plano y reportes; no decide |
| `admin@demo.pe` | Administrador | Crea cuentas de la web, aprueba las de la app, revoca celulares, destinatarios, auditoría |
| `operador@demo.pe` | Operador de campo | Solo la app móvil (la web le niega el acceso) |
| `temporal@demo.pe` | Operador | Contraseña temporal `Temp2026` (debe cambiarla) |

### Cuentas en el piloto (sin datos de demostración)

- **Primer administrador**: en el servidor, `docker compose exec web python manage.py createsuperuser`.
- **Especialistas, supervisores y otros administradores**: el administrador los crea en **Administración → Usuarios
  → Nueva cuenta**. Nacen activos con una contraseña temporal que se muestra una sola vez; al primer ingreso hay que
  cambiarla. La web no tiene registro público.
- **Operadores de campo**: se registran desde la app y el administrador los aprueba con el rol «Operador de campo»
  (o los crea con «Nueva cuenta → App móvil»).
- **Reglas**: «Operador de campo» va solo (cuenta de la app; la web le niega el acceso). Especialista y supervisor
  son cuentas de la web (la app las rechaza). El administrador entra a las dos. Una cuenta por persona y por tipo
  (ADR-W-005).

Opciones: `iniciar.bat -Demo` recarga los datos de demostración, `-IA` instala onnxruntime para el modelo real,
`-SinWorker` arranca solo la web y `-Puerto 8080` cambia el puerto.

> Si Windows pregunta por el **Firewall**, permite el acceso en *Redes privadas*. Así el celular llega a la API.

### Linux o macOS

```bash
./scripts/iniciar.sh        # DEMO=1, IA=1, SIN_WORKER=1 y PUERTO=8080 funcionan como las opciones de Windows
```

### Paso a paso (sin el script)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env               # y completa DJANGO_SECRET_KEY
python manage.py migrate             # tablas, caché y, en Supabase, RLS + REVOKE a anon/authenticated
python manage.py sembrar_demo        # SOLO en dev: catálogos del piloto + cuentas y casos de demostración
python manage.py runserver 0.0.0.0:8000
python manage.py worker_ia           # en otra terminal
```

---

## 2. Qué muestra la consola (errores y problemas)

Cada proceso escribe en su ventana, con colores:

- **Una línea por petición**: método, ruta, estado, tiempo, usuario o celular y un `traceId`. Los 4xx salen en
  amarillo, los 5xx en rojo y las peticiones de más de 1,5 s se marcan **LENTA**. Los sondeos automáticos de la
  web solo se escriben si fallan.
- **Errores de la API** con su código del contrato (`DEVICE_REVOKED`, `UPLOAD_MISMATCH`…). El `traceId` de la
  respuesta es el mismo de la consola, así que un error que ve la app se encuentra en la terminal.
- **Errores del navegador**: fallos de JavaScript, fotos que no cargan, mapa sin conexión o pantallas lentas.
  La web los envía a `/diagnostico/error-cliente/` y quedan en la consola con el usuario y la página.
- **Worker**: cada foto analizada (`✔ 2 caja(s) · 231 ms → caso 663a27a4`), los reintentos y los avisos de
  WhatsApp. En dev, el aviso se imprime completo en vez de enviarse.
- **Al arrancar**: un resumen de la base de datos, Cloudinary (real o simulado), WhatsApp y el detector, y la
  IP para configurar la app.

Revisión completa de la instalación:

```powershell
python manage.py diagnostico          # ✔ / ! / ✖ por cada punto, con la forma de corregirlo (código 1 si hay errores)
python manage.py diagnostico --red    # además prueba Cloudinary (una foto real) y el token de WhatsApp en Meta
python manage.py check --deploy       # con la configuración del piloto
```

---

## 3. Conectar los servicios reales

Todo se configura en `.env`. `.env.example` explica cada variable.

| Servicio | Variable | Dónde se obtiene |
|---|---|---|
| **Supabase** | `DATABASE_URL`, `DB_SSLMODE=require` | Project Settings → Database → Connection string → **Session pooler** (puerto 5432) |
| **Cloudinary** | `CLOUDINARY_URL` | Settings → API Keys. Crea también las transformaciones con nombre `miniatura` (`c_limit,w_400,q_auto`) y `revision` (`c_limit,w_1600,q_auto`) |
| **WhatsApp** | `WHATSAPP_CLIENT=notificaciones.whatsapp.CloudApiClient`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_GRAPH_VERSION`, `WHATSAPP_TEMPLATE` | Meta for Developers → WhatsApp → API Setup; la plantilla `caso_confirmado` debe estar aprobada |
| **Modelo YOLO** | `IA_DETECTOR=onnx`, `MODEL_PATH` | `yolo export model=best.pt format=onnx imgsz=640`; ver `ia/inference/weights/LEEME.md` |

La configuración de la base y de Cloudinary, tabla por tabla y casilla por casilla del panel, está en
[`docs/ARQUITECTURA_DATOS.md`](docs/ARQUITECTURA_DATOS.md).

Después de cambiar `DATABASE_URL`, corre `python manage.py migrate`. En Supabase eso activa RLS en todas las tablas
y quita los permisos de la Data API. Para cargar solo los catálogos del piloto, sin datos de demostración, usa
`python manage.py sembrar_demo --solo-catalogos`. Los segmentos, marcadores y coordenadas son ficticios hasta que
lleguen los reales.

Sin `CLOUDINARY_URL`, con `APP_ENV=dev`, funciona un **Cloudinary simulado**. Usa la misma firma del SDK y guarda
las fotos de la app en `media/`, así el flujo completo se prueba en la laptop. En `APP_ENV=piloto` nunca se activa.

## 4. Conectar la app móvil

En el `.env` de la app (repositorio `agricola-riachuelo-mobile`):

```
EXPO_PUBLIC_API_URL=http://<IP-de-esta-computadora>:8000     # la IP la imprime runserver al arrancar
EXPO_PUBLIC_USE_MOCK_API=0
```

Laptop y celulares deben estar en la misma red Wi-Fi. La API acepta la app **tal como está hoy**: la foto va por
multipart a `/captures/upload` y el servidor la sube a Cloudinary. También acepta el flujo **v2.0**: ticket
firmado, subida directa a Cloudinary y confirmación. Detalles, contrato y ejemplos en
[`docs/INTEGRACION_APP.md`](docs/INTEGRACION_APP.md). El esquema OpenAPI está en `/api/v1/schema`.

Cada ingreso desde la app, cuenta nueva, sesión sincronizada o caso abierto aparece **en vivo** en la web (campana,
avisos flotantes con sonido y contador de pendientes).

---

## 5. Pruebas

```powershell
python manage.py test                       # 131 pruebas (66 de referencia del Maestro Web + API, simulador, IA, seguridad de BD, extras)
python manage.py makemigrations --check --dry-run
```

En SQLite se omiten 5 pruebas que solo aplican a PostgreSQL (RLS, trigger de auditoría y concurrencia).

Operación semanal: `python manage.py respaldo` (pg_dump a `respaldos/`) y `python manage.py mantenimiento`
(sesiones, tokens y caché vencidos).
Rendimiento con 100 000 fotos sintéticas: `docs/perf/datos_sinteticos.sql` + `python manage.py medir_rendimiento`.

## 6. Estructura

```
config/          settings (APP_ENV dev|piloto), urls, wsgi
cuentas/ campo/ monitoreo/ evidencias/ ia/ revision/ notificaciones/ auditoria/   dominio (Anexo B del Maestro Web)
api/v1/          contrato de la app móvil (§15): serializadores camelCase, errores ApiErrorBody, JWT + X-Device-Id
web/             vistas HTMX, plantillas, estáticos (htmx, Leaflet, íconos, sonidos), demo y comandos
ia/inference/    detectores: simulado, onnx (YOLOv8/11 y end2end), yolo (ultralytics) + management/commands/worker_ia
simulador/       Cloudinary simulado (solo dev)
diagnostico/     registro en consola, traceId, errores del navegador, chequeos y comando `diagnostico`
docs/            reporte de avance, integración con la app, ADR y datos de rendimiento
scripts/         iniciar.ps1 (Windows) e iniciar.sh
```

## 7. Despliegue (piloto)

Variables mínimas: `APP_ENV=piloto`, `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `PUBLIC_BASE_URL=https://…`, `DATABASE_URL`, `CLOUDINARY_URL` e `IA_DETECTOR=onnx`. Luego:

```bash
python manage.py collectstatic --noinput && python manage.py migrate && python manage.py check --deploy
gunicorn config.wsgi --workers 3 --bind 0.0.0.0:8000      # detrás del proxy HTTPS del hosting
python manage.py worker_ia                                # proceso aparte (servicio)
```

`sembrar_demo` está bloqueado en piloto (W-22). El dominio de Hostinger se apunta al servidor manualmente.
