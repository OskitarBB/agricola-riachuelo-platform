# Despliegue en el VPS (Hostinger KVM 1, Ubuntu 24.04) — monitoreo.agricolariachuelo.org

La plataforma corre en Docker **junto** a OpenClaw, usando el Traefik que ya ocupa los puertos 80/443 (no se
instala otro proxy ni se toca su configuración). Base de datos: Supabase. Fotos: Cloudinary.

| Contenedor | Qué hace | Tope |
|---|---|---|
| `riachuelo-web-1` | gunicorn: web + API `/api/v1` (migraciones al arrancar) | 700 MB · 0,8 CPU |
| `riachuelo-worker-1` | `worker_ia`: análisis de fotos y avisos | 1,2 GB · 0,7 CPU |

Aislamiento: usuario sin privilegios (uid 10001), sistema de archivos de solo lectura, sin capacidades de Linux,
`no-new-privileges`, red interna propia, logs de 10 MB × 3. Secretos solo en `deploy/.env.piloto` (permiso 600).

## Instalar (una vez)

```bash
mkdir -p /srv/riachuelo && tar -xzf /root/riachuelo-plataforma.tar.gz -C /srv/riachuelo
bash /srv/riachuelo/deploy/instalar.sh          # crea .env.piloto y se detiene
nano /srv/riachuelo/deploy/.env.piloto          # DATABASE_URL y CLOUDINARY_URL
bash /srv/riachuelo/deploy/instalar.sh          # construye, levanta y diagnostica
cd /srv/riachuelo/deploy && docker compose exec web python manage.py createsuperuser
```

## Día a día

```bash
cd /srv/riachuelo/deploy
docker compose ps                                   # estado
docker compose logs -f --tail 50 web worker         # consola (Ctrl+C para salir)
docker compose exec web python manage.py diagnostico
docker compose restart worker
bash actualizar.sh                                  # tras cambiar código o .env.piloto
```

Actualizar el código: subir un nuevo `riachuelo-plataforma.tar.gz` y
`tar -xzf /root/riachuelo-plataforma.tar.gz -C /srv/riachuelo && bash /srv/riachuelo/deploy/actualizar.sh`
(el `.env.piloto` y `modelos/` no vienen en el paquete, así que no se pisan).

## Cuando llegue el modelo YOLO

1. Copiar `modelo.onnx` a `/srv/riachuelo/deploy/modelos/` (`scp modelo.onnx root@IP:/srv/riachuelo/deploy/modelos/`).
2. En `/gestion/` → Modelos de IA: crear la configuración activa (clases, imgsz, umbrales).
3. `bash actualizar.sh`. Las fotos que esperaban en cola se analizan solas.

## Retirar al terminar el proyecto

`bash /srv/riachuelo/deploy/desinstalar.sh` → borra contenedores, imágenes y `/srv/riachuelo`. OpenClaw y Traefik
quedan intactos. Quitar después el registro DNS `monitoreo` en Hostinger.
