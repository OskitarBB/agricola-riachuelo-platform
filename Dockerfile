# Dockerfile — Imagen única de la plataforma (web + API con gunicorn, y worker_ia). La usan deploy/docker-compose.yml
# en el VPS. Sin secretos: el .env.piloto se inyecta al arrancar, nunca se copia a la imagen (.dockerignore).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN groupadd --system --gid 10001 riachuelo \
    && useradd --system --uid 10001 --gid riachuelo --home-dir /app --shell /usr/sbin/nologin riachuelo

# Dependencias primero (se reutilizan en cada actualización si requirements no cambia).
COPY requirements.txt requirements-ia.txt ./
# INSTALAR_IA=1: onnxruntime + numpy ya instalados; cuando llegue el modelo YOLO solo se copia el .onnx.
ARG INSTALAR_IA=1
RUN pip install -r requirements.txt \
    && if [ "$INSTALAR_IA" = "1" ]; then pip install -r requirements-ia.txt; fi

COPY . .
# Estáticos con hash y comprimidos (WhiteNoise). Clave y entorno ficticios: collectstatic no usa la base ni secretos.
RUN APP_ENV=dev DJANGO_DEBUG=false DATABASE_URL= CLOUDINARY_URL= \
    DJANGO_SECRET_KEY=solo-para-collectstatic-no-se-usa-en-ejecucion-0000000000000000 \
    python manage.py collectstatic --noinput -v 0 \
    && mkdir -p /app/modelos

USER riachuelo
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
