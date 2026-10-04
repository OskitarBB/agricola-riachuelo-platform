"""Server-rendered web views.

The views are intentionally thin: query data, call services for decisions, and
render full pages or HTMX-friendly fragments. Business transitions live in the
domain apps.
"""
import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from cuentas.models import MobileDevice, User
from evidencias.media import signed_capture_url
from evidencias.models import Capture, QualityStatus
from ia.models import AITask, TaskStatus
from ia.services import requeue_task
from monitoreo.models import Lot, MonitoringSession
from notificaciones.models import Notification, NotificationRecipient
from revision.models import Case, ReviewStatus
from revision.services import decide_case
from web.forms import CaseDecisionForm
from web.permissions import can, permission_context


def _case_queryset():
    return Case.objects.select_related("capture", "capture__row", "capture__row__lot", "capture__session", "decided_by")


def _status_counts():
    raw = Case.objects.values("status").annotate(total=Count("case_id"))
    return {row["status"]: row["total"] for row in raw}


@login_required
def dashboard(request):
    """Main panel with operational counters and recent review cases."""
    counts = _status_counts()
    captures_total = Capture.objects.count()
    captures_ok = Capture.objects.filter(quality_status=QualityStatus.UTILIZABLE).count()
    kpis = {
        "capturas": captures_total,
        "capturas_ok": captures_ok,
        "capturas_rechazadas": Capture.objects.filter(quality_status=QualityStatus.RECHAZADA).count(),
        "pendientes": counts.get(ReviewStatus.PENDIENTE_REVISION, 0),
        "confirmados": counts.get(ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, 0),
        "descartados": counts.get(ReviewStatus.DESCARTADO, 0),
        "tasa_ok": round((captures_ok / captures_total) * 100, 1) if captures_total else 0,
        "tareas_error": AITask.objects.filter(status=TaskStatus.ERROR).count(),
    }
    sessions = MonitoringSession.objects.select_related("lot").annotate(n_captures=Count("captures")).order_by("-started_at")[:5]
    cases = _case_queryset().order_by("-opened_at")[:6]
    return render(request, "dashboard.html", {"kpis": kpis, "sessions": sessions, "cases": cases})


@login_required
def casos(request, case_id=None):
    """Case tray and selected case review panel."""
    qs = _case_queryset()
    status = request.GET.get("estado") or ReviewStatus.PENDIENTE_REVISION
    if status:
        qs = qs.filter(status=status)
    cases = qs.order_by("-opened_at")[:80]
    selected = get_object_or_404(_case_queryset(), pk=case_id) if case_id else cases.first()

    if request.method == "POST" and selected:
        form = CaseDecisionForm(request.POST)
        if form.is_valid():
            try:
                decide_case(selected.pk, request.user, form.cleaned_data["decision"], form.cleaned_data["observation"])
            except Exception as exc:
                messages.error(request, f"No se pudo guardar la decision: {exc}")
            else:
                messages.success(request, "Decision guardada y flujo de aviso actualizado.")
            return redirect("web:caso", case_id=selected.pk)
    else:
        form = CaseDecisionForm()

    detections = []
    if selected and hasattr(selected.capture, "ai_task"):
        detections = selected.capture.ai_task.detections.all()
    context = {
        "cases": cases,
        "selected": selected,
        "detections": detections,
        "form": form,
        "puede_decidir": can(request.user, "caso.decidir"),
        "selected_img": signed_capture_url(selected.capture, "revision") if selected else "",
        "filters": {"estado": status},
        "counts": _status_counts(),
    }
    return render(request, "casos_ia.html", context)


@login_required
def captura(request, capture_id):
    capture_obj = get_object_or_404(Capture.objects.select_related("row", "row__lot", "session"), pk=capture_id)
    return render(
        request,
        "captura.html",
        {
            "capture": capture_obj,
            "img_revision": signed_capture_url(capture_obj, "revision"),
            "img_original": signed_capture_url(capture_obj, "original"),
        },
    )


