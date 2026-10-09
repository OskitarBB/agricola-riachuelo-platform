# evidencias/limpieza.py — QUÉ HACE: v1.3.1 (ADR-W-008) borra fotos PARA SIEMPRE, a pedido del ADMINISTRADOR:
#   · una sesión completa (pasadas, secuencias, fotos, análisis, casos, decisiones y avisos de esa sesión);
#   · las fotos descartadas por la IA (o sin indicios) de más de N días, que no tienen caso.
# Orden: 1) base de datos en UNA transacción (se anota cada foto en deleted_captures); 2) Cloudinary, fuera de la
# transacción (si falla, el worker reintenta con borrar_en_nube); 3) los celulares borran su copia local al consultar
# GET /api/v1/mobile/deleted-captures. La auditoría conserva el hecho (quién, cuándo, cuántas), nunca la foto.
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from auditoria import services as audit
from evidencias import nube
from evidencias.models import Capture, DeletedCapture, DeletedSession, DeletionReason

log = logging.getLogger("riachuelo.limpieza")

CONFIRMAR = "ELIMINAR"  # texto que el administrador escribe para confirmar
LOTE_NUBE = 100  # Cloudinary acepta hasta 100 public_id por llamada a delete_resources


class LimpiezaInvalida(Exception):
    pass


# ------------------------------------------------------------------ qué se puede borrar
def descartadas_qs(dias):
    """Fotos sin caso cuyo análisis terminó «Sin indicios» o «Descartado por la IA», tomadas hace más de `dias` días.
    Nunca entra una foto con caso (decidido o pendiente) ni una con análisis pendiente o con error."""
    from ia.models import AiStatus, AiTask
    from revision.models import Case

    if dias < 1:
        raise LimpiezaInvalida("Los días deben ser 1 o más.")
    limite = timezone.now() - timedelta(days=dias)
    finales = [AiStatus.SIN_INDICIOS_IA, AiStatus.DESCARTADO_POR_IA]
    otra_tarea = AiTask.objects.filter(capture=OuterRef("pk")).exclude(status__in=finales)
    con_tarea = AiTask.objects.filter(capture=OuterRef("pk"), status__in=finales)
    con_caso = Case.objects.filter(capture=OuterRef("pk"))
    return (Capture.objects.filter(captured_at__lt=limite)
            .filter(Exists(con_tarea)).exclude(Exists(otra_tarea)).exclude(Exists(con_caso)))


def resumen_sesion(session):
    from revision.models import Case, ReviewStatus

    casos = Case.objects.filter(session=session)
    return {"fotos": Capture.objects.filter(session=session).count(), "casos": casos.count(),
            "decididos": casos.exclude(status=ReviewStatus.PENDIENTE_REVISION).count(),
            "pasadas": session.passes.count()}


# ------------------------------------------------------------------ borrado en la base
def _borrar_capturas(capturas, user, motivo):
    """Dentro de una transacción abierta. Borra casos, decisiones, avisos, análisis y calidad de esas fotos, anota cada
    foto en deleted_captures y borra las filas de captures. Devuelve la lista de capture_id borrados."""
    from ia.models import AiTask
    from notificaciones.models import Notification
    from revision.models import Case, HumanReview

    capturas = list(capturas.select_for_update(of=("self",)).only(
        "capture_id", "session_id", "cloudinary_public_id"))
    if not capturas:
        return []
    ids = [c.capture_id for c in capturas]
    casos = Case.objects.filter(capture_id__in=ids)
    Notification.objects.filter(case__in=casos).delete()
    reviews = HumanReview.objects.filter(case__in=casos)
    reviews.update(supersedes=None)  # la cadena de correcciones apunta a sí misma (PROTECT)
    reviews.delete()
    casos.delete()
    AiTask.objects.filter(capture_id__in=ids).delete()  # las cajas (detections) se borran en cascada
    Capture.objects.filter(replaces_capture_id__in=ids).update(replaces_capture=None)
    ahora = timezone.now()
    DeletedCapture.objects.bulk_create([
        DeletedCapture(capture_id=c.capture_id, session_id=c.session_id, cloudinary_public_id=c.cloudinary_public_id,
                       reason=motivo, deleted_at=ahora, deleted_by=user if getattr(user, "is_authenticated", False)
                       else None) for c in capturas], ignore_conflicts=True)
    Capture.objects.filter(capture_id__in=ids).delete()  # quality_results se borra en cascada
    return ids


def eliminar_sesion(session_id, user, confirmacion):
    from monitoreo.models import MonitoringSession

    if (confirmacion or "").strip().upper() != CONFIRMAR:
        raise LimpiezaInvalida(f"Para confirmar escribe {CONFIRMAR}.")
    with transaction.atomic():
        session = MonitoringSession.objects.select_for_update().get(pk=session_id)
        resumen = resumen_sesion(session)
        ids = _borrar_capturas(Capture.objects.filter(session=session), user, DeletionReason.SESION)
        datos = {"operator": str(session.operator_id), "startedAt": session.started_at.isoformat()
                 if session.started_at else None, **resumen}
        session.delete()  # pasadas, secuencias, incidencias y cámaras se borran en cascada
        DeletedSession.objects.get_or_create(session_id=session_id, defaults={
            "deleted_by": user if getattr(user, "is_authenticated", False) else None})
        audit.record("session", session_id, "SESION_ELIMINADA", user, datos, {"fotosBorradas": len(ids)})
    borrar_en_nube_seguro()
    return {"fotos": len(ids), **resumen}


