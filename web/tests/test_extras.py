# web/tests/test_extras.py — v1.0+: actividad en vivo, reporte de errores del navegador, diagnóstico, datos demo y
# reglas de frontend del Maestro Web que se pueden verificar leyendo las plantillas (W-01 sin CDN, W-17 sin JS en línea).
import json
import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from auditoria import services as audit
from cuentas.models import User
from web.tests import factories as F

PLANTILLAS = Path(settings.BASE_DIR) / "web" / "templates"
ESTATICOS = Path(settings.BASE_DIR) / "web" / "static" / "web"


class ActividadEnVivo(TestCase):
    def setUp(self):
        self.w = F.world()

    def get(self, user, desde=None):
        c = Client()
        c.force_login(user)
        return c.get(reverse("web:actividad"), {} if desde is None else {"desde": desde}, HTTP_HX_REQUEST="true",
                     HTTP_HX_TRIGGER="actividad-poll")

    def test_primer_sondeo_solo_marca_el_punto_de_partida(self):
        audit.record("session", self.w.session.pk, "SESION_RECIBIDA", self.w.op, None, {"status": "ACTIVE"})
        r = self.get(self.w.esp)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "data-evento=")
        self.assertContains(r, 'id="actividad-poll"')

    def test_sondeo_trae_eventos_nuevos_y_pendientes(self):
        ultimo = self.get(self.w.esp).content.decode()
        desde = re.search(r'data-ultimo="(\d+)"', ultimo).group(1)
        audit.record("session", self.w.session.pk, "SESION_RECIBIDA", self.w.op, None, {"status": "ACTIVE"})
        F.analyzed(self.w)  # abre un caso (CASO_ABIERTO)
        r = self.get(self.w.esp, desde)
        html = r.content.decode()
        self.assertEqual(html.count("data-evento="), 2)
        self.assertIn(reverse("web:sesion", args=[self.w.session.pk]), html)
        self.assertIn('data-pendientes="1"', html)

    def test_eventos_de_cuentas_solo_para_administradores(self):
        desde = re.search(r'data-ultimo="(\d+)"', self.get(self.w.admin).content.decode()).group(1)
        nuevo = F.user("nuevo@x.pe")
        audit.record("user", nuevo.pk, "CUENTA_REGISTRADA", None, None, {"status": "PENDIENTE_APROBACION"})
        audit.record("user", self.w.op.pk, "INGRESO_APP", self.w.op, None, {"model": "Moto"})
        self.assertEqual(self.get(self.w.admin, desde).content.decode().count("data-evento="), 2)
        self.assertEqual(self.get(self.w.esp, desde).content.decode().count("data-evento="), 0)


class ErroresDelNavegador(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_error_queda_en_la_consola_del_servidor(self):
        c = Client()
        c.force_login(self.w.esp)
        with self.assertLogs("riachuelo.navegador", "ERROR") as logs:
            r = c.post(reverse("diagnostico:error_cliente"), json.dumps({
                "tipo": "javascript", "mensaje": "x is not defined", "pagina": "/casos/", "detalle": "app.js:10"}),
                content_type="application/json")
        self.assertEqual(r.status_code, 204)
        self.assertIn("esp@x.pe", logs.output[0])
        self.assertIn("x is not defined", logs.output[0])

    def test_exige_csrf_y_limita_por_ip(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse("diagnostico:error_cliente"), "{}", content_type="application/json").status_code,
                         403)
        c = Client()
        with self.assertLogs("riachuelo.navegador", "WARNING"):
            for _ in range(35):
                c.post(reverse("diagnostico:error_cliente"), json.dumps({"tipo": "foto", "mensaje": "no cargó"}),
                       content_type="application/json")


