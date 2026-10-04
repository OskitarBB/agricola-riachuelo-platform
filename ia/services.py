"""Queue operations for AI tasks."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from auditoria.services import log_event
from evidencias.models import QualityStatus
from ia.models import AITask, Detection, ModelConfig, TaskStatus
from revision.services import open_case_for_capture


def enqueue_capture(capture):
    """Create the AI task in the same transaction that accepted a capture."""
    if capture.quality_status != QualityStatus.UTILIZABLE:
        return None
    model = ModelConfig.objects.filter(is_active=True).first()
    task, _ = AITask.objects.get_or_create(capture=capture, defaults={"model_config": model})
    return task


@transaction.atomic
def claim_next_task(worker_id):
    """Claim the oldest available task; skip-locked keeps workers independent."""
    now = timezone.now()
    qs = AITask.objects.select_for_update(skip_locked=True).filter(status=TaskStatus.PENDIENTE)
    qs = qs.filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
    task = qs.order_by("requested_at").first()
    if not task:
        return None
    task.status = TaskStatus.TOMADA
    task.claimed_at = now
    task.claimed_by = worker_id
    task.attempts += 1
    task.save(update_fields=["status", "claimed_at", "claimed_by", "attempts"])
    return task


@transaction.atomic
def save_analysis_result(task, detections):
    """Persist YOLO detections and open a review case when there are boxes."""
    task = AITask.objects.select_for_update().select_related("capture").get(pk=task.pk)
    task.detections.all().delete()
    for item in detections:
        Detection.objects.create(
            task=task,
            label=item.get("label", "indicio"),
            confidence=item.get("confidence", 0),
            bbox=item.get("bbox", {}),
        )
    task.status = TaskStatus.INDICIO_SUGERIDO_POR_IA if detections else TaskStatus.SIN_INDICIOS
    task.finished_at = timezone.now()
    task.error = ""
    task.save(update_fields=["status", "finished_at", "error"])
    if detections:
        best = max(detections, key=lambda item: item.get("confidence", 0))
        open_case_for_capture(task.capture, disease=best.get("label", "Indicio"), confidence=best.get("confidence"))
    return task


@transaction.atomic
def mark_task_error(task, message):
    task = AITask.objects.select_for_update().get(pk=task.pk)
    task.status = TaskStatus.ERROR
    task.error = message[:2000]
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "error", "finished_at"])
    return task


@transaction.atomic
def requeue_task(task_id, actor):
    task = AITask.objects.select_for_update().get(pk=task_id)
    if task.status != TaskStatus.ERROR:
        raise ValueError("Solo se reencolan tareas con error")
    task.status = TaskStatus.PENDIENTE
    task.error = ""
    task.available_at = timezone.now()
    task.save(update_fields=["status", "error", "available_at"])
    log_event(actor, "TAREA_IA_REENCOLADA", target=task)
    return task
