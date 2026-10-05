#!/usr/bin/env bash
# deploy/desinstalar.sh — Retira la plataforma del VPS cuando termine el proyecto y deja el servidor como estaba.
# No toca OpenClaw ni Traefik. Los datos siguen en Supabase y las fotos en Cloudinary (bórralos en sus paneles
# si ya no se necesitan, después de exportar lo que quieras guardar).
set -euo pipefail
cd "$(dirname "$0")"
echo "Esto detiene y elimina los contenedores e imágenes de la plataforma y la carpeta /srv/riachuelo."
read -r -p "Escribe ELIMINAR para continuar: " r
[ "$r" = "ELIMINAR" ] || { echo "Cancelado."; exit 0; }
docker compose down --rmi all --volumes --remove-orphans || true
docker builder prune -f >/dev/null || true
cd / && rm -rf /srv/riachuelo
echo "Listo. Quita también el registro DNS «monitoreo» en Hostinger."
