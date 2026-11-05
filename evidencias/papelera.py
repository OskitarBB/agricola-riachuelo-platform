# evidencias/papelera.py — QUÉ HACE: v1.5 (ADR-W-012) papelera de fotos, a pedido del ADMINISTRADOR.
#   · enviar(): la foto sale de todas las listas (bandeja, mapa, plano, panel, sesiones, descartadas, exportación y
#     «Ubicar plaga» de la app) y no se analiza. Si es la foto principal de un caso, el caso también se oculta y sus
#     avisos pendientes se anulan. Nada se borra todavía.
#   · restaurar(): vuelve todo como estaba (los avisos anulados no se reenvían).
#   · eliminar() / vaciar(): borrado definitivo por la misma ruta que la limpieza (base en una transacción →
#     Cloudinary → los celulares borran su copia al consultar /mobile/deleted-captures).
#   · vaciar_vencidas(): el worker borra solas las fotos con más de PAPELERA_DIAS días en la papelera.
# La auditoría conserva cada paso (quién, cuándo, motivo).
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from auditoria import services as audit
from evidencias import limpieza
from evidencias.models import Capture, DeletionReason


class PapeleraInvalida(Exception):
    pass


def en_papelera():
    return Capture.objects.filter(trashed_at__isnull=False)


def vence(capture):
    """Fecha en que el worker borra la foto para siempre."""
    return capture.trashed_at + timedelta(days=settings.PAPELERA_DIAS)


def enviar(capture_id, user, motivo=""):
    from notificaciones import services as notif
    from revision.models import Case

    with transaction.atomic():
        c = Capture.objects.select_for_update().get(pk=capture_id)
        if c.trashed_at is not None:
            raise PapeleraInvalida("La foto ya está en la papelera.")
        c.trashed_at, c.trashed_by, c.trash_reason = timezone.now(), user, " ".join((motivo or "").split())[:200]
        c.save(update_fields=["trashed_at", "trashed_by", "trash_reason"])
        caso = Case.objects.filter(capture=c).first()
        anulados = notif.cancel_pending_for_case(caso) if caso else 0
        audit.record("capture", c.pk, "FOTO_A_PAPELERA", user, None,
                     {"motivo": c.trash_reason, "caso": str(caso.pk) if caso else None, "avisosAnulados": anulados})
    return c, caso


def restaurar(capture_id, user):
    with transaction.atomic():
        c = Capture.objects.select_for_update().get(pk=capture_id)
        if c.trashed_at is None:
            raise PapeleraInvalida("La foto no está en la papelera.")
        antes = {"trashedAt": c.trashed_at.isoformat(), "motivo": c.trash_reason}
        c.trashed_at, c.trashed_by, c.trash_reason = None, None, ""
        c.save(update_fields=["trashed_at", "trashed_by", "trash_reason"])
        audit.record("capture", c.pk, "FOTO_RESTAURADA", user, antes, None)
    return c


def eliminar(capture_ids, user, accion="FOTOS_PAPELERA_ELIMINADAS"):
    """Borra para siempre fotos QUE ESTÁN en la papelera (las demás se ignoran). Devuelve cuántas se borraron."""
    with transaction.atomic():
        ids = limpieza._borrar_capturas(en_papelera().filter(pk__in=list(capture_ids)), user, DeletionReason.PAPELERA)
        if ids:
            audit.record("capture", "papelera", accion, user, None,
                         {"fotos": len(ids), "ejemplo": [str(i) for i in ids[:20]]})
    if ids:
        limpieza.borrar_en_nube_seguro()
    return len(ids)


def vaciar(user, confirmacion):
    if (confirmacion or "").strip().upper() != limpieza.CONFIRMAR:
        raise PapeleraInvalida(f"Para confirmar escribe {limpieza.CONFIRMAR}.")
    return eliminar(en_papelera().values_list("pk", flat=True), user, "PAPELERA_VACIADA")


def vaciar_vencidas(limite=500):
    """Lo llama el worker: borra las fotos con más de PAPELERA_DIAS días en la papelera."""
    hasta = timezone.now() - timedelta(days=settings.PAPELERA_DIAS)
    ids = list(en_papelera().filter(trashed_at__lt=hasta).order_by("trashed_at").values_list("pk", flat=True)[:limite])
    return eliminar(ids, None, "PAPELERA_VENCIDAS_ELIMINADAS") if ids else 0
