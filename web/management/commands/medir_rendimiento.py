# web/management/commands/medir_rendimiento.py — Mide el tiempo de servidor de las pantallas principales (sección 18).
# Uso: DATABASE_URL=<base con datos (Anexo H.1)> python manage.py medir_rendimiento --email especialista@demo.pe
import statistics
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from cuentas.models import User
from revision.models import Case, ReviewStatus


class Command(BaseCommand):
    help = "Mide mediana y p95 de las pantallas de la web con los datos de la base configurada."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="especialista@demo.pe")
        parser.add_argument("--repeticiones", type=int, default=12)

    def handle(self, *args, **opts):
        if "testserver" not in settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")
        client = Client()
        client.force_login(User.objects.get(email=opts["email"]))
        case = Case.objects.filter(status=ReviewStatus.PENDIENTE_REVISION).first()
        lote = case.lot_id if case else ""
        urls = {
            "bandeja (pendientes, pág. 1)": "/casos/",
            "bandeja (todos, confianza, pág. 50)": "/casos/?estado=&orden=confianza&pagina=50",
            "caso": f"/casos/{case.pk}/" if case else None,
            "mapa/datos (sin filtros)": "/mapa/datos/",
            "mapa/datos (un lote, confirmados)": f"/mapa/datos/?lote={lote}&estado=CONFIRMADO_POR_ESPECIALISTA",
            "plano (un lote)": f"/plano/?lote={lote}",
            "panel (30 días)": "/",
        }
        self.stdout.write(f"{'pantalla':40} {'mediana ms':>10} {'p95 ms':>8} {'consultas':>9} {'KB':>6}")
        for name, url in urls.items():
            if url is None:
                continue
            times, n_queries, size = [], 0, 0
            for i in range(opts["repeticiones"]):
                with CaptureQueriesContext(connection) as q:
                    t0 = time.perf_counter()
                    r = client.get(url, HTTP_ACCEPT_ENCODING="gzip")
                    dt = (time.perf_counter() - t0) * 1000
                if r.status_code != 200:
                    raise SystemExit(f"{url} respondió {r.status_code}")
                if i >= 2:  # las dos primeras calientan conexiones y cachés
                    times.append(dt)
                n_queries, size = len(q.captured_queries), len(r.content)
            times.sort()
            p95 = times[max(0, int(len(times) * 0.95) - 1)]
            self.stdout.write(f"{name:40} {statistics.median(times):10.0f} {p95:8.0f} {n_queries:9d} {size / 1024:6.0f}")
