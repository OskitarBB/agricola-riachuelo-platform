# ia/services.py — Cola de análisis (§28.8 del maestro móvil; Anexo C.4 del Maestro Web).
# Una sola fuente de reglas para la API (encolar al confirmar), el worker (tomar, guardar, fallar) y la web (reencolar).
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from auditoria import services as audit
from evidencias.models import ANALYZABLE_QUALITY, Capture
from ia.models import AiStatus, AiTask, Detection, ModelConfig

log = logging.getLogger("riachuelo.ia")

LEASE = timedelta(minutes=5)  # si el worker muere, la tarea vuelve a estar disponible
MAX_ATTEMPTS = 3  # luego ERROR_DE_ANALISIS (no es un negativo)


class NoActiveModel(Exception):
    pass


class InvalidTaskState(Exception):
    pass


def enqueue_analysis(capture):
    """La llama la confirmación de captura (POST /captures/upload) DENTRO de su transacción.
    Solo se analizan fotos aceptadas por calidad (RN-W11); devuelve None para las rechazadas."""
    if capture.quality_status not in ANALYZABLE_QUALITY:
        return None
    model = ModelConfig.objects.filter(active=True).first()
    if model is None:
        raise NoActiveModel("No hay un modelo de IA activo (model_configs.active)")
    task, _ = AiTask.objects.get_or_create(capture=capture, model_config=model)
    return task


def enqueue_missing(limit=200):
    """(v1.0+) Encola las fotos aceptadas por calidad que quedaron sin tarea del modelo activo (por ejemplo, si se
    confirmaron mientras no había modelo activo). La llama el worker en cada vuelta; es idempotente."""
    model = ModelConfig.objects.filter(active=True).first()
    if model is None:
        return 0
    pendientes = (Capture.objects.filter(quality_status__in=ANALYZABLE_QUALITY)
                  .annotate(con_tarea=Exists(AiTask.objects.filter(capture=OuterRef("pk"), model_config=model)))
                  .filter(con_tarea=False).order_by("confirmed_at")[:limit])
    n = 0
    for capture in pendientes:
        _, created = AiTask.objects.get_or_create(capture=capture, model_config=model)
        n += int(created)
    if n:
        log.info("Encoladas %s foto(s) que no tenían tarea del modelo %s", n, model.version)
    return n


def claim_next_task(worker_id):
    """Toma una tarea libre sin bloquear a otros workers (SELECT ... FOR UPDATE SKIP LOCKED)."""
    now = timezone.now()
    with transaction.atomic():
        task = (
            AiTask.objects.select_for_update(skip_locked=True)
            .filter(status__in=[AiStatus.PENDIENTE_DE_ANALISIS, AiStatus.EN_ANALISIS], available_at__lte=now)
            .exclude(status=AiStatus.EN_ANALISIS, locked_until__gt=now)
            .order_by("requested_at")
            .first()
        )
        if task is None:
            return None
        task.status = AiStatus.EN_ANALISIS
        task.locked_by = worker_id
        task.locked_until = now + LEASE
        task.attempts += 1
        task.started_at = now
        task.save(update_fields=["status", "locked_by", "locked_until", "attempts", "started_at"])
        return task


def save_analysis_result(task, boxes, image_width, image_height, processing_ms, model_version, raw_output=None):
    """Guarda el resultado del worker en UNA transacción y, si hay cajas, abre el caso (sin callbacks)."""
    from revision.services import open_case_from_analysis  # import local: revision depende de ia

    with transaction.atomic():
        task = AiTask.objects.select_for_update().get(pk=task.pk)
        task.detections.all().delete()  # un reintento reemplaza un resultado parcial anterior
        Detection.objects.bulk_create([
            Detection(task=task, class_name=b["class_name"], confidence=b["confidence"],
                      x_min=b["x_min"], y_min=b["y_min"], x_max=b["x_max"], y_max=b["y_max"])
            for b in boxes
        ])
        task.status = AiStatus.INDICIO_SUGERIDO_POR_IA if boxes else AiStatus.SIN_INDICIOS_IA
        task.image_width, task.image_height = image_width, image_height
        task.processing_ms = processing_ms
        task.model_version = model_version
        task.raw_output = raw_output
        task.finished_at = timezone.now()
        task.locked_until = None
        task.error_message = ""
        task.save()
        case = open_case_from_analysis(task) if boxes else None
    return task, case


def mark_analysis_failed(task, error_message):
    with transaction.atomic():
        task = AiTask.objects.select_for_update().get(pk=task.pk)
        task.error_message = error_message[:2000]
        task.locked_until = None
        if task.attempts >= MAX_ATTEMPTS:
            task.status = AiStatus.ERROR_DE_ANALISIS
            task.finished_at = timezone.now()
        else:
            task.status = AiStatus.PENDIENTE_DE_ANALISIS
            task.available_at = timezone.now() + timedelta(seconds=30 * (2 ** (task.attempts - 1)))
        task.save()
    return task


def requeue_failed(task_id, user):
    """Acción del ADMINISTRADOR en la web (WEB-16): vuelve a encolar una tarea con ERROR_DE_ANALISIS."""
    with transaction.atomic():
        task = AiTask.objects.select_for_update().get(pk=task_id)
        if task.status != AiStatus.ERROR_DE_ANALISIS:
            raise InvalidTaskState("Solo se reencolan tareas con error de análisis")
        before = {"status": task.status, "attempts": task.attempts, "error": task.error_message}
        task.status = AiStatus.PENDIENTE_DE_ANALISIS
        task.attempts = 0
        task.available_at = timezone.now()
        task.error_message = ""
        task.save(update_fields=["status", "attempts", "available_at", "error_message"])
        audit.record("ai_task", task.pk, "TAREA_IA_REENCOLADA", user, before, {"status": task.status})
    return task
