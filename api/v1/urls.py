# api/v1/urls.py — Rutas del contrato /api/v1 (Maestro App Móvil §15.2). La app llama SIN barra final
# (p. ej. /api/v1/auth/login); se acepta también con barra para que nada dependa de APPEND_SLASH.
from django.urls import re_path
from drf_spectacular.views import SpectacularAPIView

from api.v1 import views

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def r(route, view, name):
    return re_path(rf"^{route}/?$", view.as_view(), name=name)


app_name = "api"
urlpatterns = [
    r("health", views.HealthView, "health"),
    r("auth/register", views.RegisterView, "register"),
    r("auth/login", views.LoginView, "login"),
    r("auth/refresh", views.RefreshView, "refresh"),
    r("auth/logout", views.LogoutView, "logout"),
    r("auth/me", views.MeView, "me"),
    r("auth/change-password", views.ChangePasswordView, "change_password"),
    r("auth/password-reset-requests", views.PasswordResetView, "password_reset"),
    r("mobile/bootstrap", views.BootstrapView, "bootstrap"),
    r("mobile/pest-reports", views.PestReportsView, "pest_reports"),  # v1.3 (ADR-W-007)
    r("mobile/deleted-captures", views.DeletedCapturesView, "deleted_captures"),  # v1.3.1 (ADR-W-008)
    r("sessions", views.SessionUpsertView, "sessions"),
    r(rf"sessions/(?P<session_id>{UUID})/passes", views.PassUpsertView, "passes"),
    r(rf"sessions/(?P<session_id>{UUID})/sequences/batch", views.SequenceBatchView, "sequences_batch"),
    r(rf"sessions/(?P<session_id>{UUID})/incidents/batch", views.IncidentBatchView, "incidents_batch"),
    r(rf"captures/(?P<capture_id>{UUID})/upload-ticket", views.UploadTicketView, "upload_ticket"),
    r("captures/upload", views.CaptureConfirmView, "capture_upload"),
    r(rf"captures/(?P<capture_id>{UUID})", views.CaptureDetailView, "capture_detail"),
    re_path(r"^schema/?$", SpectacularAPIView.as_view(authentication_classes=[], permission_classes=[]),
            name="schema"),
]
