# cuentas/tests/test_editar_cuentas.py — QUÉ HACE: v1.3 (ADR-W-007) prueba que solo el administrador edita datos de
# ingreso y asigna contraseñas a otras cuentas, con validaciones, cierre de sesión en la app y auditoría.
from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import AuditEvent
from cuentas import services as cuentas
from cuentas.models import User
from web.tests import factories as F


class EditarCuenta(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_solo_el_administrador(self):
        for quien in (self.w.esp, self.w.sup, self.w.op):
            with self.assertRaises(PermissionDenied):
                cuentas.update_account(self.w.op.pk, quien, "Otro Nombre", "otro@x.pe")
            with self.assertRaises(PermissionDenied):
                cuentas.set_password_by_admin(self.w.op.pk, quien, "Nueva-Clave-2026")

    def test_edita_datos_y_audita_solo_lo_que_cambia(self):
        user, cambio = cuentas.update_account(self.w.op.pk, self.w.admin, "  Juan   Operador ", " Juan@X.pe ",
                                              "987 654 321", "T-01")
        self.assertTrue(cambio)
        self.assertEqual((user.full_name, user.email, user.phone, user.employee_code),
                         ("Juan Operador", "juan@x.pe", "987654321", "T-01"))
        ev = AuditEvent.objects.get(action="CUENTA_EDITADA")
        self.assertEqual(ev.before["email"], "op@x.pe")
        self.assertEqual(ev.after["email"], "juan@x.pe")
        _, cambio = cuentas.update_account(self.w.op.pk, self.w.admin, "Juan Operador", "juan@x.pe", "987654321",
                                           "T-01")
        self.assertFalse(cambio)
        self.assertEqual(AuditEvent.objects.filter(action="CUENTA_EDITADA").count(), 1)

    def test_correo_repetido_y_celular_invalido(self):
        with self.assertRaises(ValidationError) as ctx:
            cuentas.update_account(self.w.op.pk, self.w.admin, "Juan Operador", "ESP@x.pe", "12")
        self.assertEqual(set(ctx.exception.message_dict), {"email", "phone"})

    def test_cambiar_correo_cierra_la_app(self):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        from rest_framework_simplejwt.tokens import RefreshToken

        RefreshToken.for_user(self.w.op)
        cuentas.update_account(self.w.op.pk, self.w.admin, "Op Campo Uno", "nuevo-op@x.pe")
        self.assertEqual(BlacklistedToken.objects.filter(token__user=self.w.op).count(), 1)

    def test_asignar_contrasena(self):
        cuentas.set_password_by_admin(self.w.op.pk, self.w.admin, "Vid-Ica-2026", must_change=False)
        user = User.objects.get(pk=self.w.op.pk)
        self.assertFalse(user.must_change_password)
        self.assertIsNotNone(authenticate(email="op@x.pe", password="Vid-Ica-2026"))
        ev = AuditEvent.objects.get(action="CONTRASENA_ASIGNADA")
        self.assertNotIn("Vid-Ica-2026", str(ev.after))

    def test_contrasena_debil_o_propia(self):
        with self.assertRaises(ValidationError):
            cuentas.set_password_by_admin(self.w.op.pk, self.w.admin, "12345678")
        with self.assertRaises(ValidationError):
            cuentas.set_password_by_admin(self.w.admin.pk, self.w.admin, "Vid-Ica-2026")


class PantallaEditarCuenta(TestCase):
    def setUp(self):
        self.w = F.world()
        self.c = Client()
        self.c.force_login(self.w.admin)
        self.url = reverse("web:usuario_editar", args=[self.w.esp.pk])

    def test_solo_admin_ve_la_pantalla(self):
        for quien in (self.w.esp, self.w.sup):
            c = Client()
            c.force_login(quien)
            self.assertEqual(c.get(self.url).status_code, 403)
        self.assertContains(self.c.get(self.url), "Asignar contraseña")
        self.assertContains(self.c.get(reverse("web:usuarios")), self.url)

    def test_guardar_datos(self):
        r = self.c.post(self.url, {"guardar_datos": "1", "full_name": "Elena Especialista", "email": "elena@x.pe",
                                   "phone": "", "employee_code": ""}, follow=True)
        self.assertContains(r, "Datos de Elena Especialista guardados")
        self.assertEqual(User.objects.get(pk=self.w.esp.pk).email, "elena@x.pe")

    def test_asignar_contrasena_con_confirmacion(self):
        r = self.c.post(self.url, {"asignar_clave": "1", "password1": "Vid-Ica-2026", "password2": "otra"})
        self.assertContains(r, "Las contraseñas no coinciden")
        r = self.c.post(self.url, {"asignar_clave": "1", "password1": "Vid-Ica-2026", "password2": "Vid-Ica-2026",
                                   "must_change": "on"}, follow=True)
        self.assertContains(r, "Contraseña de")
        self.assertTrue(User.objects.get(pk=self.w.esp.pk).must_change_password)

    def test_propia_cuenta_no_muestra_asignar(self):
        r = self.c.get(reverse("web:usuario_editar", args=[self.w.admin.pk]))
        self.assertNotContains(r, "Asignar contraseña")
