"""Routes for the Django-rendered review web."""
from django.contrib.auth import views as auth_views
from django.urls import path

from web import views


app_name = "web"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("casos/", views.casos, name="casos"),
    path("casos/<uuid:case_id>/", views.casos, name="caso"),
    path("capturas/<uuid:capture_id>/", views.captura, name="captura"),
    path("mapa/", views.mapa, name="mapa"),
    path("mapa/datos/", views.mapa_datos, name="mapa_datos"),
    path("sesiones/", views.sesiones, name="sesiones"),
    path("tratamientos/", views.tratamientos, name="tratamientos"),
    path("reportes/", views.reportes, name="reportes"),
    path("reportes/casos.csv", views.exportar_casos, name="exportar_casos"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
