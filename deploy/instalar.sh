#!/usr/bin/env bash
# deploy/instalar.sh — Instala (o reinstala) la plataforma en el VPS, junto al Traefik y al OpenClaw que ya corren.
#
#   bash /srv/riachuelo/deploy/instalar.sh
#
# 1) revisa Docker y detecta el Traefik existente (red, entrypoints 80/443 y resolvedor de certificados),
# 2) crea deploy/.env.piloto la primera vez (con clave secreta) y se detiene para que pongas Supabase y Cloudinary,
# 3) valida el .env.piloto, revisa el DNS, construye la imagen y levanta web + worker con límites de RAM/CPU,
# 4) espera a que responda y ejecuta el diagnóstico. No modifica OpenClaw, Traefik ni nada fuera de /srv/riachuelo.
set -euo pipefail
cd "$(dirname "$0")"
DOMINIO="${DOMINIO:-monitoreo.agricolariachuelo.org}"

verde() { printf '\033[32m%s\033[0m\n' "$*"; }
amarillo() { printf '\033[33m%s\033[0m\n' "$*"; }
paso() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
falla() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || falla "Ejecuta como root (en la consola del VPS ya eres root)."

# ------------------------------------------------------------------ 1. Docker y Traefik
paso "Revisando Docker"
command -v docker >/dev/null || falla "No está Docker."
docker compose version >/dev/null 2>&1 || falla "Falta el plugin «docker compose»."
verde "  $(docker --version)"

paso "Detectando el Traefik que ya usa OpenClaw"
TRAEFIK="$(docker ps --format '{{.Names}}' | grep -i traefik | head -n1 || true)"
[ -n "$TRAEFIK" ] || falla "No encontré un contenedor de Traefik corriendo (docker ps)."
verde "  Contenedor: $TRAEFIK"

MODO_RED="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$TRAEFIK")"
if [ "$MODO_RED" = "host" ]; then
  # Traefik usa la red del VPS (modo host): llega a cualquier red de Docker, así que la plataforma usa una propia.
  RED="riachuelo-proxy"
  docker network inspect "$RED" >/dev/null 2>&1 || docker network create "$RED" >/dev/null
else
  RED="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$TRAEFIK" \
        | grep -vE '^(bridge|host|none)?$' | head -n1 || true)"
  if [ -z "$RED" ]; then
    # Traefik solo en la red «bridge» por defecto: se le suma una red propia (no cambia nada de OpenClaw).
    RED="riachuelo-proxy"
    docker network inspect "$RED" >/dev/null 2>&1 || docker network create "$RED" >/dev/null
    docker network connect "$RED" "$TRAEFIK" 2>/dev/null || true
    amarillo "  Traefik se conectó también a la red $RED (si se recrea Traefik, vuelve a ejecutar instalar.sh)."
  fi
fi
if [ -z "$RED" ]; then
  echo "  Modo de red de Traefik: $MODO_RED"
  falla "No pude saber en qué red está Traefik. Mándame: docker inspect -f '{{json .NetworkSettings.Networks}}' $TRAEFIK"
fi

ARGS="$(docker inspect -f '{{join .Config.Cmd " "}} {{join .Args " "}}' "$TRAEFIK" | tr ' ' '\n')"
ENTRY_HTTPS="$(grep -oP '^--entry[pP]oints\.\K[^.=]+(?=\.address=[^ ]*:443$)' <<<"$ARGS" | head -n1 || true)"
ENTRY_HTTP="$(grep -oP '^--entry[pP]oints\.\K[^.=]+(?=\.address=[^ ]*:80$)' <<<"$ARGS" | head -n1 || true)"
RESOLVER="$(grep -oP '^--certificates[rR]esolvers\.\K[^.=]+' <<<"$ARGS" | head -n1 || true)"

# Si Traefik se configuró por archivo, se copian los valores de las etiquetas de los contenedores que ya publica.
if [ -z "$ENTRY_HTTPS" ] || [ -z "$RESOLVER" ]; then
  ETIQ="$(docker ps -q | xargs -r docker inspect -f '{{range $k, $v := .Config.Labels}}{{$k}}={{$v}}{{"\n"}}{{end}}')"
  [ -n "$RESOLVER" ] || RESOLVER="$(grep -oP '^traefik\.http\.routers\.[^.]+\.tls\.certresolver=\K.+' <<<"$ETIQ" | head -n1 || true)"
  [ -n "$ENTRY_HTTPS" ] || ENTRY_HTTPS="$(grep -oP '^traefik\.http\.routers\.[^.]+\.entrypoints=\K.+' <<<"$ETIQ" \
                                            | grep -iE 'secure|https|443' | head -n1 || true)"
fi
ENTRY_HTTPS="${ENTRY_HTTPS:-websecure}"
ENTRY_HTTP="${ENTRY_HTTP:-web}"
if [ -z "$RESOLVER" ]; then
  echo "  Argumentos de Traefik:"; grep -E '^--(entry|certificates)' <<<"$ARGS" | sed 's/email=.*/email=***/' || true
  falla "No pude detectar el resolvedor de certificados de Traefik (manda captura de lo de arriba)."
fi
verde "  Modo: $MODO_RED · Red: $RED · HTTPS: $ENTRY_HTTPS · HTTP: $ENTRY_HTTP · certificados: $RESOLVER"

