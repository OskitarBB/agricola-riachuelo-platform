# web/management/commands/sembrar_demo.py — Catálogos del piloto y, opcionalmente, cuentas y evidencia de
# demostración. Prohibido con APP_ENV=piloto (W-22: nunca mezclar datos de prueba con evidencia del piloto).
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import User
from monitoreo.models import MonitoringSession
from web import demo


class Command(BaseCommand):
    help = "Carga catálogos del piloto y, opcionalmente, usuarios y evidencia de demostración (solo dev)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=demo.DEMO_PASSWORD, help="Contraseña de las cuentas demo")
        parser.add_argument("--solo-catalogos", action="store_true")
        parser.add_argument("--mas", action="store_true", help="Agrega otra tanda de evidencia aunque ya exista")

    def handle(self, *args, **opts):
        if settings.APP_ENV == "piloto":
            raise CommandError("sembrar_demo está prohibido en el entorno piloto (no mezclar datos de prueba).")
        demo.crear_catalogos_piloto()
        self.stdout.write("✔ Catálogos del piloto cargados (segmentos, marcadores y coordenadas FICTICIOS).")
        if opts["solo_catalogos"]:
            return
        users = demo.crear_usuarios_demo(opts["password"])
        self.stdout.write(f"✔ Cuentas demo (contraseña {opts['password']}): admin@demo.pe, especialista@demo.pe, "
                          "supervisor@demo.pe, operador@demo.pe · temporal@demo.pe (Temp2026) · bloqueado@demo.pe · "
                          "pendiente@demo.pe")
        if MonitoringSession.objects.exists() and not opts["mas"]:
            self.stdout.write("• Ya hay sesiones: no se agrega evidencia (usa --mas para otra tanda).")
            return
        demo.crear_evidencia_demo(users["operador"])
        demo.crear_revision_demo(User.objects.get(email="especialista@demo.pe"))
        self.stdout.write(self.style.SUCCESS("✔ Evidencia, casos, decisiones y avisos de demostración cargados."))
