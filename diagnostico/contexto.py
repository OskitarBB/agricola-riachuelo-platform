# diagnostico/contexto.py — traceId de la petición (o de la tarea del worker) disponible en cualquier capa:
# la API lo devuelve en ApiErrorBody, la auditoría lo guarda y cada línea del registro lo muestra.
import contextvars
import uuid

_trace_id = contextvars.ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def set_trace_id(value: str):
    return _trace_id.set(value)


def reset_trace_id(token) -> None:
    _trace_id.reset(token)


def current_trace_id() -> str:
    return _trace_id.get()
