# revision/services.py — Reglas de la revisión (RN-W01 a RN-W07). La web, Django Admin y cualquier script usan
# SOLO estas funciones para abrir, decidir o corregir un caso: así la regla se aplica igual en todas partes.
# v1.3 (ADR-W-007): la IA confirma sola los casos de alta confianza (CONFIRMADO_POR_IA, con aviso) y el especialista
# puede dejar un caso como POSIBLE_PLAGA (visible en la app para que el encargado vaya, sin aviso).
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from auditoria import services as audit
from campo.models import Marker
from cuentas.models import Role
from evidencias.models import Capture
from ia.models import AiStatus, DetectionReview
from notificaciones import services as notif
from revision.models import (
    CON_AVISO,
    DECIDIBLES,
    DECISIONS,
    Case,
    CaseNotificationStatus,
    HumanReview,
    LocationSource,
    ReviewStatus,
)

OBSERVATION_REQUIRED = {ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, ReviewStatus.EVIDENCIA_INSUFICIENTE}


class CaseAlreadyDecided(Exception):
    """Otro especialista decidió el caso mientras este tenía la pantalla abierta (HTTP 409 en la web)."""

    def __init__(self, case):
        super().__init__("El caso ya tiene una decisión")
        self.case = case


class StaleReview(Exception):
    """La decisión vigente cambió desde que se abrió el formulario de corrección (HTTP 409)."""

    def __init__(self, current):
        super().__init__("La decisión vigente cambió")
        self.current = current


def _require_specialist(user):
    # RN-W01 (RN-01 del curso): solo el ESPECIALISTA_FITOSANITARIO confirma, descarta o corrige.
    if not (user and user.is_authenticated and user.is_active and user.has_role(Role.ESPECIALISTA_FITOSANITARIO)):
        raise PermissionDenied("Solo el especialista fitosanitario puede decidir un caso")


def case_location(capture):
    """Ubicación del caso: contexto de la repetición (RN-07 del maestro móvil) o de la secuencia.
    Prioridad de coordenadas: GPS de la secuencia → coordenadas del marcador (aproximada) → ninguna."""
    ctx = capture.retake_context
    if ctx:  # se guarda tal como llega de la app (camelCase)
        segment_id, marker_id = ctx.get("segmentId"), ctx.get("markerId")
        lat, lon, acc = ctx.get("lat"), ctx.get("lon"), ctx.get("gpsAccuracyM")
    else:
        seq = capture.sequence
        segment_id, marker_id = seq.segment_id, seq.marker_id
        lat, lon, acc = seq.lat, seq.lon, seq.gps_accuracy_m
    source = LocationSource.GPS
    if lat is None or lon is None:
        marker = Marker.objects.filter(pk=marker_id).only("lat", "lon").first() if marker_id else None
        if marker is not None and marker.lat is not None and marker.lon is not None:
            lat, lon, acc, source = marker.lat, marker.lon, None, LocationSource.MARCADOR
        else:
            lat = lon = acc = None
            source = LocationSource.NINGUNA
    return {"segment_id": segment_id, "marker_id": marker_id, "lat": lat, "lon": lon,
            "gps_accuracy_m": acc, "location_source": source}


def _new_case(capture, task, origin, stats):
    p = capture.monitoring_pass
    return Case.objects.create(
        capture=capture, ai_task=task, origin=origin,
        session_id=capture.session_id, monitoring_pass_id=p.pk, sequence_id=capture.sequence_id,
        lot_id=p.lot_id, row_id=p.row_id, lateral_code=capture.lateral_code,
        captured_at=capture.captured_at,
        **stats, **case_location(capture),
    )


def _stats(task):
    confidences = list(task.detections.values_list("confidence", flat=True)) if task else []
    return {"detections_count": len(confidences), "max_confidence": max(confidences) if confidences else None}


