# web/queries.py — Consultas de solo lectura de la web (bandeja, mapa, plano, dashboard, exportaciones, actividad).
# Reglas: sin N+1 (select_related / agregados en la BD), filtros siempre acotados, nada de escrituras aquí.
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, Exists, F, Min, OuterRef, Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from auditoria.models import AuditEvent
from campo.models import FieldLot, FieldRow, FieldSegment
from evidencias.models import Capture, QualityStatus
from ia.models import AiStatus, AiTask
from monitoreo.models import Incident, LateralCode, MonitoringPass, MonitoringSession, PassStatus
from notificaciones.models import Notification
from revision.models import Case, ReviewStatus

ORDERING = {"antiguos": ("opened_at",), "recientes": ("-opened_at",),
            "confianza": (F("max_confidence").desc(nulls_last=True), "opened_at")}
REJECTED_QUALITY = (QualityStatus.REPETIR_NITIDEZ, QualityStatus.REPETIR_EXPOSICION, QualityStatus.ERROR_CAMARA)


def filter_cases(qs, f):
    """f = cleaned_data de FiltroCasosForm (o dict equivalente)."""
    if f.get("estado"):
        qs = qs.filter(status=f["estado"])
    if f.get("lote"):
        qs = qs.filter(lot_id=f["lote"])
    if f.get("origen"):
        qs = qs.filter(origin=f["origen"])
    if f.get("desde"):
        qs = qs.filter(captured_at__date__gte=f["desde"])  # fecha en hora de Lima (TIME_ZONE)
    if f.get("hasta"):
        qs = qs.filter(captured_at__date__lte=f["hasta"])
    return qs


def bandeja(f):
    qs = Case.objects.select_related("lot", "row", "segment", "marker", "capture", "decided_by")
    qs = filter_cases(qs, f)
    return qs.order_by(*ORDERING.get(f.get("orden") or "antiguos", ORDERING["antiguos"]))


def next_pending_case_id(after_case):
    """Siguiente caso pendiente en la bandeja (orden por defecto) para «Guardar y siguiente»."""
    return (Case.objects.filter(status=ReviewStatus.PENDIENTE_REVISION)
            .exclude(pk=after_case.pk).order_by("opened_at").values_list("pk", flat=True).first())


def case_detail(case_id):
    case = (Case.objects.select_related("lot", "row", "segment", "marker", "capture__quality", "capture__device",
                                        "capture__camera_user", "capture__operator_user", "ai_task__model_config",
                                        "decided_by", "session", "monitoring_pass", "sequence")
            .get(pk=case_id))
    detections = list(case.ai_task.detections.all()) if case.ai_task_id else []
    reviews = list(case.reviews.select_related("reviewer").order_by("reviewed_at"))
    notifications = list(case.notifications.order_by("created_at"))
    sibling = (Capture.objects.filter(sequence_id=case.sequence_id).exclude(pk=case.capture_id)
               .exclude(camera_role=case.capture.camera_role).order_by("-captured_at").first())
    return case, detections, reviews, notifications, sibling


def map_geojson(f):
    qs = filter_cases(Case.objects.all(), f)
    sin_ubicacion = qs.filter(lat__isnull=True).count()
    limit = settings.WEB["MAPA_MAX_FEATURES"]
    # values() en lugar de instancias: con 5 000 puntos el JSON se arma ~5 veces más rápido (RNF-W01).
    rows = list(qs.filter(lat__isnull=False, lon__isnull=False).order_by("-captured_at").values(
        "pk", "status", "lot__code", "row__number", "lateral_code", "segment__code", "marker__code", "captured_at",
        "location_source", "gps_accuracy_m", "lat", "lon")[: limit + 1])
    truncated = len(rows) > limit
    estados, laterales = dict(ReviewStatus.choices), dict(LateralCode.choices)
    url_caso = reverse("web:caso", args=["00000000-0000-0000-0000-000000000000"])
    tz = timezone.get_current_timezone()
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},  # GeoJSON: [lon, lat]
        "properties": {
            "id": str(c["pk"]), "status": c["status"], "statusLabel": estados.get(c["status"], c["status"]),
            "lot": c["lot__code"], "row": c["row__number"], "lateral": laterales.get(c["lateral_code"], c["lateral_code"]),
            "segment": c["segment__code"], "marker": c["marker__code"],
            "capturedAt": c["captured_at"].astimezone(tz).strftime("%d/%m/%Y %H:%M"),
            "locationSource": c["location_source"], "accuracyM": c["gps_accuracy_m"],
            "url": url_caso.replace("00000000-0000-0000-0000-000000000000", str(c["pk"])),
        },
    } for c in rows[:limit]]
    lots = [{"type": "Feature", "geometry": lot.geometry, "properties": {"id": lot.pk, "code": lot.code}}
            for lot in FieldLot.objects.filter(active=True, geometry__isnull=False)]
    return {"type": "FeatureCollection", "features": features, "lots": lots,
            "meta": {"sinUbicacion": sin_ubicacion, "truncated": truncated, "limit": limit}}