class Operacion(TestCase):
    def test_diagnostico_sin_errores_con_datos_de_prueba(self):
        F.world()
        out = StringIO()
        call_command("diagnostico", "--sin-color", stdout=out)
        texto = out.getvalue()
        self.assertIn("Base de datos", texto)
        self.assertIn("Migraciones al día", texto)
        self.assertIn("0 errores", texto)

    def test_diagnostico_falla_sin_especialistas(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("diagnostico", "--sin-color", stdout=out)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("No hay lotes activos", out.getvalue())

    def test_sembrar_demo_prohibido_en_piloto(self):
        with override_settings(APP_ENV="piloto"), self.assertRaises(CommandError):
            call_command("sembrar_demo", stdout=StringIO())

    def test_sembrar_demo_solo_catalogos_es_idempotente(self):
        call_command("sembrar_demo", "--solo-catalogos", stdout=StringIO())
        call_command("sembrar_demo", "--solo-catalogos", stdout=StringIO())
        self.assertFalse(User.objects.exists())

    def test_salud_y_paginas_publicas(self):
        c = Client()
        self.assertEqual(c.get(reverse("web:login")).status_code, 200)
        r = c.get("/no-existe/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Agrícola Riachuelo", status_code=404)


class ReglasDeFrontend(TestCase):
    """Comprobaciones estáticas de las plantillas y scripts (se ejecutan en milisegundos)."""

    def plantillas(self):
        return [(p, p.read_text(encoding="utf-8")) for p in PLANTILLAS.rglob("*.html")]

    def test_w01_sin_cdn_ni_recursos_externos(self):
        externo = re.compile(r'(?:src|href)="(?:https?:)?//(?!www\.google\.com/maps)', re.I)
        for path, html in self.plantillas():
            self.assertIsNone(externo.search(html), f"{path.name} carga un recurso externo")

    def test_w17_sin_javascript_en_linea(self):
        en_linea = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>|\son[a-z]+\s*=\s*\"", re.I)
        for path, html in self.plantillas():
            self.assertIsNone(en_linea.search(html), f"{path.name} tiene JavaScript en línea")

    def test_scripts_y_estilos_referenciados_existen(self):
        for path, html in self.plantillas():
            for ref in re.findall(r"\{% static '([^']+)' %\}", html):
                self.assertTrue((Path(settings.BASE_DIR) / "web" / "static" / ref).exists(), f"{path.name}: falta {ref}")

    def test_iconos_usados_existen_en_el_sprite(self):
        sprite = (ESTATICOS / "iconos.svg").read_text(encoding="utf-8")
        definidos = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', sprite))
        usados = set()
        for _, html in self.plantillas():
            usados |= set(re.findall(r'\{% icono "([a-z0-9-]+)"', html))
        for js in ESTATICOS.glob("*.js"):
            usados |= set(re.findall(r'icono\("([a-z0-9-]+)"\)', js.read_text(encoding="utf-8")))
        from web.templatetags.web_tags import ICONO_EVENTO

        usados |= set(ICONO_EVENTO.values()) | {"actividad"}
        self.assertEqual(usados - definidos, set())

    def test_sin_almacenamiento_de_secretos_en_el_navegador(self):
        for js in ESTATICOS.glob("*.js"):
            texto = js.read_text(encoding="utf-8")
            self.assertNotIn("api_secret", texto)
            self.assertNotRegex(texto, r"localStorage\.setItem\([^)]*(token|clave|password)", js.name)


class ConexionBaseDeDatos(SimpleTestCase):
    """diagnostico/bd.py: errores de DATABASE_URL explicados sin mostrar la contraseña."""

    def test_errores_de_supabase_en_lenguaje_claro(self):
        from diagnostico import bd

        error = Exception('connection failed: connection to server at "44.238.118.41", port 5432 failed: FATAL:  '
                          'password authentication failed for user "postgres"')
        self.assertIn("contraseña", bd.explicar_error(error)[0])
        self.assertIn("usuario", bd.explicar_error(Exception("FATAL: Tenant or user not found"))[0])

    def test_url_revisada_antes_de_conectar_sin_revelar_la_clave(self):
        from diagnostico import bd

        url = "postgresql://postgres:Secreta123@aws-0-us-west-2.pooler.supabase.com:6543/postgres"
        self.assertNotIn("Secreta123", bd.resumen_seguro(url))
        textos = " ".join(t for t, _ in bd.problemas_de_url(url))
        self.assertIn("postgres.<id-del-proyecto>", textos)
        self.assertIn("6543", textos)
        self.assertTrue(bd.problemas_de_url("postgresql://postgres.abc:[YOUR-PASSWORD]@h.pooler.supabase.com:5432/postgres"))
        self.assertEqual(bd.problemas_de_url("postgresql://postgres.abc:Clave123@aws-0-sa-east-1.pooler.supabase.com:5432/"
                                             "postgres"), [])