def open_case_from_analysis(task):
    """La llama el worker dentro de la transacción que guarda las cajas (ia.services.save_analysis_result)."""
    capture = Capture.objects.select_related("sequence", "monitoring_pass").get(pk=task.capture_id)
    case = Case.objects.select_for_update().filter(capture=capture).first()
    stats = _stats(task)
    if case is None:
        case = _new_case(capture, task, Case.Origin.IA, stats)
        audit.record("case", case.pk, "CASO_ABIERTO", None, None, {"origin": "IA", "aiTask": str(task.pk)})
    elif case.status == ReviewStatus.PENDIENTE_REVISION:
        case.ai_task = task
        case.detections_count, case.max_confidence = stats["detections_count"], stats["max_confidence"]
        case.save(update_fields=["ai_task", "detections_count", "max_confidence"])
        audit.record("case", case.pk, "CASO_NUEVO_ANALISIS", None, None, {"aiTask": str(task.pk)})
    else:  # un análisis nuevo nunca cambia una decisión tomada (RN-W06)
        audit.record("case", case.pk, "ANALISIS_POSTERIOR_A_DECISION", None, None, {"aiTask": str(task.pk)})
        return case
    _auto_confirm_if_confident(case, task)
    return case


def auto_confirm_threshold(task):
    model = task.model_config if task else None
    return getattr(model, "auto_confirm_threshold", None)


def _auto_confirm_if_confident(case, task):
    """v1.3 (ADR-W-007): si alguna caja alcanza el umbral del modelo, la IA confirma el caso sola y se avisa por
    WhatsApp sin esperar al especialista (que luego puede corregirlo). Sin umbral, el caso espera al especialista."""
    umbral = auto_confirm_threshold(task)
    if umbral is None or case.status != ReviewStatus.PENDIENTE_REVISION or case.max_confidence is None:
        return False
    if case.max_confidence < umbral:
        return False
    task.detections.filter(confidence__gte=umbral).update(review_status=DetectionReview.CONFIRMADO_POR_IA)
    case.status = ReviewStatus.CONFIRMADO_POR_IA
    case.decided_at = timezone.now()
    case.decided_by = None
    notif.enqueue_for_ai_case(case)
    case.notification_status = notif.case_notification_summary(case)
    case.save(update_fields=["status", "decided_at", "decided_by", "notification_status"])
    audit.record("case", case.pk, "CASO_CONFIRMADO_POR_IA", None, {"status": ReviewStatus.PENDIENTE_REVISION},
                 {"status": case.status, "maxConfidence": case.max_confidence, "threshold": umbral,
                  "modelVersion": task.model_version or task.model_config.version})
    return True


def open_manual_case(capture_id, user):
    """El especialista abre un caso sobre una foto SIN_INDICIOS_IA, DESCARTADO_POR_IA o ERROR_DE_ANALISIS (falso
    negativo posible)."""
    _require_specialist(user)
    with transaction.atomic():
        capture = Capture.objects.select_related("sequence", "monitoring_pass").select_for_update().get(pk=capture_id)
        existing = Case.objects.filter(capture=capture).first()
        if existing is not None:
            return existing, False
        task = (capture.ai_tasks.filter(status__in=[AiStatus.SIN_INDICIOS_IA, AiStatus.DESCARTADO_POR_IA,
                                                    AiStatus.ERROR_DE_ANALISIS])
                .order_by("-finished_at").first())
        if task is None:
            raise ValidationError("Solo se abre un caso sobre fotos aceptadas por calidad y con el análisis terminado.")
        case = _new_case(capture, task, Case.Origin.MANUAL, {"detections_count": 0, "max_confidence": None})
        audit.record("case", case.pk, "CASO_ABIERTO", user, None, {"origin": "MANUAL", "aiTask": str(task.pk)})
    return case, True


