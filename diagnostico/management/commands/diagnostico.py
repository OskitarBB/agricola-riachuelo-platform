# diagnostico/management/commands/diagnostico.py — Revisión completa de la instalación, en lenguaje claro.
#
#   python manage.py diagnostico            # configuración, base de datos, catálogos, Cloudinary, WhatsApp, IA y cola
#   python manage.py diagnostico --red      # además prueba Cloudinary (una foto real) y el token de WhatsApp en Meta
#
# Cada línea es ✔ (bien), ! (aviso: funciona pero conviene corregir) o ✖ (error: algo no funcionará).
# Sale con código 1 si hay errores, para usarlo en scripts de despliegue. Nunca imprime secretos.
import importlib
import sys
from importlib import metadata
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

OK, AVISO, ERROR = "ok", "aviso", "error"
SIMBOLO = {OK: "✔", AVISO: "!", ERROR: "✖"}
COLOR = {OK: "\033[32m", AVISO: "\033[33m", ERROR: "\033[31m"}


class Command(BaseCommand):
    help = "Revisa configuración, base de datos, catálogos, Cloudinary, WhatsApp, modelo de IA y la cola de análisis."

    def add_arguments(self, parser):
        parser.add_argument("--red", action="store_true",
                            help="Prueba también los servicios externos (Cloudinary y WhatsApp) por internet.")
        parser.add_argument("--sin-color", action="store_true", help="Salida sin colores ANSI.")

    # ------------------------------------------------------------------ salida
    def handle(self, *args, **opts):
        self.red = opts["red"]
        self.color = not opts["sin_color"] and getattr(self.stdout, "isatty", lambda: False)()
        if sys.platform == "win32" and self.color:
            import os

            os.system("")  # activa las secuencias ANSI en la consola de Windows
        self.conteo = {OK: 0, AVISO: 0, ERROR: 0}
        self.bd_ok = False
        for titulo, fn in [("Entorno y configuración", self.entorno), ("Librerías", self.librerias),
                           ("Base de datos", self.base_datos), ("Catálogos y cuentas", self.catalogos),
                           ("Fotos (Cloudinary)", self.cloudinary), ("Avisos por WhatsApp", self.whatsapp),
                           ("IA y cola de análisis", self.ia), ("Archivos estáticos", self.estaticos)]:
            self.titulo(titulo)
            try:
                fn()
            except Exception as exc:  # un bloque roto no debe ocultar el resto del diagnóstico
                self.linea(ERROR, f"No se pudo revisar: {exc.__class__.__name__}: {exc}")
        self.stdout.write("")
        resumen = (f"{self.conteo[OK]} correctos · {self.conteo[AVISO]} avisos · {self.conteo[ERROR]} errores")
        estado = ERROR if self.conteo[ERROR] else AVISO if self.conteo[AVISO] else OK
        self.linea(estado, f"Resultado: {resumen}")
        if not self.red:
            self.stdout.write("   Para probar Cloudinary y WhatsApp por internet: python manage.py diagnostico --red")
        if self.conteo[ERROR]:
            sys.exit(1)

    def titulo(self, texto):
        self.stdout.write("")
        self.stdout.write(f"\033[1m{texto}\033[0m" if self.color else texto)

    def linea(self, nivel, texto, ayuda=None):
        self.conteo[nivel] += 1
        s = SIMBOLO[nivel]
        if self.color:
            s = f"{COLOR[nivel]}{s}\033[0m"
        self.stdout.write(f"  {s} {texto}")
        if ayuda:
            self.stdout.write(f"      → {ayuda}")

    # ------------------------------------------------------------------ bloques
    def entorno(self):
        py = sys.version_info
        self.linea(OK if py >= (3, 10) else ERROR, f"Python {py.major}.{py.minor}.{py.micro}",
                   None if py >= (3, 10) else "Django 5.2 necesita Python 3.10 o superior (recomendado 3.12).")
        piloto = settings.APP_ENV == "piloto"
        self.linea(OK, f"APP_ENV={settings.APP_ENV} · DEBUG={'true' if settings.DEBUG else 'false'}")
        if piloto and settings.DEBUG:
            self.linea(ERROR, "DEBUG está activo en piloto.", "DJANGO_DEBUG=false en el .env del servidor.")
        if getattr(settings, "SECRET_KEY_EFIMERA", False):
            self.linea(AVISO, "Sin DJANGO_SECRET_KEY: clave temporal, las sesiones se pierden al reiniciar.",
                       "Ejecuta scripts\\iniciar.ps1 o copia .env.example a .env.")
        elif len(settings.SECRET_KEY) < 40:
            self.linea(ERROR if piloto else AVISO, "DJANGO_SECRET_KEY es demasiado corta (mínimo 40 caracteres).")
        else:
            self.linea(OK, "DJANGO_SECRET_KEY definida")
        hosts = settings.ALLOWED_HOSTS
        if piloto and ("*" in hosts or not hosts):
            self.linea(ERROR, "ALLOWED_HOSTS debe listar el dominio en piloto.", "ALLOWED_HOSTS=monitoreo.tudominio.pe")
        else:
            self.linea(OK, f"ALLOWED_HOSTS={','.join(hosts)}")
        url = settings.PUBLIC_BASE_URL
        if piloto and not url.startswith("https://"):
            self.linea(ERROR, f"PUBLIC_BASE_URL={url} debe ser https:// en piloto (enlace del WhatsApp).")
        else:
            self.linea(OK, f"PUBLIC_BASE_URL={url}")
        if piloto and not settings.CSRF_TRUSTED_ORIGINS:
            self.linea(AVISO, "CSRF_TRUSTED_ORIGINS vacío: detrás de un proxy https el ingreso puede fallar.",
                       "CSRF_TRUSTED_ORIGINS=https://monitoreo.tudominio.pe")

    def librerias(self):
        requeridas = [("django", "Django"), ("rest_framework", "djangorestframework"),
                      ("rest_framework_simplejwt", "djangorestframework-simplejwt"),
                      ("drf_spectacular", "drf-spectacular"), ("django_htmx", "django-htmx"),
                      ("whitenoise", "whitenoise"), ("cloudinary", "cloudinary"), ("environ", "django-environ"),
                      ("requests", "requests"), ("PIL", "Pillow")]
        if connection.vendor == "postgresql":
            requeridas.append(("psycopg", "psycopg"))
        faltan = []
        versiones = []
        for modulo, paquete in requeridas:
            try:
                importlib.import_module(modulo)
                try:
                    versiones.append(f"{paquete} {metadata.version(paquete)}")
                except metadata.PackageNotFoundError:
                    versiones.append(paquete)
            except Exception:
                faltan.append(paquete)
        if faltan:
            self.linea(ERROR, f"Faltan librerías: {', '.join(faltan)}", "pip install -r requirements.txt")
        else:
            self.linea(OK, "Librerías de la plataforma instaladas")
            self.stdout.write("      " + " · ".join(versiones))
        if settings.IA_DETECTOR == "onnx":
            for modulo, paquete in [("numpy", "numpy"), ("onnxruntime", "onnxruntime")]:
                try:
                    importlib.import_module(modulo)
                except Exception:
                    self.linea(ERROR, f"IA_DETECTOR=onnx pero falta {paquete}.", "pip install -r requirements-ia.txt")

    def base_datos(self):
        db = settings.DATABASES["default"]
        motor = "PostgreSQL" if connection.vendor == "postgresql" else connection.vendor
        destino = db.get("HOST") or db.get("NAME")
        t0 = time.perf_counter()
        try:
            connection.ensure_connection()
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception as exc:
            from diagnostico import bd

            texto, ayuda = bd.explicar_error(exc)
            self.linea(ERROR, f"No conecta a la base de datos ({motor} {destino}): {texto}", ayuda)
            for problema, como in bd.problemas_de_url(bd.url_cruda()):
                self.linea(ERROR, problema, como)
            return
        ms = (time.perf_counter() - t0) * 1000
        self.bd_ok = True
        self.linea(OK if ms < 800 else AVISO, f"Conexión a {motor} ({destino}) en {ms:.0f} ms",
                   None if ms < 800 else "Latencia alta: elige la región de Supabase más cercana al servidor.")
        if settings.APP_ENV == "piloto" and connection.vendor != "postgresql":
            self.linea(ERROR, "En piloto la base debe ser PostgreSQL (Supabase).")
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            self.linea(ERROR, f"Hay {len(plan)} migraciones sin aplicar.", "python manage.py migrate")
        else:
            self.linea(OK, "Migraciones al día")
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT current_setting('server_version')")
                self.stdout.write(f"      PostgreSQL {cur.fetchone()[0]}")
                cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity")
                sin_rls = [r[0] for r in cur.fetchall()]
                cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
                roles = [r[0] for r in cur.fetchall()]
                expuestas = []
                for rol in roles:
                    cur.execute("SELECT count(*) FROM information_schema.role_table_grants "
                                "WHERE grantee = %s AND table_schema = 'public'", [rol])
                    if cur.fetchone()[0]:
                        expuestas.append(rol)
            if sin_rls:
                self.linea(ERROR, f"{len(sin_rls)} tablas sin Row Level Security: {', '.join(sin_rls[:5])}…",
                           "python manage.py migrate (lo activa al terminar) o revisa auditoria/seguridad_bd.py")
            else:
                self.linea(OK, "Row Level Security activo en todas las tablas")
            if expuestas:
                self.linea(ERROR, f"Los roles {', '.join(expuestas)} de la Data API tienen permisos en tablas.",
                           "python manage.py migrate (revoca los permisos al terminar)")
            elif roles:
                self.linea(OK, "Roles anon/authenticated de Supabase sin permisos sobre las tablas")
            self.integridad_postgres()
        try:
            from django.core.cache import caches

            caches["default"].set("diagnostico", "1", 5)
            self.linea(OK, "Caché en base de datos operativa")
        except Exception as exc:
            self.linea(ERROR, f"La tabla de caché no responde: {exc}", "python manage.py migrate")

    def integridad_postgres(self):
        """docs/ARQUITECTURA_DATOS.md §5–§6: cifrado, auditoría de solo inserción, CHECK de estados y espacio usado."""
        db = settings.DATABASES["default"]
        local = (db.get("HOST") or "localhost") in ("localhost", "127.0.0.1", "::1", "")
        try:
            cifrada = bool(connection.connection.pgconn.ssl_in_use)
        except AttributeError:
            cifrada = None
        if cifrada:
            self.linea(OK, "Conexión cifrada (TLS) con la base de datos")
        elif not local:
            self.linea(ERROR, "La conexión con la base de datos NO está cifrada.",
                       "DB_SSLMODE=require en .env y, en Supabase, Database → SSL Configuration → Enforce SSL.")
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_events_solo_insercion' "
                        "AND NOT tgisinternal")
            trigger = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                        "WHERE n.nspname = 'public' AND c.contype = 'c' AND c.conname LIKE %s", ["%_valido"])
            checks = cur.fetchone()[0]
            cur.execute("SELECT pg_database_size(current_database()), current_user")
            tamano, usuario = cur.fetchone()
        self.linea(OK if trigger else ERROR, "Auditoría de solo inserción (trigger en audit_events)" if trigger else
                   "Falta el trigger que impide editar o borrar la auditoría.", None if trigger else "python manage.py migrate")
        self.linea(OK if checks else ERROR, f"{checks} restricciones CHECK de estados y coordenadas" if checks else
                   "Faltan las restricciones CHECK de estados.", None if checks else "python manage.py migrate")
        limite = int(getattr(settings, "DB_LIMITE_MB", 500))
        mb = tamano / 1024 / 1024
        uso = mb / limite * 100
        self.linea(OK if uso < 80 else AVISO, f"Espacio usado: {mb:.0f} MB de {limite} MB del plan ({uso:.0f} %) · "
                                              f"usuario de conexión: {usuario}",
                   None if uso < 80 else "Revisa el plan de Supabase o la retención de datos (ARQUITECTURA_DATOS.md §9).")

    def catalogos(self):
        if not self.bd_ok:
            self.linea(AVISO, "Se omite: sin base de datos.")
            return
        from campo.models import FieldLot, FieldRow, FieldSegment, Marker
        from cuentas.models import AccountStatus, Role, User
        from notificaciones.models import NotificationRecipient

        lotes = FieldLot.objects.filter(active=True).count()
        hileras = FieldRow.objects.count()
        if not lotes:
            self.linea(ERROR, "No hay lotes activos: la app no podrá iniciar sesiones de monitoreo.",
                       "Créalos en /gestion/ o, solo en dev: python manage.py sembrar_demo")
        else:
            self.linea(OK, f"{lotes} lotes activos · {hileras} hileras · {FieldSegment.objects.count()} segmentos · "
                           f"{Marker.objects.count()} marcadores")
            sin_geo = FieldLot.objects.filter(active=True, geometry__isnull=True).count()
            if sin_geo:
                self.linea(AVISO, f"{sin_geo} lotes sin contorno GeoJSON: no se dibujan en el mapa.")
        activos = User.objects.filter(status=AccountStatus.ACTIVO)
        for rol, nombre in [(Role.ADMINISTRADOR, "administradores"), (Role.ESPECIALISTA_FITOSANITARIO, "especialistas")]:
            n = activos.filter(user_roles__role=rol).distinct().count()
            self.linea(OK if n else ERROR, f"{nombre.capitalize()} activos: {n}",
                       None if n else "python manage.py createsuperuser y asigna el rol en /gestion/")
        pendientes = User.objects.filter(status=AccountStatus.PENDIENTE_APROBACION).count()
        if pendientes:
            self.linea(AVISO, f"Cuentas de la app esperando aprobación: {pendientes} (web → Usuarios).")
        if settings.APP_ENV == "piloto" and User.objects.filter(email__endswith="@demo.pe").exists():
            self.linea(ERROR, "Hay cuentas de demostración (@demo.pe) en piloto.", "Bloquéalas o elimínalas.")
        dest = NotificationRecipient.objects.filter(active=True, opt_in_at__isnull=False).count()
        self.linea(OK if dest else AVISO, f"Destinatarios de WhatsApp activos con consentimiento: {dest}",
                   None if dest else "Agrégalos en la web → Destinatarios (jefe de fundo y supervisor de zona).")

    def cloudinary(self):
        from evidencias import nube

        modo = nube.modo()
        if modo == nube.SIN_CONFIGURAR:
            self.linea(ERROR, "CLOUDINARY_URL no está configurado.",
                       "cloudinary://<api_key>:<api_secret>@<cloud_name> (panel de Cloudinary → API Keys)")
            return
        if modo == nube.SIMULADO:
            self.linea(AVISO, "Cloudinary SIMULADO en esta computadora (solo dev): las fotos quedan en media/.",
                       "Para usar Cloudinary real define CLOUDINARY_URL en .env.")
        else:
            import cloudinary

            self.linea(OK, f"Cloudinary real: cloud «{cloudinary.config().cloud_name}» · prefijo "
                           f"{settings.CLOUDINARY_ENV_PREFIX}")
        if not self.bd_ok:
            return
        from evidencias.models import Capture

        captura = Capture.objects.order_by("-captured_at").first()
        if not captura:
            self.linea(OK, "Aún no hay fotos subidas")
            return
        if modo == nube.SIMULADO:
            existe = nube.ruta_simulada(captura.cloudinary_public_id).exists()
            self.linea(OK if existe else AVISO,
                       "La última foto está en el almacenamiento simulado" if existe else
                       "La última foto no está en media/ (datos de demostración: se dibuja una foto de ejemplo)")
            return
        if not self.red:
            return
        import requests

        for variante in ("miniatura", "revision"):
            url = nube.signed_image_url(captura, variante)
            try:
                r = requests.head(url, timeout=15, allow_redirects=True)
            except requests.RequestException as exc:
                self.linea(ERROR, f"No se pudo contactar a Cloudinary: {exc.__class__.__name__}")
                return
            if r.status_code == 200:
                self.linea(OK, f"Transformación «{variante}» responde (foto {captura.pk.hex[:8]})")
            else:
                razon = r.headers.get("x-cld-error", "")[:120]
                self.linea(ERROR, f"La URL «{variante}» respondió {r.status_code} {razon}",
                           f"Crea la transformación con nombre «{variante}» en Cloudinary (Settings → Transformations)"
                           " y verifica que la foto exista.")

    def whatsapp(self):
        cliente = settings.WHATSAPP_CLIENT
        if cliente.endswith("ConsoleClient"):
            nivel = AVISO if settings.APP_ENV == "piloto" else OK
            self.linea(nivel, "WhatsApp en modo consola: los avisos se imprimen en la terminal del worker, no se envían.",
                       "Para enviar: WHATSAPP_CLIENT=notificaciones.whatsapp.CloudApiClient + token y phone id.")
        else:
            faltan = [k for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_GRAPH_VERSION") if not getattr(settings, k)]
            if faltan:
                self.linea(ERROR, f"WhatsApp Cloud API sin {', '.join(faltan)}: los avisos quedarán en ERROR_ENVIO.")
            else:
                self.linea(OK, f"WhatsApp Cloud API · plantilla «{settings.WHATSAPP_TEMPLATE}» "
                               f"({settings.WHATSAPP_TEMPLATE_LANG}) · Graph {settings.WHATSAPP_GRAPH_VERSION}")
                if self.red:
                    self.probar_whatsapp()
        if self.bd_ok:
            from notificaciones.models import Notification, NotificationStatus

            errores = Notification.objects.filter(status=NotificationStatus.ERROR_ENVIO).count()
            pendientes = Notification.objects.filter(status=NotificationStatus.PENDIENTE_ENVIO).count()
            if errores:
                self.linea(AVISO, f"{errores} avisos con error de envío (web → Avisos). Revisa el número del destinatario "
                                  "o la plantilla aprobada en Meta.")
            if pendientes:
                self.linea(AVISO if pendientes > 20 else OK, f"{pendientes} avisos esperando al worker_ia")

    def probar_whatsapp(self):
        import requests

        url = (f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_ID}"
               "?fields=display_phone_number,verified_name")
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}, timeout=15)
        except requests.RequestException as exc:
            self.linea(ERROR, f"No se pudo contactar a Meta: {exc.__class__.__name__}")
            return
        if r.ok:
            d = r.json()
            self.linea(OK, f"Token válido: número {d.get('display_phone_number', '?')} ({d.get('verified_name', '')})")
        else:
            msg = (r.json().get("error", {}) or {}).get("message", "") if "json" in r.headers.get("content-type", "") else ""
            self.linea(ERROR, f"Meta rechazó el token o el phone id ({r.status_code}): {msg[:140]}",
                       "Genera un token permanente de usuario del sistema y revisa WHATSAPP_PHONE_ID.")

    def ia(self):
        detector = settings.IA_DETECTOR
        if detector == "simulado":
            self.linea(ERROR if settings.APP_ENV == "piloto" else AVISO,
                       "Detector SIMULADO: el worker inventa cajas de prueba (solo para desarrollo).",
                       "Con el modelo entrenado: IA_DETECTOR=onnx y MODEL_PATH=<ruta al .onnx>.")
        else:
            ruta = Path(settings.MODEL_PATH)
            if not ruta.exists():
                self.linea(ERROR, f"IA_DETECTOR={detector} pero no existe {ruta}",
                           "Exporta el modelo YOLO a ONNX (yolo export format=onnx) y copia el archivo.")
            else:
                self.linea(OK, f"Pesos del modelo: {ruta.name} ({ruta.stat().st_size / 1e6:.1f} MB)")
        if not self.bd_ok:
            return
        from evidencias.models import ANALYZABLE_QUALITY, Capture
        from ia.inference import cargar_detector
        from ia.models import AiStatus, AiTask, ModelConfig

        activo = ModelConfig.objects.filter(active=True).first()
        if not activo:
            self.linea(ERROR, "No hay un modelo de IA activo: las fotos nuevas no se encolan para análisis.",
                       "Créalo en /gestion/ → Modelos de IA (o python manage.py sembrar_demo en dev).")
        else:
            self.linea(OK, f"Modelo activo {activo.name} v{activo.version} · clases: {', '.join(activo.classes) or '—'}"
                           f" · umbral {activo.conf_threshold} · imgsz {activo.imgsz}")
            if Path(settings.MODEL_PATH).exists() or detector == "simulado":
                t0 = time.perf_counter()
                try:
                    cargar_detector(activo)
                    self.linea(OK, f"El detector «{detector}» carga correctamente ({(time.perf_counter() - t0):.1f} s)")
                except Exception as exc:
                    self.linea(ERROR, f"El detector no carga: {exc}")
        ahora = timezone.now()
        cola = AiTask.objects
        pend = cola.filter(status=AiStatus.PENDIENTE_DE_ANALISIS)
        n_pend = pend.count()
        mas_vieja = pend.order_by("requested_at").values_list("requested_at", flat=True).first()
        if n_pend:
            edad = ahora - mas_vieja
            nivel = AVISO if edad > timedelta(minutes=10) else OK
            self.linea(nivel, f"{n_pend} fotos en cola; la más antigua espera {int(edad.total_seconds() // 60)} min",
                       "¿Está corriendo «python manage.py worker_ia»?" if nivel == AVISO else None)
        else:
            self.linea(OK, "Cola de análisis vacía")
        trabadas = cola.filter(status=AiStatus.EN_ANALISIS, locked_until__lt=ahora).count()
        if trabadas:
            self.linea(AVISO, f"{trabadas} tareas quedaron EN_ANALISIS con el bloqueo vencido (el worker se reinició)."
                              " Se reintentan solas.")
        errores = cola.filter(status=AiStatus.ERROR_DE_ANALISIS, finished_at__gte=ahora - timedelta(days=1)).count()
        if errores:
            ultimo = (cola.filter(status=AiStatus.ERROR_DE_ANALISIS).order_by("-finished_at")
                      .values_list("error_message", flat=True).first() or "")
            self.linea(AVISO, f"{errores} análisis con error en las últimas 24 h. Último: {ultimo[:120]}",
                       "Web → Estado de la IA → Reintentar errores.")
        sin_tarea = (Capture.objects.filter(quality_status__in=ANALYZABLE_QUALITY, ai_tasks__isnull=True).count()
                     if activo else 0)
        if sin_tarea:
            self.linea(AVISO, f"{sin_tarea} fotos utilizables sin tarea de análisis: el worker_ia las encola solo.")

    def estaticos(self):
        base = Path(settings.BASE_DIR) / "web" / "static" / "web"
        faltan = [r for r in ("vendor/htmx.min.js", "vendor/leaflet/leaflet.js", "iconos.svg", "app.js", "app.css",
                              "caso.js", "mapa.js") if not (base / r).exists()]
        if faltan:
            self.linea(ERROR, f"Faltan archivos estáticos: {', '.join(faltan)}")
        else:
            self.linea(OK, "htmx, Leaflet, íconos, estilos y scripts presentes (servidos localmente)")
        if not settings.DEBUG:
            manifest = Path(settings.STATIC_ROOT) / "staticfiles.json"
            if "Manifest" in str(settings.STORAGES["staticfiles"]["BACKEND"]) and not manifest.exists():
                self.linea(ERROR, "Sin DEBUG falta ejecutar collectstatic.", "python manage.py collectstatic --noinput")
