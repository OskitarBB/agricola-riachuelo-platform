"""Audit helpers used by services and web actions."""


def log_event(actor, action, target=None, payload=None):
    from auditoria.models import AuditEvent

    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        payload=payload or {},
    )