def _clean_inputs(case, decision, observation, confirmed_class, rejected_detection_ids):
    if decision not in DECISIONS:
        raise ValidationError({"decision": "Decisión no válida."})
    observation = (observation or "").strip()
    max_len = settings.WEB["OBSERVATION_MAX_LENGTH"]
    errors = {}
    if len(observation) > max_len:
        errors["observation"] = f"Máximo {max_len} caracteres."
    elif decision in OBSERVATION_REQUIRED and not observation:
        errors["observation"] = ("Registra la observación fitosanitaria."
                                 if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA
                                 else "Indica qué falta en la evidencia para decidir.")
    task = case.ai_task
    valid_ids = set(task.detections.values_list("id", flat=True)) if task else set()
    try:
        rejected = {int(x) for x in (rejected_detection_ids or [])}
    except (TypeError, ValueError):
        rejected = {-1}
    if not rejected <= valid_ids:
        errors["rejected_detection_ids"] = "Hay cajas que no pertenecen a este caso."
    if decision != ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        confirmed_class = ""
    elif confirmed_class and task and confirmed_class not in (task.model_config.classes or []):
        errors["confirmed_class"] = "Clase no válida para el modelo de este análisis."
    if errors:
        raise ValidationError(errors)
    return observation, confirmed_class or "", sorted(rejected)


def _sync_notifications(case, review, decision):
    """Avisos al decidir o corregir. RN-W03 (v1.3): avisan «Confirmado por especialista» y «Confirmado por IA».
    · decisión con aviso y el caso todavía sin avisos efectivos → se encolan;
    · decisión sin aviso → se anulan los pendientes (lo ya ENVIADO no se puede retirar, Q-W07)."""
    if decision in CON_AVISO:
        if not notif.case_has_effective_notifications(case):
            notif.enqueue_for_review(review)
    else:
        notif.cancel_pending_for_case(case)


def _apply_detection_status(case, decision, rejected):
    if case.ai_task_id is None:
        return
    dets = case.ai_task.detections
    if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA:
        dets.exclude(id__in=rejected).update(review_status=DetectionReview.CONFIRMADO_POR_ESPECIALISTA)
        dets.filter(id__in=rejected).update(review_status=DetectionReview.DESCARTADO)
    else:
        dets.update(review_status=decision)


def decide_case(case_id, user, decision, observation="", confirmed_class="", rejected_detection_ids=()):
    """CU6/CU7: decisión del especialista. Una sola transacción: decisión + cajas + caso + avisos + auditoría."""
    _require_specialist(user)
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("ai_task__model_config").get(pk=case_id)
        if case.status not in DECIDIBLES:  # v1.3: «Confirmado por IA» también lo decide el especialista
            raise CaseAlreadyDecided(case)
        observation, confirmed_class, rejected = _clean_inputs(
            case, decision, observation, confirmed_class, rejected_detection_ids)
        review = HumanReview.objects.create(
            case=case, ai_task=case.ai_task, decision=decision, observation=observation,
            confirmed_class=confirmed_class, rejected_detection_ids=rejected, reviewer=user)
        _apply_detection_status(case, decision, rejected)
        before = {"status": case.status}
        _sync_notifications(case, review, decision)
        case.status = decision
        case.decided_at = review.reviewed_at
        case.decided_by = user
        case.notification_status = notif.case_notification_summary(case)
        case.save(update_fields=["status", "decided_at", "decided_by", "notification_status"])
        audit.record("case", case.pk, "CASO_DECIDIDO", user, before,
                     {"status": decision, "review": str(review.pk), "rejectedDetections": rejected})
    return review


