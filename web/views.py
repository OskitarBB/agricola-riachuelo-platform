# web/views.py — Vistas de la web. Cada vista: decorador @web_view (permiso) → formulario → servicio → plantilla.
import csv
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from auditoria import services as audit
from auditoria.models import AuditEvent
from campo import services as catalogo
from campo.models import FieldLot, FieldRow, FieldSegment, Marker
from cuentas import services as cuentas
from cuentas.models import AccountStatus, Device, PasswordResetRequest, Role, User
from evidencias.media import signed_image_url
from evidencias.models import Capture
from ia import services as ia
from ia.models import AiStatus, AiTask, ModelConfig
from monitoreo.models import MonitoringSession
from notificaciones.models import Notification, NotificationRecipient
from revision import services as revision
from revision.models import CON_AVISO, DECIDIBLES, Case, ReviewStatus
from web import messages as M
from web import queries
from web.forms import (ApproveForm, AsignarContrasenaForm, CorrectionForm, DecisionForm, DividirForm, EditarCuentaForm,
                       FiltroCasosForm, FiltroDescartadasForm, HileraForm, HilerasForm, LoginForm, LoteForm,
                       MarcadorForm, NuevaCuentaForm, RecipientForm, SegmentoForm)
from web.permissions import can, web_view


# ------------------------------------------------------------------ cuenta
@require_http_methods(["GET", "POST"])
def ingresar(request):
    if request.user.is_authenticated and request.user.can_use_web:
        return redirect("web:dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["mostrar_splash"] = True  # v1.0+: pantalla de carga en la primera página
        audit.record("user", form.user.pk, "INGRESO_WEB", form.user)
        nxt = request.POST.get("next") or request.GET.get("next")
        if form.user.must_change_password:
            return redirect("web:cambiar_contrasena")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
            return redirect(nxt)
        return redirect("web:dashboard")
    return render(request, "web/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def salir(request):
    logout(request)
    return redirect("web:login")


@require_http_methods(["GET", "POST"])
def cambiar_contrasena(request):
    if not request.user.is_authenticated:
        return redirect("web:login")
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        audit.record("user", user.pk, "CONTRASENA_CAMBIADA_WEB", user)
        messages.success(request, M.CONTRASENA_CAMBIADA)
        return redirect("web:dashboard")
    if request.user.must_change_password:
        messages.warning(request, M.CONTRASENA_OBLIGATORIA)
    return render(request, "web/cambiar_contrasena.html", {"form": form})


# ------------------------------------------------------------------ panel
@web_view("dashboard.ver")
def dashboard(request):
    desde, hasta = queries.default_range(30)
    f = FiltroCasosForm(request.GET or None, initial={"desde": desde, "hasta": hasta})
    if f.is_valid():
        desde = f.cleaned_data.get("desde") or desde
        hasta = f.cleaned_data.get("hasta") or hasta
    k = cache.get_or_set(f"panel:{desde}:{hasta}", lambda: queries.dashboard(desde, hasta),
                         settings.WEB["DASHBOARD_CACHE_SECONDS"])  # KPIs con hasta 60 s de antigüedad
    eventos = queries.actividad(can(request.user, "usuarios.gestionar"), limite=8)
    return render(request, "web/dashboard.html", {
        "k": k, "filtro": f, "eventos": eventos, "desde_iso": desde.isoformat(), "hasta_iso": hasta.isoformat(),
        "sin_modelo": not ModelConfig.objects.filter(active=True).exists(), "aviso_sin_modelo": M.SIN_MODELO_IA})


@web_view("dashboard.ver")
@require_GET
def actividad(request):
    """v1.0+: sondeo de actividad (patrón P-2: el fragmento se reemplaza a sí mismo con el último id visto)."""
    try:  # sin «desde» (primer sondeo de la página) solo se marca el punto de partida
        desde = int(request.GET["desde"]) if "desde" in request.GET else None
    except ValueError:
        desde = None
    puede_cuentas = can(request.user, "usuarios.gestionar")
    ultimo = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    eventos = []
    if desde is not None:
        eventos = [e for e in queries.actividad(puede_cuentas, limite=10) if e["id"] > desde]
        eventos.reverse()
    desde = desde or 0
    pendientes = Case.objects.filter(status__in=DECIDIBLES).count()
    return render(request, "web/partials/actividad_poll.html",
                  {"eventos": eventos, "ultimo": max(ultimo, desde), "pendientes": pendientes})


# ------------------------------------------------------------------ bandeja y casos
@web_view("bandeja.ver")
def bandeja(request):
    data = request.GET.copy()
    if "estado" not in data:
        data["estado"] = FiltroCasosForm.POR_REVISAR  # por defecto: lo que falta revisar (v1.3: + confirmados por IA)
    f = FiltroCasosForm(data)
    filtros = f.cleaned_data if f.is_valid() else {"estado": FiltroCasosForm.POR_REVISAR}
    if filtros.get("estado") == FiltroCasosForm.DESCARTADAS_IA:  # v1.3.2: las descartadas no son casos
        params = {k: v for k, v in request.GET.items() if k in ("lote", "desde", "hasta") and v}
        url = reverse("web:descartadas_ia") + (f"?{urlencode(params)}" if params else "")
        return _go(request, url)
    page = Paginator(queries.bandeja(filtros), settings.WEB["BANDEJA_PAGE_SIZE"]).get_page(request.GET.get("pagina"))
    for case in page.object_list:
        case.thumb_url = signed_image_url(case.capture, "miniatura")
    ctx = {"page": page, "filtro": f, "lotes": FieldLot.objects.filter(active=True),
           "aviso_ia": M.IA_AVISO, "ayuda": M.BANDEJA_AYUDA}
    template = "web/partials/bandeja_tabla.html" if request.htmx else "web/bandeja.html"
    return render(request, template, ctx)


@web_view("bandeja.ver")
def descartadas_ia(request):
    """v1.3.2: fotos descartadas por la IA (indicio débil o sin indicios), sin caso. Desde aquí el especialista abre la
    foto y, si ve una plaga que la IA no marcó, la rescata con «Abrir caso para revisión»."""
    f = FiltroDescartadasForm(request.GET or None)
    filtros = f.cleaned_data if f.is_valid() else {}
    page = Paginator(queries.descartadas_ia(filtros), settings.WEB["BANDEJA_PAGE_SIZE"]).get_page(
        request.GET.get("pagina"))
    for t in page.object_list:
        t.thumb_url = signed_image_url(t.capture, "miniatura")
    return render(request, "web/descartadas_ia.html", {
        "page": page, "filtro": f, "lotes": FieldLot.objects.filter(active=True), "ayuda": M.DESCARTADAS_AYUDA})


@web_view("bandeja.ver")
@require_GET
def descartadas_resumen(request):
    """v1.3.2: franja «Descartadas por la IA» de la bandeja. Se carga aparte con HTMX (la bandeja sigue en 6 consultas)
    y respeta los filtros de lote y fechas de la bandeja."""
    params = {k: v for k, v in request.GET.items() if k in ("lote", "desde", "hasta") and v}
    f = FiltroDescartadasForm(params)  # solo lote y fechas: el estado y el orden de la bandeja no aplican aquí
    qs = queries.descartadas_ia(f.cleaned_data if f.is_valid() else {})
    total = qs.count()
    ultimas = list(qs[:8]) if total else []
    for t in ultimas:
        t.thumb_url = signed_image_url(t.capture, "miniatura")
    return render(request, "web/partials/descartadas_resumen.html", {
        "total": total, "ultimas": ultimas, "params": urlencode(params)})


def _case_context(request, case_id, form=None, correction_form=None):
    case, detections, reviews, notifications, sibling = queries.case_detail(case_id)
    current = next((r for r in reviews if r.is_current), None)
    width = (case.ai_task.image_width if case.ai_task_id and case.ai_task.image_width else case.capture.width)
    height = (case.ai_task.image_height if case.ai_task_id and case.ai_task.image_height else case.capture.height)
    return {
        "case": case, "detections": detections, "reviews": reviews, "current": current,
        "notifications": notifications, "sibling": sibling,
        "img_revision": signed_image_url(case.capture, "revision"),
        "img_original": signed_image_url(case.capture, "original"),
        "sibling_thumb": signed_image_url(sibling, "miniatura") if sibling else None,
        "vb_w": width, "vb_h": height, "label_size": max(12, round(max(width, height) / 45)),
        "form": form or DecisionForm(case=case),
        "correction_form": correction_form or CorrectionForm(case=case, initial={
            "expected_review_id": current.pk if current else None,
            "decision": current.decision if current else None,
            "observation": current.observation if current else "",
            "confirmed_class": current.confirmed_class if current else ""}),
        "aviso_ia": M.IA_AVISO,
        "por_decidir": case.status in DECIDIBLES,  # v1.3: «Confirmado por IA» también se decide
    }


@web_view("caso.ver")
def caso(request, pk):
    get_object_or_404(Case, pk=pk)
    return render(request, "web/caso.html", _case_context(request, pk))


@web_view("caso.decidir")
@require_POST
def caso_decidir(request, pk):
    case = get_object_or_404(Case.objects.select_related("ai_task__model_config"), pk=pk)
    form = DecisionForm(request.POST, case=case)
    status = 200
    if form.is_valid():
        d = form.cleaned_data
        try:
            review = revision.decide_case(case.pk, request.user, d["decision"], d["observation"],
                                          d["confirmed_class"], d["rejected_detection_ids"])
        except revision.CaseAlreadyDecided as exc:
            c = exc.case
            messages.warning(request, M.CASO_YA_DECIDIDO.format(
                quien=c.decided_by.full_name, cuando=timezone.localtime(c.decided_at).strftime("%d/%m/%Y %H:%M")))
            status = 409
        except ValidationError as exc:
            _merge_errors(form, exc)
            status = 422
        else:
            messages.success(request, M.CASO_DECIDIDO.format(decision=review.get_decision_display()))
            n = review.notifications.count()
            if review.decision in CON_AVISO and n:
                messages.info(request, M.AVISO_ENCOLADO.format(n=n))
            elif review.decision in CON_AVISO and not review.case.notifications.exists():
                messages.info(request, M.AVISO_SIN_DESTINATARIOS)
            if request.POST.get("siguiente"):
                nxt = queries.next_pending_case_id(case)
                if nxt:
                    return _go(request, reverse("web:caso", args=[nxt]))
                return _go(request, reverse("web:bandeja"))
            return _go(request, reverse("web:caso", args=[case.pk]))
    else:
        status = 422
    ctx = _case_context(request, case.pk, form=form if status == 422 else None)
    template = "web/partials/panel_decision.html" if request.htmx else "web/caso.html"
    return render(request, template, ctx, status=status)


@web_view("caso.corregir")
@require_POST
def caso_corregir(request, pk):
    case = get_object_or_404(Case.objects.select_related("ai_task__model_config"), pk=pk)
    form = CorrectionForm(request.POST, case=case)
    status = 422
    if form.is_valid():
        d = form.cleaned_data
        try:
            revision.correct_decision(case.pk, request.user, d["decision"], d["observation"], d["correction_reason"],
                                      d["expected_review_id"], d["confirmed_class"], d["rejected_detection_ids"])
        except revision.StaleReview:
            messages.warning(request, M.DECISION_CAMBIO)
            status = 409
        except ValidationError as exc:
            _merge_errors(form, exc)
        else:
            messages.success(request, M.CASO_CORREGIDO)
            return _go(request, reverse("web:caso", args=[case.pk]))
    ctx = _case_context(request, case.pk, correction_form=form if status == 422 else None)
    template = "web/partials/panel_decision.html" if request.htmx else "web/caso.html"
    return render(request, template, ctx, status=status)


def _merge_errors(form, exc):
    if hasattr(exc, "error_dict"):
        for field, errs in exc.error_dict.items():
            form.add_error(field if field in form.fields else None, errs)
    else:
        form.add_error(None, exc.messages)


def _go(request, url):
    from django_htmx.http import HttpResponseClientRedirect

    return HttpResponseClientRedirect(url) if request.htmx else redirect(url)


@web_view("caso.ver")
def captura(request, pk):
    capture = get_object_or_404(Capture.objects.select_related(
        "sequence", "monitoring_pass__lot", "monitoring_pass__row", "quality", "device", "camera_user"), pk=pk)
    tasks = list(capture.ai_tasks.select_related("model_config").prefetch_related("detections"))
    for t in tasks:  # v1.3.2: por qué la descartó la IA (confianza máxima frente al umbral de revisión)
        t.conf_max = max((d.confidence for d in t.detections.all()), default=None)
    case = Case.objects.filter(capture=capture).first() or revision.sequence_case(capture.sequence_id)
    return render(request, "web/captura.html", {
        "capture": capture, "tasks": tasks, "case": case,
        "img_revision": signed_image_url(capture, "revision"),
        "puede_abrir": can(request.user, "caso.abrir_manual") and case is None
        and any(t.status in (AiStatus.SIN_INDICIOS_IA, AiStatus.DESCARTADO_POR_IA, AiStatus.ERROR_DE_ANALISIS)
                for t in tasks)})


@web_view("caso.abrir_manual")
@require_POST
def captura_abrir_caso(request, pk):
    try:
        case, created = revision.open_manual_case(pk, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("web:captura", pk=pk)
    if created:
        messages.success(request, M.CASO_MANUAL_ABIERTO)
    return redirect("web:caso", pk=case.pk)


# ------------------------------------------------------------------ mapa y plano
@web_view("mapa.ver")
def mapa(request):
    desde, _ = queries.default_range(30)  # por defecto, últimos 30 días: el GeoJSON completo pesa (RNF-W01)
    filtro = FiltroCasosForm(request.GET or None, initial={"desde": desde})
    return render(request, "web/mapa.html", {"filtro": filtro, "lotes": FieldLot.objects.filter(active=True),
                                             "puede_editar": can(request.user, "catalogos.gestionar")})


@web_view("mapa.ver")
@require_GET
@gzip_page
def mapa_capas(request):
    """v1.3 (ADR-W-007): contornos de lotes, hileras y puntos con nombre para el mapa satelital."""
    return JsonResponse(queries.map_layers())


def _json_body(request):
    import json

    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@web_view("catalogos.gestionar")
@require_POST
def mapa_editar(request):
    """v1.3 (ADR-W-007): ediciones del mapa satelital (administrador y supervisor). Cuerpo JSON con «accion»:
    contorno (lote + geometry o null), hilera (hilera + inicio/fin [lat, lon]), punto_crear, punto_editar,
    punto_eliminar. Responde las capas actualizadas o los errores (422). CSRF por cabecera X-CSRFToken."""
    d = _json_body(request)
    if d is None:
        return JsonResponse({"ok": False, "error": "Cuerpo JSON inválido."}, status=400)
    accion = d.get("accion")
    try:
        if accion == "contorno":
            catalogo.fijar_contorno_lote(request.user, str(d.get("lote", "")), d.get("geometry"))
            texto = "Contorno del lote guardado." if d.get("geometry") else "Contorno del lote borrado."
        elif accion == "hilera":
            catalogo.fijar_extremos_hilera(request.user, str(d.get("hilera", "")), d.get("inicio"), d.get("fin"))
            texto = "Inicio y fin de la hilera guardados."
        elif accion == "punto_crear":
            catalogo.crear_punto(request.user, d.get("name", ""), d.get("kind", ""), d.get("lat"), d.get("lon"),
                                 d.get("description", ""))
            texto = "Punto agregado."
        elif accion == "punto_editar":
            catalogo.editar_punto(request.user, int(d.get("id") or 0), d.get("name", ""), d.get("kind", ""),
                                  d.get("lat"), d.get("lon"), d.get("description", ""))
            texto = "Punto guardado."
        elif accion == "punto_eliminar":
            catalogo.eliminar_punto(request.user, int(d.get("id") or 0))
            texto = "Punto eliminado."
        else:
            return JsonResponse({"ok": False, "error": "Acción desconocida."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": " ".join(exc.messages)}, status=422)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Datos inválidos."}, status=422)
    return JsonResponse({"ok": True, "texto": texto, "capas": queries.map_layers()})


@web_view("mapa.ver")
@require_GET
@gzip_page  # JSON sin secretos: comprimirlo no expone tokens (a diferencia de páginas con CSRF)
def mapa_datos(request):
    f = FiltroCasosForm(request.GET)
    return JsonResponse(queries.map_geojson(f.cleaned_data if f.is_valid() else {}))


@web_view("mapa.ver")
def plano(request):
    lotes = FieldLot.objects.filter(active=True)
    lot = get_object_or_404(FieldLot, pk=request.GET.get("lote")) if request.GET.get("lote") else lotes.first()
    f = FiltroCasosForm(request.GET or None)
    data = queries.plano(lot, f.cleaned_data if f.is_valid() else {}) if lot else None
    return render(request, "web/plano.html", {"p": data, "lotes": lotes, "filtro": f})


# ------------------------------------------------------------------ sesiones
@web_view("sesiones.ver")
def sesiones(request):
    qs = (MonitoringSession.objects.select_related("operator", "controller_device")
          .annotate(n_pasadas=Count("passes", distinct=True), n_capturas=Count("captures", distinct=True))
          .order_by("-started_at"))
    page = Paginator(qs, 25).get_page(request.GET.get("pagina"))
    return render(request, "web/sesiones.html", {"page": page})


@web_view("sesiones.ver")
def sesion(request, pk):
    s = get_object_or_404(MonitoringSession.objects.select_related("operator", "controller_device"), pk=pk)
    passes = s.passes.select_related("lot", "row").order_by("started_at")
    captures = (s.captures.select_related("monitoring_pass__row", "quality").order_by("captured_at")
                .annotate(n_cases=Count("case")))
    quality = dict(s.captures.values_list("quality_status").annotate(n=Count("pk")))
    captures = list(captures[:500])
    for c in captures:  # v1.0+: galería de miniaturas (URLs firmadas al renderizar, W-10)
        c.thumb_url = signed_image_url(c, "miniatura")
    return render(request, "web/sesion.html", {
        "s": s, "passes": passes, "cameras": s.cameras.select_related("user", "device"), "incidents": s.incidents.all(),
        "captures": captures, "quality": quality, "total_fotos": sum(quality.values())})


# ------------------------------------------------------------------ reportes
@web_view("reportes.exportar")
def reportes(request):
    return render(request, "web/reportes.html", {"filtro": FiltroCasosForm(request.GET or None),
                                                 "lotes": FieldLot.objects.filter(active=True)})


class _Echo:
    def write(self, value):
        return value


def _csv_safe(value):
    """Evita inyección de fórmulas al abrir el CSV en Excel (celdas que empiezan con = + - @)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@web_view("reportes.exportar")
@require_GET
def exportar_casos(request):
    f = FiltroCasosForm(request.GET)
    qs = queries.filter_cases(queries.bandeja({}), f.cleaned_data if f.is_valid() else {})
    qs = qs.select_related("ai_task").order_by("captured_at")[: settings.WEB["EXPORT_MAX_ROWS"]]
    header = ["caso", "estado", "origen", "lote", "hilera", "lateral", "segmento", "marcador", "lat", "lon",
              "fuente_ubicacion", "capturada", "abierto", "decidido", "decidido_por", "cajas", "confianza_max",
              "modelo", "estado_aviso", "captura"]

    def rows():
        yield header
        for c in qs:
            yield [c.pk, c.status, c.origin, c.lot.code, c.row.number, c.lateral_code,
                   c.segment.code if c.segment_id else "", c.marker.code if c.marker_id else "", c.lat, c.lon,
                   c.location_source, timezone.localtime(c.captured_at).isoformat(),
                   timezone.localtime(c.opened_at).isoformat(),
                   timezone.localtime(c.decided_at).isoformat() if c.decided_at else "",
                   c.decided_by.full_name if c.decided_by_id else "", c.detections_count,
                   f"{c.max_confidence:.3f}" if c.max_confidence is not None else "",
                   c.ai_task.model_version if c.ai_task_id else "", c.notification_status, c.capture_id]

    writer = csv.writer(_Echo())

    def stream():
        yield "﻿"  # BOM: Excel abre el archivo como UTF-8 (tildes y ñ)
        for row in rows():
            yield writer.writerow([_csv_safe(v) for v in row])

    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    name = f"casos_{timezone.localdate():%Y%m%d}.csv"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    audit.record("export", name, "EXPORTACION_CASOS", request.user, None, dict(request.GET.items()))
    return response


# ------------------------------------------------------------------ notificaciones
@web_view("notificaciones.ver")
def notificaciones(request):
    qs = Notification.objects.select_related("case__lot", "case__row").order_by("-created_at")
    estado = request.GET.get("estado")
    if estado:
        qs = qs.filter(status=estado)
    return render(request, "web/notificaciones.html", {"page": Paginator(qs, 50).get_page(request.GET.get("pagina")),
                                                       "estado": estado})


@web_view("destinatarios.gestionar")
@require_http_methods(["GET", "POST"])
def destinatarios(request, pk=None):
    instance = get_object_or_404(NotificationRecipient, pk=pk) if pk else None
    form = RecipientForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        before = None if instance is None else {"active": instance.active, "phone": instance.phone_e164}
        r = form.save(commit=False)
        if form.cleaned_data["opt_in"] and r.opt_in_at is None:
            r.opt_in_at = timezone.now()
        if not form.cleaned_data["opt_in"]:
            r.opt_in_at = None
        r.save()
        form.save_m2m()
        audit.record("notification_recipient", r.pk, "DESTINATARIO_GUARDADO", request.user, before,
                     {"active": r.active, "phone": r.phone_e164, "optIn": r.opt_in_at is not None})
        messages.success(request, M.DESTINATARIO_GUARDADO)
        return redirect("web:destinatarios")
    lista = NotificationRecipient.objects.prefetch_related("lots").select_related("user")
    return render(request, "web/destinatarios.html", {"form": form, "lista": lista, "editando": instance})


# ------------------------------------------------------------------ administración
def _contexto_usuarios(form_nueva=None):
    pendientes = User.objects.filter(status=AccountStatus.PENDIENTE_APROBACION).order_by("created_at")
    todos = User.objects.prefetch_related("user_roles").order_by("full_name")
    solicitudes = PasswordResetRequest.objects.filter(status=PasswordResetRequest.Status.PENDIENTE)
    return {"pendientes": pendientes, "todos": todos, "solicitudes": solicitudes, "approve_form": ApproveForm(),
            "roles_choices": Role.choices, "form_nueva": form_nueva or NuevaCuentaForm()}


@web_view("usuarios.gestionar")
def usuarios(request):
    return render(request, "web/usuarios.html", _contexto_usuarios())


@web_view("usuarios.gestionar")
@require_POST
def usuario_nuevo(request):
    """v1.1 (ADR-W-005): «Nueva cuenta». Con errores vuelve a la misma página con el formulario y sus mensajes."""
    form = NuevaCuentaForm(request.POST)
    if form.is_valid():
        try:
            nuevo, clave = cuentas.create_account(request.user, **form.datos())
        except ValidationError as exc:
            form.add_error(None, exc)  # errores por campo (correo repetido, roles…) del servicio
        else:
            donde = M.CUENTA_CREADA_APP if nuevo.roles == {Role.OPERADOR_CAMPO} else M.CUENTA_CREADA_WEB.format(
                url=request.build_absolute_uri(reverse("web:login")))
            messages.warning(request, M.CUENTA_CREADA.format(nombre=nuevo.full_name, correo=nuevo.email, clave=clave,
                                                             donde=donde), extra_tags="persistente")
            return redirect("web:usuarios")
    return render(request, "web/usuarios.html", _contexto_usuarios(form))


@web_view("usuarios.gestionar")
def usuario_editar(request, pk):
    """v1.3 (ADR-W-007): solo el ADMINISTRADOR corrige nombre, correo (usuario de ingreso), celular y código, y puede
    asignar una contraseña concreta. Dos formularios en la misma página, distinguidos por el botón enviado."""
    cuenta = get_object_or_404(User.objects.prefetch_related("user_roles"), pk=pk)
    datos = EditarCuentaForm(initial={"full_name": cuenta.full_name, "email": cuenta.email, "phone": cuenta.phone,
                                      "employee_code": cuenta.employee_code})
    clave = AsignarContrasenaForm()
    if request.method == "POST":
        if "guardar_datos" in request.POST:
            datos = EditarCuentaForm(request.POST)
            if datos.is_valid():
                try:
                    cuenta, cambio = cuentas.update_account(pk, request.user, **datos.cleaned_data)
                except ValidationError as exc:
                    datos.add_error(None, exc)
                else:
                    messages.success(request, M.CUENTA_EDITADA.format(nombre=cuenta.full_name) if cambio
                                     else M.CUENTA_SIN_CAMBIOS)
                    return redirect("web:usuario_editar", pk=pk)
        elif "asignar_clave" in request.POST:
            clave = AsignarContrasenaForm(request.POST)
            if clave.is_valid():
                try:
                    cuentas.set_password_by_admin(pk, request.user, clave.cleaned_data["password1"],
                                                  clave.cleaned_data["must_change"])
                except ValidationError as exc:
                    for msg in exc.messages:
                        clave.add_error("password1", msg)
                else:
                    extra = "; al ingresar deberá cambiarla" if clave.cleaned_data["must_change"] else ""
                    messages.success(request, M.CONTRASENA_ASIGNADA.format(nombre=cuenta.full_name, extra=extra))
                    return redirect("web:usuario_editar", pk=pk)
        else:
            return HttpResponse(status=400)
    return render(request, "web/usuario_editar.html", {"cuenta": cuenta, "datos": datos, "clave": clave,
                                                         "es_yo": cuenta.pk == request.user.pk})


@web_view("usuarios.gestionar")
@require_POST
def usuario_accion(request, pk, accion):
    try:
        if accion == "aprobar":
            form = ApproveForm(request.POST)
            if not form.is_valid():
                raise ValidationError("Elige al menos un rol.")
            cuentas.approve_user(pk, request.user, form.cleaned_data["roles"])
            messages.success(request, M.CUENTA_APROBADA)
        elif accion == "roles":
            form = ApproveForm(request.POST)
            if not form.is_valid():
                raise ValidationError("Elige al menos un rol.")
            cuentas.set_roles(pk, request.user, form.cleaned_data["roles"])
            messages.success(request, M.CUENTA_ACTUALIZADA)
        elif accion in ("rechazar", "bloquear", "desbloquear"):
            nuevo = {"rechazar": AccountStatus.RECHAZADO, "bloquear": AccountStatus.BLOQUEADO,
                     "desbloquear": AccountStatus.ACTIVO}[accion]
            cuentas.change_status(pk, request.user, nuevo)
            messages.success(request, M.CUENTA_ACTUALIZADA)
        elif accion == "contrasena-temporal":
            user = get_object_or_404(User, pk=pk)
            clave = cuentas.set_temporary_password(pk, request.user)
            messages.warning(request, M.CONTRASENA_TEMPORAL.format(nombre=user.full_name, clave=clave),
                             extra_tags="persistente")
        else:
            return HttpResponse(status=404)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("web:usuarios")


# ------------------------------------------------------------------ v1.2 (ADR-W-006): catálogos del fundo
def _aplicar(form, fn):
    """Valida el formulario y llama al servicio. Los errores del servicio vuelven al formulario (por campo si se
    puede). Devuelve el resultado del servicio, o None si hubo errores."""
    if not form.is_valid():
        return None
    try:
        resultado = fn(form.cleaned_data)
    except ValidationError as exc:
        if hasattr(exc, "error_dict") and set(exc.error_dict) <= set(form.fields):
            form.add_error(None, exc)
        else:
            for mensaje in exc.messages:
                form.add_error(None, mensaje)
        return None
    return True if resultado is None else resultado


def _error_de(exc):
    return " ".join(exc.messages)


def _aviso_sesiones(request, n):
    if n:
        messages.warning(request, M.CATALOGO_SESION_EN_CURSO.format(n=n))


def _volver(request, nombre, pk=None):
    url = reverse(nombre, args=[pk] if pk else [])
    if request.GET.get("inactivos") == "1" or request.POST.get("inactivos") == "1":
        url += "?inactivos=1"
    return redirect(url)


@web_view("catalogos.gestionar")
@require_http_methods(["GET", "POST"])
def catalogos(request):
    inactivos = request.GET.get("inactivos") == "1"
    form = LoteForm(request.POST or None)
    if request.method == "POST":
        lot = _aplicar(form, lambda d: catalogo.crear_lote(request.user, d["code"], d["name"]))
        if lot:
            messages.success(request, M.CATALOGO_LOTE_CREADO.format(lote=lot.code))
            return redirect("web:catalogo_lote", lot.pk)
    return render(request, "web/catalogos.html", {"lotes": queries.catalogo_lotes(inactivos), "form": form,
                                                  "inactivos": inactivos})


@web_view("catalogos.gestionar")
@require_http_methods(["GET", "POST"])
def catalogo_lote(request, pk):
    lot = get_object_or_404(FieldLot, pk=pk)
    inactivos = request.GET.get("inactivos") == "1"
    ultima = lot.rows.order_by("-number").first()
    f_lote = LoteForm(initial={"code": lot.code, "name": lot.name})
    f_hileras = HilerasForm(initial={"desde": (ultima.number + 1) if ultima else 1,
                                     "plantas": ultima.plant_count if ultima else None, "segmento_completo": True})
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "editar":
            f_lote = LoteForm(request.POST)
            if _aplicar(f_lote, lambda d: catalogo.editar_lote(request.user, lot.pk, d["code"], d["name"])):
                messages.success(request, M.CATALOGO_GUARDADO)
                return _volver(request, "web:catalogo_lote", lot.pk)
        elif accion == "hileras":
            f_hileras = HilerasForm(request.POST)
            res = _aplicar(f_hileras, lambda d: catalogo.crear_hileras(
                request.user, lot.pk, d["desde"], d["hasta"], d["plantas"], d["segmento_completo"]))
            if res:
                creadas, saltadas = res
                messages.success(request, M.CATALOGO_HILERAS_CREADAS.format(n=len(creadas)))
                if saltadas:
                    messages.info(request, M.CATALOGO_HILERAS_SALTADAS.format(
                        numeros=", ".join(str(x) for x in saltadas)))
                return _volver(request, "web:catalogo_lote", lot.pk)
        elif accion == "completar":
            n = catalogo.completar_hileras_sin_segmento(request.user, lot.pk)
            messages.success(request, M.CATALOGO_COMPLETADAS.format(n=n))
            return _volver(request, "web:catalogo_lote", lot.pk)
        elif accion in ("desactivar", "reactivar"):
            tipo, obj_id = request.POST.get("tipo"), request.POST.get("id", "")
            valido = (tipo == "lote" and obj_id == lot.pk) or (
                tipo == "hilera" and FieldRow.objects.filter(pk=obj_id, lot=lot).exists())
            if not valido:
                return HttpResponse(status=404)
            try:
                if accion == "desactivar":
                    _aviso_sesiones(request, catalogo.desactivar(request.user, tipo, obj_id))
                    messages.success(request, M.CATALOGO_DESACTIVADO)
                else:
                    catalogo.reactivar(request.user, tipo, obj_id)
                    messages.success(request, M.CATALOGO_REACTIVADO)
            except ValidationError as exc:
                messages.error(request, _error_de(exc))
            return _volver(request, "web:catalogo_lote", lot.pk)
        else:
            return HttpResponse(status=404)
        lot.refresh_from_db()
    return render(request, "web/catalogo_lote.html", {"lot": lot, "inactivos": inactivos, "f_lote": f_lote,
                                                      "f_hileras": f_hileras, **queries.catalogo_lote(lot, inactivos)})


@web_view("catalogos.gestionar")
@require_http_methods(["GET", "POST"])
def catalogo_hilera(request, pk):
    row = get_object_or_404(FieldRow.objects.select_related("lot"), pk=pk)
    datos = queries.catalogo_hilera(row)
    f_hilera = HileraForm(initial={"plant_count": row.plant_count})
    f_segmento = SegmentoForm(initial={"start_plant": 1, "end_plant": row.plant_count})
    f_dividir = DividirForm(initial={"modo": DividirForm.PARTES, "valor": 2, "con_marcadores": True})
    f_marcador = MarcadorForm(segmentos=datos["activos"], initial={"position": "INTERMEDIO"})
    if request.method == "POST":
        accion, obj_id = request.POST.get("accion"), request.POST.get("id", "")
        hecho = None
        if accion == "editar":
            f_hilera = HileraForm(request.POST)
            hecho = _aplicar(f_hilera, lambda d: catalogo.editar_hilera(request.user, row.pk, d["plant_count"]))
        elif accion == "segmento_nuevo":
            f_segmento = SegmentoForm(request.POST)
            hecho = _aplicar(f_segmento, lambda d: catalogo.crear_segmento(
                request.user, row.pk, d["code"], d["start_plant"], d["end_plant"], d["is_pilot"]))
        elif accion == "dividir":
            f_dividir = DividirForm(request.POST)
            hecho = _aplicar(f_dividir, lambda d: catalogo.dividir_hilera(
                request.user, row.pk, partes=d["valor"] if d["modo"] == DividirForm.PARTES else None,
                cada=d["valor"] if d["modo"] == DividirForm.CADA else None, con_marcadores=d["con_marcadores"]))
            if hecho:
                _aviso_sesiones(request, catalogo.sesiones_en_curso(FieldRow.objects.filter(pk=row.pk)))
        elif accion == "marcador_nuevo":
            f_marcador = MarcadorForm(request.POST, segmentos=datos["activos"])
            hecho = _aplicar(f_marcador, lambda d: catalogo.crear_marcador(
                request.user, row.pk, d["code"], d["position"], d["segment"] or None, d["description"],
                d["lat"], d["lon"]))
        elif accion in ("segmento_editar", "marcador_editar"):
            # Formularios en línea de cada fila: los errores se muestran como mensaje y se vuelve a la página.
            if accion == "segmento_editar":
                form = SegmentoForm(request.POST)
                obj_ok = FieldSegment.objects.filter(pk=obj_id, row=row).exists()
                fn = (lambda d: catalogo.editar_segmento(request.user, obj_id, d["code"], d["start_plant"],
                                                         d["end_plant"], d["is_pilot"]))
            else:
                form = MarcadorForm(request.POST, segmentos=datos["activos"])
                obj_ok = Marker.objects.filter(pk=obj_id, row=row).exists()
                fn = (lambda d: catalogo.editar_marcador(request.user, obj_id, d["code"], d["position"],
                                                         d["segment"] or None, d["description"], d["lat"], d["lon"]))
            if not obj_ok:
                return HttpResponse(status=404)
            if _aplicar(form, fn):
                messages.success(request, M.CATALOGO_GUARDADO)
            else:
                messages.error(request, M.CATALOGO_NO_GUARDADO.format(
                    errores=" ".join(e for errs in form.errors.values() for e in errs)))
            return redirect(reverse("web:catalogo_hilera", args=[row.pk]) + f"#{obj_id}")
        elif accion in ("desactivar", "reactivar"):
            tipo = request.POST.get("tipo")
            pertenece = {"hilera": lambda: obj_id == row.pk,
                         "segmento": lambda: FieldSegment.objects.filter(pk=obj_id, row=row).exists(),
                         "marcador": lambda: Marker.objects.filter(pk=obj_id, row=row).exists()}
            if tipo not in pertenece or not pertenece[tipo]():
                return HttpResponse(status=404)
            try:
                if accion == "desactivar":
                    _aviso_sesiones(request, catalogo.desactivar(request.user, tipo, obj_id))
                    messages.success(request, M.CATALOGO_DESACTIVADO)
                else:
                    catalogo.reactivar(request.user, tipo, obj_id)
                    messages.success(request, M.CATALOGO_REACTIVADO)
            except ValidationError as exc:
                messages.error(request, _error_de(exc))
            return redirect("web:catalogo_hilera", row.pk)
        else:
            return HttpResponse(status=404)
        if hecho:
            messages.success(request, M.CATALOGO_GUARDADO)
            return redirect("web:catalogo_hilera", row.pk)
        row.refresh_from_db()
    return render(request, "web/catalogo_hilera.html", {
        "row": row, "lot": row.lot, "f_hilera": f_hilera, "f_segmento": f_segmento, "f_dividir": f_dividir,
        "f_marcador": f_marcador, "posiciones": MarcadorForm.base_fields["position"].choices, **datos})


@web_view("dispositivos.gestionar")
def dispositivos(request):
    lista = Device.objects.select_related("user", "revoked_by").order_by("-last_seen_at")
    return render(request, "web/dispositivos.html", {"lista": lista})


@web_view("dispositivos.gestionar")
@require_POST
def dispositivo_revocar(request, pk):
    cuentas.revoke_device(pk, request.user)
    messages.success(request, M.CELULAR_REVOCADO)
    return redirect("web:dispositivos")


@web_view("ia.ver")
def ia_estado(request):
    conteo = dict(AiTask.objects.values_list("status").annotate(n=Count("pk")))
    errores = (AiTask.objects.filter(status=AiStatus.ERROR_DE_ANALISIS).select_related("capture", "model_config")
               .order_by("-finished_at")[:100])
    return render(request, "web/ia.html", {"conteo": conteo, "errores": errores,
                                           "modelo": ModelConfig.objects.filter(active=True).first(),
                                           "estados": AiStatus.choices, "total": sum(conteo.values())})


@web_view("ia.reencolar")
@require_POST
def ia_reencolar(request, pk):
    try:
        ia.requeue_failed(pk, request.user)
        messages.success(request, M.TAREA_REENCOLADA)
    except ia.InvalidTaskState as exc:
        messages.error(request, str(exc))
    return redirect("web:ia")


@web_view("auditoria.ver")
def auditoria(request):
    qs = AuditEvent.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(entity_id__icontains=q) | Q(action__icontains=q))
    return render(request, "web/auditoria.html", {"page": Paginator(qs, 50).get_page(request.GET.get("pagina")),
                                                  "q": q})


# ------------------------------------------------------------------ v1.3.1 (ADR-W-008): limpieza de fotos
@web_view("limpieza.ejecutar")
def sesion_eliminar(request, pk):
    from evidencias import limpieza

    s = get_object_or_404(MonitoringSession.objects.select_related("operator"), pk=pk)
    error = ""
    if request.method == "POST":
        try:
            r = limpieza.eliminar_sesion(s.pk, request.user, request.POST.get("confirmacion"))
        except limpieza.LimpiezaInvalida as exc:
            error = str(exc)
        else:
            messages.success(request, M.LIMPIEZA_SESION_OK.format(**r))
            pendientes = limpieza.pendientes_en_nube()
            if pendientes:
                messages.warning(request, M.LIMPIEZA_NUBE_PENDIENTE.format(n=pendientes))
            return redirect("web:sesiones")
    return render(request, "web/sesion_eliminar.html", {"s": s, "r": limpieza.resumen_sesion(s), "error": error,
                                                         "palabra": limpieza.CONFIRMAR})


@web_view("limpieza.ejecutar")
def limpieza_fotos(request):
    from evidencias import limpieza
    from evidencias.models import DeletedCapture

    try:
        dias = max(1, min(int(request.POST.get("dias") or request.GET.get("dias") or 30), 3650))
    except ValueError:
        dias = 30
    error = ""
    if request.method == "POST":
        try:
            n = limpieza.eliminar_descartadas(dias, request.user, request.POST.get("confirmacion"))
        except limpieza.LimpiezaInvalida as exc:
            error = str(exc)
        else:
            messages.success(request, M.LIMPIEZA_DESCARTADAS_OK.format(n=n) if n else M.LIMPIEZA_NADA)
            pendientes = limpieza.pendientes_en_nube()
            if pendientes:
                messages.warning(request, M.LIMPIEZA_NUBE_PENDIENTE.format(n=pendientes))
            return redirect(f"{reverse('web:limpieza')}?dias={dias}")
    return render(request, "web/limpieza.html", {
        "dias": dias, "candidatas": limpieza.descartadas_qs(dias).count(), "error": error,
        "palabra": limpieza.CONFIRMAR, "pendientes_nube": limpieza.pendientes_en_nube(),
        "total_borradas": DeletedCapture.objects.count(),
        "ultimas": DeletedCapture.objects.select_related("deleted_by").order_by("-deleted_at")[:10]})
