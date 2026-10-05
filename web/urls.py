# web/urls.py — Rutas de la web (sección 6.3). Prefijo raíz; la API vive en /api/v1/ y Django Admin en /gestion/.
from django.urls import path

from web import views

app_name = "web"
urlpatterns = [
    path("ingresar/", views.ingresar, name="login"),
    path("salir/", views.salir, name="logout"),
    path("cuenta/contrasena/", views.cambiar_contrasena, name="cambiar_contrasena"),
    path("", views.dashboard, name="dashboard"),
    path("actividad/", views.actividad, name="actividad"),  # v1.0+: avisos en vivo (sondeo P-2)
    path("casos/", views.bandeja, name="bandeja"),
    path("casos/<uuid:pk>/", views.caso, name="caso"),
    path("casos/<uuid:pk>/decidir/", views.caso_decidir, name="caso_decidir"),
    path("casos/<uuid:pk>/corregir/", views.caso_corregir, name="caso_corregir"),
    path("capturas/<uuid:pk>/", views.captura, name="captura"),
    path("capturas/<uuid:pk>/abrir-caso/", views.captura_abrir_caso, name="captura_abrir_caso"),
    path("mapa/", views.mapa, name="mapa"),
    path("mapa/datos/", views.mapa_datos, name="mapa_datos"),
    path("plano/", views.plano, name="plano"),
    path("sesiones/", views.sesiones, name="sesiones"),
    path("sesiones/<uuid:pk>/", views.sesion, name="sesion"),
    path("reportes/", views.reportes, name="reportes"),
    path("reportes/casos.csv", views.exportar_casos, name="exportar_casos"),
    path("notificaciones/", views.notificaciones, name="notificaciones"),
    path("administracion/destinatarios/", views.destinatarios, name="destinatarios"),
    path("administracion/destinatarios/<int:pk>/", views.destinatarios, name="destinatario_editar"),
    path("administracion/usuarios/", views.usuarios, name="usuarios"),
    path("administracion/usuarios/<uuid:pk>/<slug:accion>/", views.usuario_accion, name="usuario_accion"),
    path("administracion/dispositivos/", views.dispositivos, name="dispositivos"),
    path("administracion/dispositivos/<uuid:pk>/revocar/", views.dispositivo_revocar, name="dispositivo_revocar"),
    path("ia/", views.ia_estado, name="ia"),
    path("ia/tareas/<uuid:pk>/reencolar/", views.ia_reencolar, name="ia_reencolar"),
    path("auditoria/", views.auditoria, name="auditoria"),
]