@login_required
def sesiones(request):
    """Read-only monitoring sessions with capture counts."""
    sessions_qs = (
        MonitoringSession.objects.select_related("lot", "operator")
        .annotate(
            n_captures=Count("captures"),
            n_ok=Count("captures", filter=Q(captures__quality_status=QualityStatus.UTILIZABLE)),
            n_rejected=Count("captures", filter=Q(captures__quality_status=QualityStatus.RECHAZADA)),
        )
        .order_by("-started_at")
    )
    selected = sessions_qs.first()
    if request.GET.get("sesion"):
        selected = get_object_or_404(sessions_qs, pk=request.GET["sesion"])
    captures = Capture.objects.filter(session=selected).select_related("row").order_by("-captured_at")[:40] if selected else []
    return render(request, "sesiones.html", {"sessions": sessions_qs[:60], "selected": selected, "captures": captures})


@login_required
def mapa(request):
    lots = Lot.objects.order_by("code")
    return render(request, "mapa.html", {"lots": lots, "statuses": ReviewStatus.choices})


@login_required
def mapa_datos(request):
    """GeoJSON endpoint consumed by Leaflet."""
    qs = _case_queryset().exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    if request.GET.get("estado"):
        qs = qs.filter(status=request.GET["estado"])
    if request.GET.get("lote"):
        qs = qs.filter(capture__row__lot_id=request.GET["lote"])

    features = []
    sin_ubicacion = Case.objects.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)).count()
    for case in qs[:500]:
        lot = case.lot
        features.append(
            {
                "type": "Feature",
                "id": str(case.pk),
                "geometry": {"type": "Point", "coordinates": [float(case.longitude), float(case.latitude)]},
                "properties": {
                    "url": reverse("web:caso", args=[case.pk]),
                    "status": case.status,
                    "disease": case.disease or "Indicio",
                    "lot": lot.code if lot else "Sin lote",
                    "row": case.row_label,
                    "opened_at": case.opened_at.isoformat(),
                },
            }
        )
    return JsonResponse({"type": "FeatureCollection", "features": features, "meta": {"sinUbicacion": sin_ubicacion}})


@login_required
def tratamientos(request):
    """Treatment page stays read-only: the web confirms evidence, not treatments."""
    confirmed = _case_queryset().filter(status=ReviewStatus.CONFIRMADO_POR_ESPECIALISTA).order_by("-decided_at")[:30]
    return render(request, "tratamientos.html", {"cases": confirmed})


@login_required
def reportes(request):
    return render(
        request,
        "reportes.html",
        {
            "case_count": Case.objects.count(),
            "notification_count": Notification.objects.count(),
            "recipient_count": NotificationRecipient.objects.filter(is_active=True).count(),
        },
    )


def _csv_safe(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


@login_required
def exportar_casos(request):
    """CSV export with spreadsheet-injection protection."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["caso", "estado", "enfermedad", "lote", "hilera", "abierto", "decision", "revisor"])
    for case in _case_queryset().order_by("-opened_at")[:5000]:
        lot = case.lot
        writer.writerow(
            [
                case.pk,
                case.status,
                _csv_safe(case.disease),
                _csv_safe(lot.code if lot else ""),
                _csv_safe(case.row_label),
                case.opened_at.isoformat(),
                case.decided_at.isoformat() if case.decided_at else "",
                _csv_safe(case.decided_by.email if case.decided_by else ""),
            ]
        )
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="casos_riachuelo.csv"'
    return response


@login_required
def usuarios(request):
    users = User.objects.prefetch_related("user_roles").order_by("status", "email")
    return render(request, "usuarios.html", {"users": users, "devices": MobileDevice.objects.select_related("owner")[:100]})


@login_required
def configuracion(request):
    errors = AITask.objects.filter(status=TaskStatus.ERROR).select_related("capture").order_by("-finished_at")[:30]
    if request.method == "POST" and request.POST.get("task_id"):
        try:
            requeue_task(request.POST["task_id"], request.user)
            messages.success(request, "Tarea reencolada.")
        except Exception as exc:
            messages.error(request, f"No se pudo reencolar: {exc}")
        return redirect("web:configuracion")
    return render(
        request,
        "configuracion.html",
        {
            "devices": MobileDevice.objects.select_related("owner").order_by("code")[:100],
            "errors": errors,
            "can_requeue": can(request.user, "ia.reencolar"),
        },
    )


def common_context(request):
    """Template context for permissions in navigation and actions."""
    if not request.user.is_authenticated:
        return {}
    return {"puede": permission_context(request.user)}
