# ia/management/commands/worker_ia.py — Proceso worker: `python manage.py worker_ia` (28.8 del maestro móvil).
#
# Nunca atiende HTTP. En cada vuelta: toma una tarea de ai_tasks (SKIP LOCKED), descarga el original de Cloudinary,
# ejecuta el detector cargado UNA vez, guarda cajas y estado (y abre el caso si hay indicios), y envía los avisos de
# WhatsApp pendientes. Todo queda escrito en la consola con el traceId de la tarea.
import logging
import os
import signal
import socket
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection
from django.db.models import Count, Min

from diagnostico.contexto import reset_trace_id, set_trace_id
from ia import services as ia
from ia.inference import DetectorNoDisponible, cargar_detector
from ia.models import AiStatus, AiTask, ModelConfig
from notificaciones import services as notif
from notificaciones.whatsapp import WhatsAppError, get_client

log = logging.getLogger("riachuelo.worker")


class Command(BaseCommand):
    help = "Toma tareas de ai_tasks y avisos pendientes; nunca atiende HTTP."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesa lo pendiente y termina (pruebas)")
        parser.add_argument("--sleep", type=float, default=3.0, help="Segundos de espera cuando no hay trabajo")
        parser.add_argument("--detector", default=None, help="simulado | onnx | yolo (por defecto IA_DETECTOR)")

    def handle(self, *args, **opts):
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.detector, self.modelo_version = None, None
        self.nombre_detector = opts["detector"]
        self.detenido = False
        signal.signal(signal.SIGINT, self._detener)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._detener)
        try:
            self.client = get_client()
        except WhatsAppError as exc:
            log.error("Cliente de WhatsApp no disponible: %s. Los avisos quedarán pendientes.", exc)
            self.client = None
        log.info("Worker %s iniciado · detector %s · avisos %s", self.worker_id,
                 self.nombre_detector or "según IA_DETECTOR", type(self.client).__name__ if self.client else "—")
        ultimo_estado = ultimo_backfill = 0.0
        while not self.detenido:
            if not connection.in_atomic_block:  # en pruebas (TestCase) todo corre dentro de una transacción
                close_old_connections()  # conexiones caídas o vencidas (CONN_MAX_AGE) entre vueltas
            trabajo = 0
            try:
                self._asegurar_detector()
                if time.monotonic() - ultimo_backfill > 60:
                    ia.enqueue_missing()
                    ultimo_backfill = time.monotonic()
                if self.detector is not None:
                    trabajo += self._una_tarea()
                if self.client is not None:
                    trabajo += notif.process_pending_notifications(self.client, self.worker_id)
                if time.monotonic() - ultimo_estado > 300:
                    self._estado_cola()
                    ultimo_estado = time.monotonic()
            except Exception:  # noqa: BLE001 — el worker no se cae por un error de una vuelta (p. ej. BD caída)
                log.exception("Error en la vuelta del worker; se reintenta en %.0f s", max(opts["sleep"], 5))
                time.sleep(max(opts["sleep"], 5))
                continue
            if opts["once"] and not trabajo:
                break
            if not trabajo:
                time.sleep(opts["sleep"])
        log.info("Worker %s detenido.", self.worker_id)

    def _detener(self, *args):
        if not self.detenido:
            log.info("Deteniendo el worker al terminar la tarea en curso…")
        self.detenido = True

    def _asegurar_detector(self):
        modelo = ModelConfig.objects.filter(active=True).first()
        if modelo is None:
            if self.modelo_version != "__ninguno__":
                log.warning("No hay modelo de IA activo (model_configs.active): no se analizan fotos. "
                            "Actívalo en /gestion/ia/modelconfig/.")
            self.detector, self.modelo_version = None, "__ninguno__"
            return
        if self.detector is not None and self.modelo_version == modelo.version:
            return
        try:
            self.detector = cargar_detector(modelo, self.nombre_detector)
            self.modelo_version = modelo.version
            log.info("Detector «%s» listo con el modelo %s (clases: %s · umbral %.2f)",
                     getattr(self.detector, "nombre", "?"), modelo, ", ".join(modelo.classes or []) or "—",
                     modelo.conf_threshold)
        except DetectorNoDisponible as exc:
            if self.modelo_version != f"__error__{modelo.version}":
                log.error("No se pudo cargar el detector: %s. Se siguen enviando avisos; las fotos esperan en la cola.",
                          exc)
            self.detector, self.modelo_version = None, f"__error__{modelo.version}"

    def _una_tarea(self):
        task = ia.claim_next_task(self.worker_id)
        if task is None:
            return 0
        token = set_trace_id(f"ia-{str(task.pk)[:8]}")
        try:
            log.info("Analizando foto %s (intento %s)…", str(task.capture_id)[:8], task.attempts)
            try:
                r = self.detector.analyze(task)  # descarga el original firmado, tiling, NMS → cajas en píxeles
                task, case = ia.save_analysis_result(task, r.boxes, r.width, r.height, r.ms, r.model_version, r.raw)
            except Exception as exc:  # noqa: BLE001 — cualquier fallo se registra y reintenta
                task = ia.mark_analysis_failed(task, repr(exc))
                if task.status == AiStatus.ERROR_DE_ANALISIS:
                    log.exception("Foto %s: ERROR_DE_ANALISIS tras %s intentos (reencolar en /ia/)",
                                  str(task.capture_id)[:8], task.attempts)
                else:
                    log.warning("Foto %s: falló el análisis (%s); se reintenta más tarde", str(task.capture_id)[:8],
                                exc)
                return 1
            if case is not None:
                log.info("✔ %s caja(s) · %s ms → caso %s en la bandeja", len(r.boxes), r.ms, str(case.pk)[:8])
            else:
                log.info("✔ Sin indicios · %s ms", r.ms)
            return 1
        finally:
            reset_trace_id(token)

    def _estado_cola(self):
        cola = AiTask.objects.filter(status__in=[AiStatus.PENDIENTE_DE_ANALISIS, AiStatus.EN_ANALISIS]).aggregate(
            n=Count("pk"), desde=Min("requested_at"))
        errores = AiTask.objects.filter(status=AiStatus.ERROR_DE_ANALISIS).count()
        if cola["n"] or errores:
            log.info("Estado de la cola: %s foto(s) por analizar · %s con error", cola["n"], errores)
