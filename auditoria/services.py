# auditoria/services.py — Registro de auditoría. Lo llaman los servicios dentro de su transacción.
from auditoria.models import AuditEvent
from diagnostico.contexto import current_trace_id


def record(entity_type, entity_id, action, user=None, before=None, after=None, trace_id=""):
    return AuditEvent.objects.create(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        user=user if (user is not None and user.is_authenticated) else None,
        before=before,
        after=after,
        trace_id=trace_id or current_trace_id(),
    )