def eliminar_descartadas(dias, user, confirmacion, limite=2000):
    if (confirmacion or "").strip().upper() != CONFIRMAR:
        raise LimpiezaInvalida(f"Para confirmar escribe {CONFIRMAR}.")
    with transaction.atomic():
        pks = list(descartadas_qs(dias).order_by("captured_at").values_list("pk", flat=True)[:limite])
        ids = _borrar_capturas(Capture.objects.filter(pk__in=pks), user, DeletionReason.DESCARTADAS)
        if ids:
            audit.record("capture", "limpieza", "FOTOS_DESCARTADAS_ELIMINADAS", user, None,
                         {"fotos": len(ids), "dias": dias, "ejemplo": [str(i) for i in ids[:20]]})
    borrar_en_nube_seguro()
    return len(ids)


# ------------------------------------------------------------------ Cloudinary (fuera de la transacción)
def borrar_en_nube(max_lotes=5):
    """Borra en Cloudinary las fotos anotadas y aún no borradas allí. Lo llaman las acciones de limpieza y el worker
    (reintento). Devuelve (borradas, con_error)."""
    pendientes = DeletedCapture.objects.filter(cloud_deleted_at__isnull=True).order_by("deleted_at")
    borradas = errores = 0
    for _ in range(max_lotes):
        lote = list(pendientes[:LOTE_NUBE])
        if not lote:
            break
        ok, fallo = nube.delete_public_ids([d.cloudinary_public_id for d in lote])
        ahora = timezone.now()
        for d in lote:
            if d.cloudinary_public_id in ok:
                d.cloud_deleted_at, d.cloud_error = ahora, ""
                borradas += 1
            else:
                d.cloud_error = (fallo.get(d.cloudinary_public_id) or "sin respuesta")[:300]
                errores += 1
        DeletedCapture.objects.bulk_update(lote, ["cloud_deleted_at", "cloud_error"])
        if errores:
            break  # la nube falla: se reintenta en la próxima vuelta del worker
    return borradas, errores


def borrar_en_nube_seguro():
    try:
        return borrar_en_nube()
    except Exception as exc:  # la web no falla por la nube: el worker reintenta
        log.warning("No se pudo borrar en Cloudinary ahora (%s: %s): el worker reintentará", exc.__class__.__name__,
                    str(exc)[:200])
        return 0, 0


def pendientes_en_nube():
    return DeletedCapture.objects.filter(cloud_deleted_at__isnull=True).count()


def _desde(qs, desde, limite):
    """Filas con deleted_at > desde, las más antiguas primero. Si se llena el límite, agrega TODAS las que comparten
    la última marca de tiempo (un borrado masivo las crea juntas) para que el cursor nunca salte filas."""
    if desde is not None:
        qs = qs.filter(deleted_at__gt=desde)
    filas = list(qs.order_by("deleted_at")[:limite])
    lleno = len(filas) == limite
    if lleno:
        ultima = filas[-1].deleted_at
        vistos = {f.pk for f in filas}
        filas += [f for f in qs.filter(deleted_at=ultima) if f.pk not in vistos]
    return filas, lleno


def borradas_desde(desde, limite=5000):
    """Para la app (GET /mobile/deleted-captures): fotos y sesiones borradas después de `desde`."""
    fotos, mas_fotos = _desde(DeletedCapture.objects.all(), desde, limite)
    sesiones, mas_sesiones = _desde(DeletedSession.objects.all(), desde, limite)
    marcas = [f.deleted_at for f in fotos] + [s.deleted_at for s in sesiones]
    if mas_fotos or mas_sesiones:  # el cursor avanza solo hasta lo que se entregó completo
        cursor = min(fotos[-1].deleted_at if mas_fotos else max(marcas),
                     sesiones[-1].deleted_at if mas_sesiones else max(marcas))
        fotos = [f for f in fotos if f.deleted_at <= cursor]
        sesiones = [s for s in sesiones if s.deleted_at <= cursor]
    else:
        cursor = max(marcas) if marcas else desde
    return {"captures": [(f.capture_id, f.session_id) for f in fotos], "sessions": [s.session_id for s in sesiones],
            "cursor": cursor, "hasMore": mas_fotos or mas_sesiones}


__all__ = ["CONFIRMAR", "LimpiezaInvalida", "descartadas_qs", "resumen_sesion", "eliminar_sesion",
           "eliminar_descartadas", "borrar_en_nube", "borrar_en_nube_seguro", "pendientes_en_nube", "borradas_desde"]
