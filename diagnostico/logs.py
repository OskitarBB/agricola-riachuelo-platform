# diagnostico/logs.py — Formato del registro en consola: hora, nivel con color e ícono, origen y traceId.
# Pensado para leerlo «en vivo» mientras se usa la plataforma (python manage.py runserver / worker_ia).
# Sin dependencias: códigos ANSI (Windows 10+ los admite; LOG_COLOR=0 los desactiva).
import logging
import os
import sys

from diagnostico.contexto import current_trace_id

RESET = "\033[0m"
COLORES = {
    "DEBUG": "\033[90m",
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;41;97m",
}
ICONOS = {"DEBUG": "·", "INFO": "●", "WARNING": "▲", "ERROR": "✖", "CRITICAL": "‼"}
GRIS = "\033[90m"


def _color_habilitado() -> bool:
    if os.environ.get("LOG_COLOR", "1") in ("0", "false", "False", "no"):
        return False
    if os.name == "nt":  # activa el modo VT de la consola de Windows (cmd y PowerShell)
        os.system("")
    stream = sys.stderr
    return hasattr(stream, "isatty") and stream.isatty()


class ConsoleFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.color = _color_habilitado()

    def format(self, record):
        hora = self.formatTime(record, "%H:%M:%S")
        nivel = record.levelname
        icono = ICONOS.get(nivel, "•")
        trace = getattr(record, "trace_id", "") or current_trace_id()
        origen = record.name.replace("riachuelo.", "")
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            msg += "\n" + self.formatStack(record.stack_info)
        traza = f" [{trace}]" if trace else ""
        if not self.color:
            return f"{hora} {icono} {nivel:<7} {origen}{traza} — {msg}"
        c = COLORES.get(nivel, "")
        return f"{GRIS}{hora}{RESET} {c}{icono} {nivel:<7}{RESET} {GRIS}{origen}{traza}{RESET} {msg}"
