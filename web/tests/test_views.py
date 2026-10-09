import uuid

from django.core.cache import cache
from django.test import Client, TestCase, override_settings  # noqa: F401
from django.urls import URLPattern, reverse

from auditoria.models import AuditEvent
from cuentas.models import AccountStatus, Role, User
from ia.models import AiStatus, AiTask
from monitoreo.models import Incident
from notificaciones.models import NotificationRecipient
from revision import services as rv
from revision.models import Case, ReviewStatus  # noqa: F401
from web import messages as M
from web import urls as web_urls
from web.permissions import PERMISOS
from web.tests import factories as F

PUBLIC = {"login", "logout", "cambiar_contrasena"}
HX = {"HTTP_HX_REQUEST": "true"}


def login(client, user):
    client.force_login(user)
    return client


class Ingreso(TestCase):
    def setUp(self):
        cache.clear()
        self.w = F.world()

    def post(self, email, password=F.PASSWORD):
        return self.client.post(reverse("web:login"), {"email": email, "password": password})

    def test_credenciales_incorrectas_mensaje_generico(self):
        for email in ("esp@x.pe", "noexiste@x.pe"):
            r = self.post(email, "mala")
            self.assertContains(r, M.LOGIN_INVALIDO)

    def test_estado_de_cuenta_solo_con_contrasena_correcta(self):
        F.user("pend@x.pe", status=AccountStatus.PENDIENTE_APROBACION)
        self.assertContains(self.post("pend@x.pe", "mala"), M.LOGIN_INVALIDO)
        self.assertContains(self.post("pend@x.pe"), M.CUENTA_PENDIENTE)

    def test_operador_no_entra_a_la_web(self):
        self.assertContains(self.post("op@x.pe"), M.SIN_ACCESO_WEB)

    def test_bloqueo_tras_intentos_fallidos(self):
        for _ in range(5):
            self.post("esp@x.pe", "mala")
        self.assertContains(self.post("esp@x.pe"), "Demasiados intentos")

    def test_ingreso_y_redireccion(self):
        r = self.post("esp@x.pe")
        self.assertRedirects(r, reverse("web:dashboard"))
        self.assertTrue(AuditEvent.objects.filter(action="INGRESO_WEB").exists())

    def test_contrasena_temporal_obliga_a_cambiarla(self):
        self.w.sup.must_change_password = True
        self.w.sup.save()
        self.assertRedirects(self.post("sup@x.pe"), reverse("web:cambiar_contrasena"))
        r = self.client.get(reverse("web:bandeja"))
        self.assertRedirects(r, reverse("web:cambiar_contrasena"))
        r = self.client.post(reverse("web:cambiar_contrasena"), {
            "old_password": F.PASSWORD, "new_password1": "Otra-clave-larga-77", "new_password2": "Otra-clave-larga-77"})
        self.assertRedirects(r, reverse("web:dashboard"))
        self.w.sup.refresh_from_db()
        self.assertFalse(self.w.sup.must_change_password)

    def test_bloquear_cuenta_cierra_la_sesion_web(self):
        login(self.client, self.w.sup)
        self.assertEqual(self.client.get(reverse("web:bandeja")).status_code, 200)
        User.objects.filter(pk=self.w.sup.pk).update(status=AccountStatus.BLOQUEADO)
        r = self.client.get(reverse("web:bandeja"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("web:login"), r["Location"])

    def test_next_no_permite_redireccion_externa(self):
        r = self.client.post(reverse("web:login") + "?next=https://malo.example.com/",
                             {"email": "esp@x.pe", "password": F.PASSWORD})
        self.assertRedirects(r, reverse("web:dashboard"))


class MatrizDePermisos(TestCase):
    """W-07: toda vista de la web (salvo ingreso/salida/contraseña) tiene @web_view y respeta la matriz 7.2."""

    def setUp(self):
        self.w = F.world()
        self.cap, self.task, self.case = F.analyzed(self.w)

    def test_todas_las_rutas_estan_protegidas(self):
        for p in web_urls.urlpatterns:
            assert isinstance(p, URLPattern)
            if p.name in PUBLIC:
                continue
            self.assertIn(getattr(p.callback, "web_permission", None), PERMISOS, f"{p.name} sin @web_view")

    def test_paginas_por_rol(self):
        pages = {
            "web:dashboard": [], "web:bandeja": [], "web:caso": [self.case.pk], "web:captura": [self.cap.pk],
            "web:mapa": [], "web:mapa_datos": [], "web:plano": [], "web:sesiones": [], "web:sesion": [self.w.session.pk],
            "web:reportes": [], "web:exportar_casos": [], "web:notificaciones": [], "web:ia": [],
            "web:usuarios": [], "web:dispositivos": [], "web:destinatarios": [], "web:auditoria": [],
            "web:catalogos": [], "web:catalogo_lote": [self.w.lot.pk], "web:catalogo_hilera": [self.w.row.pk],
        }
        for name, args in pages.items():
            perm = getattr(reverse_view(name), "web_permission")
            for user in (self.w.admin, self.w.esp, self.w.sup):
                c = login(Client(), user)
                r = c.get(reverse(name, args=args))
                expected = 200 if user.has_role(*PERMISOS[perm]) else 403
                self.assertEqual(r.status_code, expected, f"{name} {user.email}")

    def test_anonimo_va_al_login_y_htmx_recibe_redireccion_de_cliente(self):
        r = self.client.get(reverse("web:bandeja"))
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("web:bandeja"), **HX, HTTP_HX_CURRENT_URL="http://testserver/casos/?lote=SWG1")
        self.assertIn("/ingresar/?next=", r["HX-Redirect"])

    def test_decidir_solo_especialista(self):
        for user in (self.w.sup, self.w.admin):
            r = login(Client(), user).post(reverse("web:caso_decidir", args=[self.case.pk]), {"decision": "DESCARTADO"})
            self.assertEqual(r.status_code, 403)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, ReviewStatus.PENDIENTE_REVISION)