cat > .env <<VARS
# Generado por instalar.sh (variables de docker-compose, sin secretos)
DOMINIO=$DOMINIO
TRAEFIK_NETWORK=$RED
TRAEFIK_ENTRY_HTTPS=$ENTRY_HTTPS
TRAEFIK_ENTRY_HTTP=$ENTRY_HTTP
TRAEFIK_CERTRESOLVER=$RESOLVER
VARS

# ------------------------------------------------------------------ 2. secretos
chmod 700 /srv/riachuelo 2>/dev/null || true
mkdir -p modelos
if [ ! -f .env.piloto ]; then
  paso "Creando deploy/.env.piloto"
  cp env.piloto.plantilla .env.piloto
  CLAVE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(60))')"
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$CLAVE|" .env.piloto
  sed -i "s|monitoreo.agricolariachuelo.org|$DOMINIO|g" .env.piloto
  chmod 600 .env.piloto
  amarillo "  Falta poner DATABASE_URL (Supabase del piloto) y CLOUDINARY_URL. Edita el archivo con:"
  amarillo "      nano $(pwd)/.env.piloto"
  amarillo "  (Ctrl+O, Enter para guardar; Ctrl+X para salir) y vuelve a ejecutar: bash $(pwd)/instalar.sh"
  exit 0
fi
chmod 600 .env.piloto

paso "Revisando deploy/.env.piloto (sin mostrar secretos)"
valor() { grep -E "^$1=" .env.piloto | tail -n1 | cut -d= -f2- || true; }
ERRORES=0
for v in DJANGO_SECRET_KEY DATABASE_URL CLOUDINARY_URL; do
  if [ -z "$(valor "$v")" ]; then amarillo "  ✖ Falta $v"; ERRORES=1; fi
done
if grep -qE '^(DATABASE_URL|CLOUDINARY_URL)=.*(<|>|\[YOUR-PASSWORD\])' .env.piloto; then
  amarillo "  ✖ DATABASE_URL o CLOUDINARY_URL todavía tienen el texto de ejemplo (<...> o [YOUR-PASSWORD])"; ERRORES=1
fi
if grep -qE '^DATABASE_URL=.*:6543/' .env.piloto; then amarillo "  ✖ DATABASE_URL usa el puerto 6543: usa el Session pooler (5432)"; ERRORES=1; fi
if grep -qE '^(DATABASE_URL|CLOUDINARY_URL)=["'"'"']' .env.piloto; then amarillo "  ✖ Quita las comillas de las URLs"; ERRORES=1; fi
[ "$ERRORES" -eq 0 ] || falla "Corrige deploy/.env.piloto (nano $(pwd)/.env.piloto) y vuelve a ejecutar."
verde "  ✔ Variables obligatorias presentes"

# ------------------------------------------------------------------ 3. DNS
paso "Revisando el DNS de $DOMINIO"
IP_PUBLICA="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
IP_DNS="$(getent ahostsv4 "$DOMINIO" | awk 'NR==1{print $1}' || true)"
if [ "$IP_DNS" = "$IP_PUBLICA" ]; then
  verde "  ✔ $DOMINIO → $IP_DNS"
else
  amarillo "  ! $DOMINIO apunta a «${IP_DNS:-nada}» y este VPS es $IP_PUBLICA."
  amarillo "    La plataforma arranca igual, pero el certificado HTTPS llegará cuando el DNS apunte aquí"
  amarillo "    (registro A «monitoreo» → $IP_PUBLICA en Hostinger). Luego: bash $(pwd)/actualizar.sh"
fi

# ------------------------------------------------------------------ 4. construir y levantar
paso "Construyendo la imagen (la primera vez tarda 3–6 minutos)"
docker compose build web

paso "Levantando web y worker"
docker compose up -d --remove-orphans

paso "Esperando a que la web responda (migraciones incluidas)"
for i in $(seq 1 40); do
  ESTADO="$(docker inspect -f '{{.State.Health.Status}}' riachuelo-web-1 2>/dev/null || echo desconocido)"
  [ "$ESTADO" = "healthy" ] && break
  if [ "$ESTADO" = "unhealthy" ] || [ "$(docker inspect -f '{{.State.Restarting}}' riachuelo-web-1 2>/dev/null)" = "true" ]; then
    docker compose logs --tail 40 web
    falla "La web no arrancó (mensaje arriba)."
  fi
  sleep 5
done
[ "$ESTADO" = "healthy" ] || { docker compose logs --tail 40 web; falla "La web no respondió en 200 s."; }
verde "  ✔ Web en marcha"
docker compose ps

paso "Diagnóstico de la plataforma"
docker compose exec -T web python manage.py diagnostico --sin-color || amarillo "  Hay avisos o errores arriba."

paso "Uso de recursos (la plataforma tiene tope; OpenClaw no se ve afectado)"
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'

paso "Listo"
echo "  Web:     https://$DOMINIO/"
echo "  API:     https://$DOMINIO/api/v1/health"
echo "  Primer administrador (una sola vez):"
echo "           cd $(pwd) && docker compose exec web python manage.py createsuperuser"
echo "  Logs:    cd $(pwd) && docker compose logs -f --tail 50 web worker"
