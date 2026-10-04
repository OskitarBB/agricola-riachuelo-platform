# Agricola Riachuelo Platform

Plataforma Django para la web de revision fitosanitaria descrita en `MAESTRO_WEB_v1.0`: plantillas Django, HTMX-ready, Leaflet, backend central para Supabase/PostgreSQL, Cloudinary firmado y worker separado para IA/WhatsApp.

## Inicio rapido

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

En otra terminal:

```powershell
python manage.py worker_ia
```

## Variables clave

- `DATABASE_URL`: URL de Supabase/PostgreSQL. Si no existe, Django usa `db.sqlite3` para desarrollo.
- `CLOUDINARY_URL`: solo la lee Django para firmar URLs de evidencia.
- `WHATSAPP_*`: solo las lee el worker.
- `PUBLIC_BASE_URL`: base de los enlaces enviados por WhatsApp.

## Modulos

- `cuentas`: usuarios, roles, celulares y servicios de aprobacion.
- `monitoreo`: fundos, lotes, hileras y sesiones sincronizadas por la app.
- `evidencias`: capturas y helpers de Cloudinary firmado.
- `ia`: cola `ai_tasks`, detecciones y worker.
- `revision`: casos, decisiones humanas y reglas de transicion.
- `notificaciones`: destinatarios y cola WhatsApp.
- `auditoria`: eventos y recordatorio de seguridad Supabase.
- `web`: vistas Django responsive, GeoJSON y CSV.
