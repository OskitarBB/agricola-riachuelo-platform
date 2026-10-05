#!/usr/bin/env bash
# scripts/iniciar.sh — Arranque local en Linux o macOS (equivalente a iniciar.bat / scripts/iniciar.ps1).
#   ./scripts/iniciar.sh            web + API en :8000 y worker de IA en segundo plano
#   DEMO=1 ./scripts/iniciar.sh     vuelve a cargar los datos de demostración
#   IA=1 ./scripts/iniciar.sh       instala también onnxruntime/numpy (modelo YOLO en ONNX)
set -euo pipefail
cd "$(dirname "$0")/.."
PUERTO="${PUERTO:-8000}"
PY="$(command -v python3.12 || command -v python3.13 || command -v python3.11 || command -v python3.10 || command -v python3)"
"$PY" -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 14), "Se necesita Python 3.10–3.13"'
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VPY=.venv/bin/python
echo "==> Instalando dependencias"
"$VPY" -m pip install -q --disable-pip-version-check -r requirements.txt
[ "${IA:-0}" = "1" ] && "$VPY" -m pip install -q --disable-pip-version-check -r requirements-ia.txt
PRIMERA=0
if [ ! -f .env ]; then
  echo "==> Creando .env con una clave secreta nueva"
  CLAVE="$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(60))')"
  sed "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${CLAVE}|" .env.example > .env
  PRIMERA=1
fi
echo "==> Probando la conexión a la base de datos"
"$VPY" manage.py comprobar_bd || { echo "Corrige DATABASE_URL en .env según el mensaje de arriba."; exit 1; }
echo "==> Migraciones"
"$VPY" manage.py migrate --noinput
HAY="$("$VPY" manage.py shell -v 0 --no-imports -c 'from cuentas.models import User; print(int(User.objects.exists()))' | tail -1)"
if [ "${DEMO:-0}" = "1" ] || [ "$PRIMERA" = "1" ] || [ "$HAY" = "0" ]; then
  echo "==> Datos de demostración (cuentas *@demo.pe, contraseña Demo2026)"
  "$VPY" manage.py sembrar_demo
fi
"$VPY" manage.py diagnostico || echo "   Hay errores de configuración (arriba). La web arranca igual."
if [ "${SIN_WORKER:-0}" != "1" ]; then
  echo "==> Worker de IA en segundo plano (registro en worker.log)"
  "$VPY" manage.py worker_ia > worker.log 2>&1 &
  WORKER=$!
  trap 'kill $WORKER 2>/dev/null || true' EXIT
fi
echo "==> Web y API: http://127.0.0.1:${PUERTO}/  (Ctrl+C para detener)"
"$VPY" manage.py runserver "0.0.0.0:${PUERTO}"