def covered_rows(desde=None, hasta=None):
    """RN-13 del maestro móvil: hilera cubierta = LATERAL_A y LATERAL_B cerrados (COMPLETED, o INCOMPLETE con
    incidencia), en el periodo. Devuelve el conjunto de row_id."""
    passes = MonitoringPass.objects.annotate(
        con_incidencia=Exists(Incident.objects.filter(monitoring_pass=OuterRef("pk"))))
    passes = passes.filter(Q(status=PassStatus.COMPLETED) | Q(status=PassStatus.INCOMPLETE, con_incidencia=True))
    if desde:
        passes = passes.filter(started_at__date__gte=desde)
    if hasta:
        passes = passes.filter(started_at__date__lte=hasta)
    a = set(passes.filter(lateral_code=LateralCode.LATERAL_A).values_list("row_id", flat=True))
    b = set(passes.filter(lateral_code=LateralCode.LATERAL_B).values_list("row_id", flat=True))
    return a & b


def plano(lot, f):
    """Plano esquemático del lote: hileras → segmentos con conteo de casos por estado (sin coordenadas)."""
    cases = filter_cases(Case.objects.filter(lot=lot), f)
    by_row = defaultdict(lambda: defaultdict(int))
    by_segment = defaultdict(lambda: defaultdict(int))
    for row_id, segment_id, status, n in cases.values_list("row_id", "segment_id", "status").annotate(n=Count("id")):
        by_row[row_id][status] += n
        if segment_id:
            by_segment[segment_id][status] += n
    covered = covered_rows(f.get("desde"), f.get("hasta"))
    rows = []
    # v1.2 (ADR-W-006): se dibujan solo los segmentos activos; los casos de segmentos desactivados siguen contando en
    # la hilera (by_row). Prefetch con filtro: misma cantidad de consultas.
    activos = Prefetch("segments", queryset=FieldSegment.objects.filter(active=True).order_by("start_plant"))
    for row in FieldRow.objects.filter(lot=lot, active=True).prefetch_related(activos).order_by("number"):
        rows.append({
            "row": row, "covered": row.pk in covered, "counts": dict(by_row.get(row.pk, {})),
            "segments": [{
                "segment": s, "counts": dict(by_segment.get(s.pk, {})),
                # posición relativa dentro de la barra de la hilera (plantas 1..plant_count)
                "left_pct": round(100 * (s.start_plant - 1) / row.plant_count, 2) if row.plant_count else 0,
                "width_pct": round(100 * (s.end_plant - s.start_plant + 1) / row.plant_count, 2) if row.plant_count else 0,
            } for s in row.segments.all()],
        })
    max_plants = max((r["row"].plant_count for r in rows), default=1)
    return {"lot": lot, "rows": rows, "max_plants": max_plants, "covered": sum(1 for r in rows if r["covered"])}


