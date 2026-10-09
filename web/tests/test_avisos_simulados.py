# web/tests/test_avisos_simulados.py — QUÉ HACE: v1.3.1 prueba que un aviso enviado por la consola (WhatsApp en modo
# ConsoleClient) se muestre como «Simulado (no enviado)» y no como «Enviado».
from django.test import TestCase, override_settings
from django.urls import reverse

from notificaciones import services as notif
from notificaciones.models import Notification
from revision import services as rv
from revision.models import ReviewStatus
from web.tests import factories as F


class AvisosSimulados(TestCase):
    def setUp(self):
        self.w = F.world()
        F.recipient("Jefe")
        _, _, case = F.analyzed(self.w)
        rv.decide_case(case.pk, self.w.esp, ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Colonias")
        self.case = case
        self.client.force_login(self.w.admin)

    @override_settings(WHATSAPP_CLIENT="notificaciones.whatsapp.ConsoleClient")
    def test_consola_se_ve_como_simulado(self):
        notif.mark_sent(Notification.objects.get(), "console-123")
        r = self.client.get(reverse("web:notificaciones"))
        self.assertContains(r, "Simulado (no enviado)")
        r = self.client.get(reverse("web:caso", args=[self.case.pk]))
        self.assertContains(r, "Simulado (no enviado)")

    @override_settings(WHATSAPP_CLIENT="notificaciones.whatsapp.CloudApiClient")
    def test_envio_real_se_ve_como_enviado(self):
        notif.mark_sent(Notification.objects.get(), "wamid.ABC")
        r = self.client.get(reverse("web:notificaciones"))
        self.assertNotContains(r, "Simulado (no enviado)")
