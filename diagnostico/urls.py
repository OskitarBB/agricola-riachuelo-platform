from django.urls import path

from diagnostico import views

app_name = "diagnostico"
urlpatterns = [
    path("error-cliente/", views.error_cliente, name="error_cliente"),
]
