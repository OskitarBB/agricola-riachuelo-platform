# cuentas/tests/test_reglas_cuentas.py — v1.1 (ADR-W-005): tipos de cuenta y alta desde la web, a nivel de servicio.
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from api.errors import ApiError
from cuentas import services as cuentas
from cuentas.models import AccountStatus, Role, User
from web.tests import factories as F

A, E, S, O = Role.ADMINISTRADOR, Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR, Role.OPERADOR_CAMPO


class TiposDeCuenta(TestCase):
    def test_combinaciones_validas(self):
        for roles in ({O}, {E}, {S}, {A}, {E, S}, {E, A}, {A, E, S}):
            self.assertEqual(cuentas.validate_roles(roles), roles)

    def test_combinaciones_invalidas(self):
        for roles in (set(), {"JARDINERO"}, {O, E}, {O, S}, {O, A}):
            with self.assertRaises(ValidationError, msg=str(roles)):
                cuentas.validate_roles(roles)

    def test_tipo_de_cuenta(self):
        self.assertEqual(cuentas.account_kind({O}), "APP")
        self.assertEqual(cuentas.account_kind({E, S}), "WEB")
        self.assertEqual(cuentas.account_kind({A}), "WEB_Y_APP")


class AltaDeCuentas(TestCase):
    def setUp(self):
        self.w = F.world()

    def test_solo_el_administrador(self):
        with self.assertRaises(PermissionDenied):
            cuentas.create_account(self.w.esp, "Nombre Completo", "nuevo@x.pe", [S])

    def test_crea_cuenta_activa_con_temporal(self):
        user, clave = cuentas.create_account(self.w.admin, "  Rosa   María  Supervisora ", " Rosa@X.PE ", [S])
        self.assertEqual((user.email, user.full_name, user.status, user.must_change_password),
                         ("rosa@x.pe", "Rosa María Supervisora", AccountStatus.ACTIVO, True))
        self.assertTrue(user.check_password(clave))
        validate_password(clave, user)  # cumple la política de la app y de la web
        self.assertTrue(user.can_use_web)
        with self.assertRaises(ApiError):  # cuenta de la web: la app la rechaza (ROLE_NOT_ALLOWED)
            cuentas.ensure_app_access(user)

    def test_operador_creado_en_la_web_usa_la_app(self):
        user, _ = cuentas.create_account(self.w.admin, "Pedro Operador", "pedro@x.pe", [O], phone="+51987654321")
        cuentas.ensure_app_access(user)
        self.assertFalse(user.can_use_web)

    def test_rechaza_mezcla_y_correo_repetido(self):
        with self.assertRaises(ValidationError):
            cuentas.create_account(self.w.admin, "Mezcla De Roles", "mezcla@x.pe", [O, E])
        with self.assertRaises(ValidationError) as ctx:
            cuentas.create_account(self.w.admin, "Otro Especialista", "ESP@x.pe", [E])
        self.assertIn("email", ctx.exception.message_dict)
        self.assertEqual(User.objects.filter(email__iexact="esp@x.pe").count(), 1)