def dashboard(desde, hasta):
    now = timezone.now()
    sessions = MonitoringSession.objects.filter(started_at__date__gte=desde, started_at__date__lte=hasta)
    captures = Capture.objects.filter(captured_at__date__gte=desde, captured_at__date__lte=hasta)
    cap = captures.aggregate(total=Count("pk"), rechazadas=Count("pk", filter=Q(quality_status__in=REJECTED_QUALITY)))
    tasks = AiTask.objects.filter(capture__in=captures)
    ia = {s: 0 for s in AiStatus.values}
    ia.update(dict(tasks.values_list("status").annotate(n=Count("pk"))))
    ia_tiempo = tasks.filter(processing_ms__isnull=False).aggregate(ms=Avg("processing_ms"))["ms"]
    cola = AiTask.objects.filter(status__in=[AiStatus.PENDIENTE_DE_ANALISIS, AiStatus.EN_ANALISIS]).aggregate(
        n=Count("pk"), mas_antigua=Min("requested_at"))
    cases = Case.objects.filter(captured_at__date__gte=desde, captured_at__date__lte=hasta)
    casos = {s: 0 for s in ReviewStatus.values}
    casos.update(dict(cases.values_list("status").annotate(n=Count("pk"))))
    decididos = cases.exclude(decided_at__isnull=True).aggregate(espera=Avg(F("decided_at") - F("opened_at")))
    pendientes = Case.objects.filter(status=ReviewStatus.PENDIENTE_REVISION).aggregate(
        n=Count("pk"), mas_antiguo=Min("opened_at"))
    avisos = dict(Notification.objects.filter(created_at__date__gte=desde, created_at__date__lte=hasta)
                  .values_list("status").annotate(n=Count("pk")))
    covered = covered_rows(desde, hasta)
    cobertura = []
    for lot in FieldLot.objects.filter(active=True).annotate(hileras=Count("rows", filter=Q(rows__active=True))):
        n_cov = FieldRow.objects.filter(lot=lot, pk__in=covered).count() if covered else 0
        confirmados = cases.filter(lot=lot, status=ReviewStatus.CONFIRMADO_POR_ESPECIALISTA).count()
        cobertura.append({"lot": lot, "hileras": lot.hileras, "cubiertas": n_cov, "confirmados": confirmados})
    total = cap["total"] or 0
    total_casos = sum(casos.values())
    return {
        "desde": desde, "hasta": hasta,
        "sesiones": sessions.count(),
        "capturas": total,
        "rechazadas": cap["rechazadas"],
        "pct_rechazadas": round(100 * cap["rechazadas"] / total, 1) if total else None,
        "ia": ia, "ia_ms_promedio": round(ia_tiempo) if ia_tiempo else None,
        "cola": cola["n"], "cola_espera": (now - cola["mas_antigua"]) if cola["mas_antigua"] else None,
        "casos": casos,
        "total_casos": total_casos,  # v1.0+: base de la barra de distribución por estado del panel
        "espera_decision": decididos["espera"],
        "pendientes": pendientes["n"],
        "pendiente_mas_antiguo": (now - pendientes["mas_antiguo"]) if pendientes["mas_antiguo"] else None,
        "avisos": avisos,
        "cobertura": cobertura,
    }


def default_range(days=30):
    hoy = timezone.localdate()
    return hoy - timedelta(days=days - 1), hoy


# ------------------------------------------------------------------ v1.0+: actividad en vivo (panel y avisos)
# Eventos de auditoría que se muestran como actividad. Los de cuentas (registros e ingresos desde la app) solo los ve
# quien gestiona usuarios; el resto, cualquier rol de la web.
ACTIVIDAD_OPERATIVA = {
    "SESION_RECIBIDA": ("sesion", "Nueva sesión de monitoreo sincronizada"),
    "SESION_CERRADA": ("sesion", "Sesión de monitoreo cerrada"),
    "CASO_ABIERTO": ("caso", "Nuevo caso para revisar"),
    "CASO_DECIDIDO": ("decision", "Caso decidido"),
    "CASO_CORREGIDO": ("decision", "Decisión corregida"),
}
ACTIVIDAD_CUENTAS = {
    "CUENTA_REGISTRADA": ("cuenta", "Nueva solicitud de cuenta desde la app"),
    "INGRESO_APP": ("ingreso", "Ingreso desde la app móvil"),
}