def reverse_view(name):
    from django.urls import resolve

    sample = {"web:caso": [uuid.uuid4()], "web:captura": [uuid.uuid4()], "web:sesion": [uuid.uuid4()],
              "web:catalogo_lote": ["X"], "web:catalogo_hilera": ["X"]}
    return resolve(reverse(name, args=sample.get(name, []))).func


class BandejaYCaso(TestCase):
    def setUp(self):
        self.w = F.world()
        self.cases = [F.analyzed(self.w)[2] for _ in range(3)]
        rv.decide_case(self.cases[2].pk, self.w.esp, ReviewStatus.DESCARTADO, "")
        self.c = login(Client(), self.w.esp)

    def test_bandeja_muestra_pendientes_por_defecto(self):
        r = self.c.get(reverse("web:bandeja"))
        self.assertEqual(r.context["page"].paginator.count, 2)
        r = self.c.get(reverse("web:bandeja"), {"estado": ""})
        self.assertEqual(r.context["page"].paginator.count, 3)

    def test_htmx_devuelve_solo_el_fragmento_que_se_reemplaza_a_si_mismo(self):
        r = self.c.get(reverse("web:bandeja"), {"lote": "SWG1"}, **HX)
        html = r.content.decode()
        self.assertNotIn("<html", html)
        self.assertIn('id="bandeja"', html)
        self.assertIn('hx-get="/casos/?lote=SWG1"', html)
        self.assertIn("HX-Request", r["Vary"])

    def test_bandeja_sin_consultas_n_mas_1(self):
        # 6 consultas fijas: sesión, usuario, roles, conteo, página de casos (con select_related) y lotes del filtro
        with self.assertNumQueries(6):
            self.c.get(reverse("web:bandeja"), {"estado": ""})
        for _ in range(5):
            F.analyzed(self.w)
        with self.assertNumQueries(6):
            self.c.get(reverse("web:bandeja"), {"estado": ""})

    def _queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.c.get(reverse("web:bandeja"), {"estado": ""})
        return len(ctx.captured_queries)

    def test_caso_con_url_firmada_y_cajas_en_coordenadas_del_analisis(self):
        case = self.cases[0]
        r = self.c.get(reverse("web:caso", args=[case.pk]))
        html = r.content.decode()
        self.assertIn("/image/authenticated/s--", html)
        self.assertIn("/c_limit,q_auto,w_1600/", html)
        self.assertNotIn("secreto-de-prueba", html)  # nunca el API secret
        self.assertIn('viewBox="0 0 3000 4000"', html)
        self.assertIn('<rect class="caja ', html)
        self.assertIn(M.IA_AVISO, html)
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(r["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_decision_htmx_ok_redirige_y_avisa(self):
        F.recipient()
        case = self.cases[0]
        r = self.c.post(reverse("web:caso_decidir", args=[case.pk]),
                        {"decision": "CONFIRMADO_POR_ESPECIALISTA", "observation": "Colonias"}, **HX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["HX-Redirect"], reverse("web:caso", args=[case.pk]))
        case.refresh_from_db()
        self.assertEqual(case.status, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA)

    def test_guardar_y_siguiente(self):
        r = self.c.post(reverse("web:caso_decidir", args=[self.cases[0].pk]), {"decision": "DESCARTADO", "siguiente": "1"},
                        **HX)
        self.assertEqual(r["HX-Redirect"], reverse("web:caso", args=[self.cases[1].pk]))

    def test_decision_invalida_422_con_errores_en_el_fragmento(self):
        r = self.c.post(reverse("web:caso_decidir", args=[self.cases[0].pk]),
                        {"decision": "CONFIRMADO_POR_ESPECIALISTA", "observation": ""}, **HX)
        self.assertEqual(r.status_code, 422)
        self.assertIn('id="panel-decision"', r.content.decode())
        self.assertContains(r, "Registra la observación fitosanitaria.", status_code=422)

    def test_caso_ya_decidido_409(self):
        rv.decide_case(self.cases[0].pk, self.w.esp2, ReviewStatus.DESCARTADO, "")
        r = self.c.post(reverse("web:caso_decidir", args=[self.cases[0].pk]),
                        {"decision": "CONFIRMADO_POR_ESPECIALISTA", "observation": "x"}, **HX)
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "ya fue decidido por Esp2", status_code=409)

    def test_csrf_obligatorio(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.w.esp)
        r = c.post(reverse("web:caso_decidir", args=[self.cases[0].pk]), {"decision": "DESCARTADO"})
        self.assertEqual(r.status_code, 403)

    def test_supervisor_ve_el_caso_sin_formulario(self):
        r = login(Client(), self.w.sup).get(reverse("web:caso", args=[self.cases[0].pk]))
        self.assertNotContains(r, 'id="form-decision"')
        self.assertContains(r, "solo el especialista fitosanitario puede decidir")


class MapaPlanoPanelExportacion(TestCase):
    def setUp(self):
        self.w = F.world()
        self.gps = F.analyzed(self.w)[2]
        self.aprox = F.analyzed(self.w, gps=False)[2]
        self.nada = F.analyzed(self.w, gps=False, marker=False)[2]
        self.c = login(Client(), self.w.sup)

    def test_geojson(self):
        data = self.c.get(reverse("web:mapa_datos")).json()
        self.assertEqual(data["type"], "FeatureCollection")
        props = {f["properties"]["id"]: f for f in data["features"]}
        self.assertEqual(set(props), {str(self.gps.pk), str(self.aprox.pk)})
        self.assertEqual(props[str(self.gps.pk)]["geometry"]["coordinates"], [-75.7302, -14.0601])  # [lon, lat]
        self.assertEqual(props[str(self.aprox.pk)]["properties"]["locationSource"], "MARCADOR")
        self.assertEqual(data["meta"]["sinUbicacion"], 1)
        data = self.c.get(reverse("web:mapa_datos"), {"estado": "DESCARTADO"}).json()
        self.assertEqual(data["features"], [])

    def test_plano_cuenta_casos_y_cobertura(self):
        F.make_pass(self.w, self.w.row, "LATERAL_B", status="INCOMPLETE")
        r = self.c.get(reverse("web:plano"), {"lote": "SWG1"})
        p = r.context["p"]
        fila = next(x for x in p["rows"] if x["row"].number == 5)
        self.assertEqual(fila["counts"], {"PENDIENTE_REVISION": 3})
        self.assertEqual(fila["segments"][0]["counts"], {"PENDIENTE_REVISION": 2})  # uno quedó sin segmento
        self.assertFalse(fila["covered"])  # LATERAL_B INCOMPLETE sin incidencia no cubre (RN-13)
        Incident.objects.create(incident_id=uuid.uuid4(), session=self.w.session,
                                monitoring_pass=self.w.session.passes.get(lateral_code="LATERAL_B"),
                                type="OPERADOR", severity="AVISO", detail="Riego",
                                occurred_at=self.w.session.started_at, created_by="OPERADOR")
        p = self.c.get(reverse("web:plano"), {"lote": "SWG1"}).context["p"]
        self.assertTrue(next(x for x in p["rows"] if x["row"].number == 5)["covered"])
        self.assertEqual(p["covered"], 1)

    def test_panel(self):
        k = self.c.get(reverse("web:dashboard")).context["k"]
        self.assertEqual((k["pendientes"], k["capturas"], k["casos"]["PENDIENTE_REVISION"]), (3, 3, 3))
        self.assertEqual(k["ia"]["INDICIO_SUGERIDO_POR_IA"], 3)

    def test_csv_utf8_con_bom_y_sin_inyeccion_de_formulas(self):
        self.w.marker.code = "=HYPERLINK(\"http://x\")"
        self.w.marker.save()
        r = self.c.get(reverse("web:exportar_casos"))
        body = b"".join(r.streaming_content).decode("utf-8")
        self.assertTrue(body.startswith("﻿caso,estado") or body.startswith("caso,estado"))
        self.assertIn("'=HYPERLINK", body)
        self.assertEqual(len(body.strip().splitlines()), 4)
        self.assertTrue(AuditEvent.objects.filter(action="EXPORTACION_CASOS").exists())


class Administracion(TestCase):
    def setUp(self):
        self.w = F.world()
        self.c = login(Client(), self.w.admin)

    def test_aprobar_cuenta_con_roles(self):
        nuevo = F.user("nuevo@x.pe", status=AccountStatus.PENDIENTE_APROBACION)
        r = self.c.post(reverse("web:usuario_accion", args=[nuevo.pk, "aprobar"]), {"roles": [Role.SUPERVISOR]})
        self.assertRedirects(r, reverse("web:usuarios"))
        nuevo = User.objects.get(pk=nuevo.pk)
        self.assertEqual((nuevo.status, set(nuevo.roles), nuevo.approved_by),
                         (AccountStatus.ACTIVO, {Role.SUPERVISOR}, self.w.admin))

    def test_contrasena_temporal_revoca_la_app(self):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        from rest_framework_simplejwt.tokens import RefreshToken

        RefreshToken.for_user(self.w.op)  # sesión abierta en un celular
        r = self.c.post(reverse("web:usuario_accion", args=[self.w.op.pk, "contrasena-temporal"]), follow=True)
        self.assertContains(r, "Contraseña temporal de")
        self.w.op.refresh_from_db()
        self.assertTrue(self.w.op.must_change_password)
        self.assertEqual(BlacklistedToken.objects.filter(token__user=self.w.op).count(), 1)

    def test_contrasena_temporal_cumple_la_politica(self):
        from django.contrib.auth.password_validation import validate_password

        from cuentas import services as cuentas

        for _ in range(20):
            validate_password(cuentas.set_temporary_password(self.w.op.pk, self.w.admin), self.w.op)

    def test_politica_igual_a_la_app(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        for mala in ("solo-letras-largas", "12345678", " Clave123", "corta1"):
            with self.assertRaises(ValidationError, msg=mala):
                validate_password(mala)
        validate_password("Vid-Ica-2026")

    def test_cambiar_roles_y_atender_pedido_por_correo(self):
        from cuentas.models import PasswordResetRequest

        r = self.c.post(reverse("web:usuario_accion", args=[self.w.sup.pk, "roles"]),
                        {"roles": [Role.SUPERVISOR, Role.ESPECIALISTA_FITOSANITARIO]})
        self.assertRedirects(r, reverse("web:usuarios"))
        self.assertEqual(set(User.objects.get(pk=self.w.sup.pk).roles), {Role.SUPERVISOR, Role.ESPECIALISTA_FITOSANITARIO})
        self.assertTrue(AuditEvent.objects.filter(action="ROLES_CAMBIADOS").exists())
        pedido = PasswordResetRequest.objects.create(email="SUP@x.pe")  # la API puede guardar solo el correo
        self.c.post(reverse("web:usuario_accion", args=[self.w.sup.pk, "contrasena-temporal"]))
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, PasswordResetRequest.Status.ATENDIDA)

    def test_no_puede_bloquearse_a_si_mismo(self):
        r = self.c.post(reverse("web:usuario_accion", args=[self.w.admin.pk, "bloquear"]), follow=True)
        self.assertContains(r, "No puedes cambiar el estado de tu propia cuenta")

    # ------------------------------------------------------------ v1.1 (ADR-W-005): alta de cuentas y tipos de cuenta
    def nueva(self, **datos):
        base = {"tipo": "WEB", "full_name": "Elena Especialista", "email": "elena@x.pe", "phone": "", "employee_code": ""}
        base.update(datos)
        return self.c.post(reverse("web:usuario_nuevo"), base, follow=True)

    def test_pagina_de_usuarios_muestra_nueva_cuenta_y_reglas(self):
        r = self.c.get(reverse("web:usuarios"))
        self.assertContains(r, 'id="nueva-cuenta"')
        self.assertContains(r, "Reglas de las cuentas")
        self.assertContains(r, reverse("web:usuario_nuevo"))

    def test_nueva_cuenta_web_con_contrasena_temporal(self):
        import re

        r = self.nueva(email="Elena@X.pe", phone="987 654 321", employee_code="E-01",
                       roles=[Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR])
        self.assertRedirects(r, reverse("web:usuarios"))
        nueva = User.objects.get(email="elena@x.pe")
        self.assertEqual((nueva.status, nueva.must_change_password, nueva.approved_by, nueva.phone),
                         (AccountStatus.ACTIVO, True, self.w.admin, "987654321"))
        self.assertEqual(set(nueva.roles), {Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR})
        evento = AuditEvent.objects.get(action="CUENTA_CREADA", entity_id=str(nueva.pk))
        self.assertEqual((evento.user, evento.after["tipo"]), (self.w.admin, "WEB"))
        clave = re.search(r"Contraseña temporal: (\S+) —", r.content.decode()).group(1)
        self.assertNotIn(clave, str(evento.after))  # la contraseña nunca queda en la auditoría
        # Entra a la web con la temporal y se le exige cambiarla antes de ver cualquier página.
        c = Client()
        self.assertRedirects(c.post(reverse("web:login"), {"email": "elena@x.pe", "password": clave}),
                             reverse("web:cambiar_contrasena"))
        self.assertContains(c.get(reverse("web:cambiar_contrasena")), "Contraseña temporal (la que te entregó")
        self.assertRedirects(c.get(reverse("web:bandeja")), reverse("web:cambiar_contrasena"))

    def test_nueva_cuenta_de_la_app_es_solo_operador(self):
        from cuentas import services as cuentas

        r = self.nueva(tipo="APP", full_name="Pedro Operador", email="pedro@x.pe")
        self.assertContains(r, "Es una cuenta de la app móvil")
        pedro = User.objects.get(email="pedro@x.pe")
        self.assertEqual(set(pedro.roles), {Role.OPERADOR_CAMPO})
        cuentas.ensure_app_access(pedro)  # puede usar la app…
        clave = cuentas.set_temporary_password(pedro.pk, self.w.admin)
        r = Client().post(reverse("web:login"), {"email": "pedro@x.pe", "password": clave})
        self.assertContains(r, M.SIN_ACCESO_WEB)  # …pero no la web

    def test_nueva_cuenta_de_la_app_no_acepta_roles_de_la_web(self):
        r = self.nueva(tipo="APP", email="mixto@x.pe", roles=[Role.SUPERVISOR])
        self.assertContains(r, "no lleva roles de la web")
        self.assertFalse(User.objects.filter(email="mixto@x.pe").exists())

    def test_nueva_cuenta_web_exige_un_rol_y_datos_validos(self):
        r = self.nueva(full_name="Ana", phone="123")
        self.assertContains(r, "Elige al menos un rol de la web.")
        r = self.nueva(full_name="Ana", phone="123", roles=[Role.SUPERVISOR])
        self.assertContains(r, "Escribe el nombre completo.")
        self.assertContains(r, "Escribe un celular válido")
        self.assertFalse(User.objects.filter(email="elena@x.pe").exists())

    def test_nueva_cuenta_con_correo_existente(self):
        r = self.nueva(email="ESP@x.pe", roles=[Role.SUPERVISOR])
        self.assertContains(r, "Ya existe una cuenta con ese correo.")
        F.user("pend@x.pe", status=AccountStatus.PENDIENTE_APROBACION)
        r = self.nueva(email="pend@x.pe", roles=[Role.SUPERVISOR])
        self.assertContains(r, "Solicitudes pendientes")
        self.assertEqual(User.objects.filter(email__iexact="esp@x.pe").count(), 1)

    def test_solo_el_administrador_crea_cuentas(self):
        for user in (self.w.esp, self.w.sup):
            r = login(Client(), user).post(reverse("web:usuario_nuevo"), {
                "tipo": "WEB", "full_name": "Intruso Prueba", "email": "intruso@x.pe", "roles": [Role.ADMINISTRADOR]})
            self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(email="intruso@x.pe").exists())

    def test_operador_no_se_combina_con_roles_de_la_web(self):
        nuevo = F.user("mix@x.pe", status=AccountStatus.PENDIENTE_APROBACION)
        r = self.c.post(reverse("web:usuario_accion", args=[nuevo.pk, "aprobar"]),
                        {"roles": [Role.OPERADOR_CAMPO, Role.ESPECIALISTA_FITOSANITARIO]}, follow=True)
        self.assertContains(r, "va solo")
        nuevo = User.objects.get(pk=nuevo.pk)
        self.assertEqual((nuevo.status, set(nuevo.roles)), (AccountStatus.PENDIENTE_APROBACION, set()))
        r = self.c.post(reverse("web:usuario_accion", args=[self.w.op.pk, "roles"]),
                        {"roles": [Role.OPERADOR_CAMPO, Role.SUPERVISOR]}, follow=True)
        self.assertContains(r, "va solo")
        self.assertEqual(set(User.objects.get(pk=self.w.op.pk).roles), {Role.OPERADOR_CAMPO})

    def test_django_admin_no_crea_usuarios(self):
        from django.contrib import admin

        self.assertFalse(admin.site._registry[User].has_add_permission(None))

    def test_destinatario_con_consentimiento(self):
        r = self.c.post(reverse("web:destinatarios"), {"full_name": "Jefe", "phone_e164": "+51987654321",
                                                       "role_label": "JEFE_FUNDO", "lots": ["SWG1"], "active": "on",
                                                       "opt_in": "on"})
        self.assertRedirects(r, reverse("web:destinatarios"))
        dest = NotificationRecipient.objects.get()
        self.assertIsNotNone(dest.opt_in_at)
        r = self.c.post(reverse("web:destinatarios"), {"full_name": "Malo", "phone_e164": "987654321",
                                                       "role_label": "OTRO"})
        self.assertContains(r, "formato internacional")

    def test_reencolar_error_de_ia(self):
        cap = F.capture(self.w)
        from ia import services as ia

        task = ia.enqueue_analysis(cap)
        AiTask.objects.filter(pk=task.pk).update(status=AiStatus.ERROR_DE_ANALISIS)
        self.assertEqual(login(Client(), self.w.esp).post(reverse("web:ia_reencolar", args=[task.pk])).status_code, 403)
        self.c.post(reverse("web:ia_reencolar", args=[task.pk]))
        task.refresh_from_db()
        self.assertEqual(task.status, AiStatus.PENDIENTE_DE_ANALISIS)

    def test_revocar_celular(self):
        self.c.post(reverse("web:dispositivo_revocar", args=[self.w.device.pk]))
        self.w.device.refresh_from_db()
        self.assertIsNotNone(self.w.device.revoked_at)


