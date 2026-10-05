#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # La consola de Windows puede no estar en UTF-8 (tildes y símbolos ✔ ✖ de los mensajes): nunca debe romper.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise SystemExit(
            "No se encontró Django. Activa el entorno virtual (.venv) e instala las dependencias:\n"
            "  Windows:  .venv\\Scripts\\activate  y  pip install -r requirements.txt\n"
            "  o ejecuta iniciar.bat, que lo hace todo."
        ) from exc
    execute_from_command_line(sys.argv)