def actividad(user_puede_cuentas, desde=None, limite=12):
    acciones = dict(ACTIVIDAD_OPERATIVA)
    if user_puede_cuentas:
        acciones.update(ACTIVIDAD_CUENTAS)
    qs = AuditEvent.objects.filter(action__in=list(acciones)).select_related("user").order_by("-timestamp")
    if desde is not None:
        qs = qs.filter(timestamp__gt=desde)
    filas = list(qs[:limite])
    # Una sola consulta extra para ubicar los casos de los eventos (lote · hilera · lateral) en el aviso.
    casos = {str(c["pk"]): c for c in Case.objects.filter(
        pk__in=[e.entity_id for e in filas if e.entity_type == "case"]).values(
        "pk", "lot__code", "row__number", "lateral_code", "status")}
    decision = dict(ReviewStatus.choices)
    eventos = []
    for e in filas:
        tipo, titulo = acciones[e.action]
        quien = e.user.full_name if e.user_id else "Sistema"
        after = e.after if isinstance(e.after, dict) else {}
        caso = casos.get(e.entity_id) if e.entity_type == "case" else None
        partes = []
        if caso:
            partes.append(f"{caso['lot__code']} · H{caso['row__number']} · {caso['lateral_code'].replace('LATERAL_', 'Lateral ')}")
        if e.action in ("CASO_DECIDIDO", "CASO_CORREGIDO") and after.get("status") in decision:
            partes.append(decision[after["status"]])
        if e.action in ("INGRESO_APP", "SESION_RECIBIDA", "CASO_DECIDIDO", "CASO_CORREGIDO", "SESION_CERRADA"):
            partes.append(quien)
        if e.action == "INGRESO_APP" and after.get("model"):
            partes.append(after["model"])
        if e.action == "CUENTA_REGISTRADA":
            partes.append("pendiente de aprobación")
        url = None
        if e.entity_type == "case":
            url = reverse("web:caso", args=[e.entity_id])
        elif e.entity_type == "session":
            url = reverse("web:sesion", args=[e.entity_id])
        elif e.entity_type == "user" and user_puede_cuentas:
            url = reverse("web:usuarios")
        eventos.append({"id": e.pk, "tipo": tipo, "titulo": titulo, "accion": e.action, "cuando": e.timestamp,
                        "quien": quien, "url": url, "after": after, "detalle": " · ".join(partes)})
    return eventos


# ------------------------------------------------------------------ v1.2 (ADR-W-006): catálogos (solo lectura)
def catalogo_lotes(inactivos=False):
    qs = FieldLot.objects.annotate(
        n_hileras=Count("rows", filter=Q(rows__active=True), distinct=True),
        n_segmentos=Count("rows__segments", filter=Q(rows__active=True, rows__segments__active=True), distinct=True),
        n_marcadores=Count("rows__markers", filter=Q(rows__active=True, rows__markers__active=True), distinct=True),
    ).order_by("-active", "code")
    return qs if inactivos else qs.filter(active=True)


def catalogo_lote(lot, inactivos=False):
    rows = (FieldRow.objects.filter(lot=lot)
            .annotate(n_marcadores=Count("markers", filter=Q(markers__active=True)))
            .prefetch_related(Prefetch("segments", queryset=FieldSegment.objects.filter(active=True)
                                       .order_by("start_plant")))
            .order_by("-active", "number"))
    if not inactivos:
        rows = rows.filter(active=True)
    sin_segmento = FieldRow.objects.filter(lot=lot, active=True).exclude(segments__active=True).count()
    inactivas = FieldRow.objects.filter(lot=lot, active=False).count()
    return {"rows": rows, "sin_segmento": sin_segmento, "inactivas": inactivas}


def catalogo_hilera(row):
    from campo.models import Marker

    segmentos = list(row.segments.order_by("-active", "start_plant"))
    marcadores = list(Marker.objects.filter(row=row).select_related("segment").order_by("-active", "code"))
    activos = [s for s in segmentos if s.active]
    total = row.plant_count or 1
    tramos = [{"code": s.code, "ini": s.start_plant, "fin": s.end_plant,
               "left": round(100 * (s.start_plant - 1) / total, 2),
               "width": round(100 * (s.end_plant - s.start_plant + 1) / total, 2)} for s in activos]
    return {"segmentos": segmentos, "activos": activos, "marcadores": marcadores, "tramos": tramos}
