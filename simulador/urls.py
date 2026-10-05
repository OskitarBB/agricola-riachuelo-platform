# simulador/urls.py — SOLO desarrollo (APP_ENV=dev). config/urls.py no incluye estas rutas en piloto y las vistas
# responden 404 si Cloudinary real está configurado.
from django.urls import path

from simulador import views

app_name = "simulador"
urlpatterns = [
    # Emula la Upload API de Cloudinary para que la app suba fotos a la laptop con el mismo ticket firmado.
    path("cloudinary/v1_1/<str:cloud>/image/upload", views.subir, name="subir"),
    # Entrega de fotos a la web (equivale a las URLs firmadas de Cloudinary); exige sesión de la web.
    path("media/<str:variant>/<path:public_id>", views.foto, name="foto"),
]
