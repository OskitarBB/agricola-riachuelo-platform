#!/usr/bin/env bash
# scripts/empaquetar.sh — Crea riachuelo-plataforma.tar.gz (código sin secretos, sin .venv ni datos) para subirlo al VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
tar --exclude-from=<(sed -e '/^#/d' -e '/^!/d' -e '/^$/d' -e 's#^\*\*/##' -e 's#/$##' .dockerignore) \
    --exclude='./deploy/modelos/*.onnx' -czf riachuelo-plataforma.tar.gz .
echo "Creado riachuelo-plataforma.tar.gz ($(du -h riachuelo-plataforma.tar.gz | cut -f1))"