def correct_decision(case_id, user, decision, observation, correction_reason, expected_review_id,
                     confirmed_class="", rejected_detection_ids=()):
    """Corrección (8.5): nueva decisión que reemplaza a la vigente; la anterior se conserva en el historial."""
    _require_specialist(user)
    correction_reason = (correction_reason or "").strip()
    if not correction_reason:
        raise ValidationError({"correction_reason": "Explica por qué corriges la decisión."})
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("ai_task__model_config").get(pk=case_id)
        if case.status in DECIDIBLES:
            raise ValidationError("El caso todavía no tiene una decisión del especialista que corregir: usa «Decidir».")
        current = case.reviews.get(is_current=True)
        if str(current.pk) != str(expected_review_id):
            raise StaleReview(current)
        observation, confirmed_class, rejected = _clean_inputs(
            case, decision, observation, confirmed_class, rejected_detection_ids)
        current.is_current = False
        current.save(update_fields=["is_current"])
        review = HumanReview.objects.create(
            case=case, ai_task=case.ai_task, decision=decision, observation=observation,
            confirmed_class=confirmed_class, rejected_detection_ids=rejected, reviewer=user,
            supersedes=current, correction_reason=correction_reason)
        _apply_detection_status(case, decision, rejected)
        before = {"status": case.status, "review": str(current.pk)}
        _sync_notifications(case, review, decision)
        case.status = decision
        case.decided_at = review.reviewed_at
        case.decided_by = user
        case.notification_status = notif.case_notification_summary(case)
        case.save(update_fields=["status", "decided_at", "decided_by", "notification_status"])
        audit.record("case", case.pk, "CASO_CORREGIDO", user, before,
                     {"status": decision, "review": str(review.pk), "reason": correction_reason})
    return review


__all__ = ["CaseAlreadyDecided", "StaleReview", "CaseNotificationStatus", "case_location", "open_case_from_analysis",
           "open_manual_case", "decide_case", "correct_decision"]


# ------------------------------------------------------------------ v1.3.1 (ADR-W-008): triage en tres franjas
def discard_case_by_ai(case_id, umbral):
    """Un caso «Pendiente de revisión» abierto por la IA cuya confianza máxima no alcanza el umbral de revisión deja de
    ser caso: se borra la fila de review_cases (sin decisiones ni avisos) y la tarea queda DESCARTADO_POR_IA. Las cajas
    se conservan en detections (sirven para medir y reentrenar). Devuelve True si se descartó."""
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("ai_task").filter(pk=case_id).first()
        if (case is None or case.status != ReviewStatus.PENDIENTE_REVISION or case.origin != Case.Origin.IA
                or case.ai_task_id is None or case.max_confidence is None or case.max_confidence >= umbral):
            return False
        if case.reviews.exists() or case.notifications.exists():
            return False
        snapshot = {"status": case.status, "capture": str(case.capture_id), "lot": case.lot_id, "row": case.row_id,
                    "maxConfidence": case.max_confidence, "detections": case.detections_count}
        task = case.ai_task
        case_pk = case.pk
        case.delete()
        task.status = AiStatus.DESCARTADO_POR_IA
        task.save(update_fields=["status"])
        audit.record("case", case_pk, "CASO_DESCARTADO_POR_IA", None, snapshot, {"threshold": umbral})
    return True


def reapply_triage(model, simulate=False):
    """Aplica los umbrales del modelo a los casos «Pendiente de revisión» abiertos por la IA (comando aplicar_triage).
    Devuelve {"descartados": n, "confirmados": n, "revision": n}."""
    out = {"descartados": 0, "confirmados": 0, "revision": 0}
    pendientes = (Case.objects.filter(status=ReviewStatus.PENDIENTE_REVISION, origin=Case.Origin.IA,
                                      ai_task__model_config=model)
                  .select_related("ai_task__model_config").order_by("opened_at"))
    for case in pendientes:
        conf = case.max_confidence
        if model.review_threshold is not None and conf is not None and conf < model.review_threshold:
            if simulate or discard_case_by_ai(case.pk, model.review_threshold):
                out["descartados"] += 1
            continue
        if model.auto_confirm_threshold is not None and conf is not None and conf >= model.auto_confirm_threshold:
            if simulate:
                out["confirmados"] += 1
                continue
            with transaction.atomic():
                locked = Case.objects.select_for_update(of=("self",)).get(pk=case.pk)
                if _auto_confirm_if_confident(locked, locked.ai_task):
                    out["confirmados"] += 1
                    continue
        out["revision"] += 1
    return out
