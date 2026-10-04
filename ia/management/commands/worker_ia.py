"""Worker process for AI queue and WhatsApp notifications.

Run with: python manage.py worker_ia
The detector is intentionally pluggable; the command already owns the process
loop required by the architecture document.
"""
import logging
import socket
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from ia import services as ia_services
from notificaciones.services import process_pending_notifications
from notificaciones.whatsapp import get_client


log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Processes ai_tasks and pending WhatsApp notifications outside HTTP."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one iteration and exit.")
        parser.add_argument("--sleep", type=float, default=5.0, help="Seconds between idle loops.")

    def handle(self, *args, **options):
        worker_id = f"{socket.gethostname()}:{id(self)}"
        client = get_client()
        self.stdout.write(self.style.SUCCESS(f"worker_ia started as {worker_id}"))

        while True:
            close_old_connections()
            processed = 0

            # Detector integration point: call claim_next_task() and pass the
            # task to the YOLO adapter when it is available in this repo.
            task = ia_services.claim_next_task(worker_id)
            if task:
                ia_services.mark_task_error(task, "Detector no configurado en este entorno")
                processed += 1

            processed += process_pending_notifications(client, worker_id)

            if options["once"]:
                self.stdout.write(f"processed={processed}")
                return
            if not processed:
                time.sleep(options["sleep"])