class Catalogos(TestCase):
    """v1.2 (ADR-W-006): Administración → Catálogos."""

    def setUp(self):
        self.w = F.world()
        self.c = login(Client(), self.w.sup)  # el supervisor también gestiona catálogos

    def test_crear_lote_y_hileras_desde_la_web(self):
        from campo.models import FieldLot, FieldRow, FieldSegment

        r = self.c.post(reverse("web:catalogos"), {"code": "SWG 4", "name": "Lote 4 (Norte)"})
        self.assertRedirects(r, reverse("web:catalogo_lote", args=["SWG4"]))
        r = self.c.post(reverse("web:catalogo_lote", args=["SWG4"]), {
            "accion": "hileras", "desde": 1, "hasta": 3, "plantas": 250, "segmento_completo": "on"}, follow=True)
        self.assertContains(r, "Se crearon 3 hilera(s).")
        self.assertEqual(FieldRow.objects.filter(lot_id="SWG4").count(), 3)
        self.assertEqual(FieldSegment.objects.filter(row__lot_id="SWG4", active=True).count(), 3)
        self.assertTrue(FieldLot.objects.get(pk="SWG4").active)

    def test_errores_vuelven_al_formulario(self):
        r = self.c.post(reverse("web:catalogo_lote", args=[self.w.lot.pk]), {
            "accion": "hileras", "desde": 9, "hasta": 2, "plantas": 100})
        self.assertContains(r, "no puede ser menor")
        r = self.c.post(reverse("web:catalogo_hilera", args=[self.w.row.pk]), {
            "accion": "segmento_nuevo", "code": "S9", "start_plant": 190, "end_plant": 220})
        self.assertContains(r, "Se cruza con el segmento")

    def test_dividir_desactivar_y_reactivar(self):
        from campo.models import FieldSegment

        url = reverse("web:catalogo_hilera", args=[self.w.row.pk])
        r = self.c.post(url, {"accion": "dividir", "modo": "partes", "valor": 2, "con_marcadores": "on"}, follow=True)
        self.assertContains(r, "Cambios guardados")
        self.assertEqual(FieldSegment.objects.filter(row=self.w.row, active=True).count(), 2)
        r = self.c.post(url, {"accion": "desactivar", "tipo": "hilera", "id": self.w.row.pk}, follow=True)
        self.assertContains(r, "Desactivado")
        r = self.c.post(url, {"accion": "desactivar", "tipo": "segmento", "id": "SWG2-OTRA"})
        self.assertEqual(r.status_code, 404)  # solo elementos de esta hilera

    def test_permisos(self):
        for user, esperado in ((self.w.admin, 200), (self.w.sup, 200), (self.w.esp, 403)):
            self.assertEqual(login(Client(), user).get(reverse("web:catalogos")).status_code, esperado)
        r = login(Client(), self.w.esp).post(reverse("web:catalogos"), {"code": "X 1", "name": "X"})
        self.assertEqual(r.status_code, 403)

    def test_plano_sigue_contando_casos_de_segmentos_desactivados(self):
        from campo import services as cat

        _, _, case = F.analyzed(self.w)
        cat.desactivar(self.w.admin, "segmento", case.segment_id)
        r = login(Client(), self.w.esp).get(reverse("web:plano"), {"lote": self.w.lot.pk})
        fila = next(x for x in r.context["p"]["rows"] if x["row"].pk == case.row_id)
        self.assertEqual(sum(fila["counts"].values()), 1)
        self.assertEqual(fila["segments"], [])

    def test_django_admin_no_borra_catalogos(self):
        from django.contrib import admin

        from campo.models import FieldLot, FieldRow, FieldSegment, Marker

        for model in (FieldLot, FieldRow, FieldSegment, Marker):
            self.assertFalse(admin.site._registry[model].has_delete_permission(None))
