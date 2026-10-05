from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from monitoreo.models import CaptureSequence, Incident, MonitoringPass, MonitoringSession

for model in (MonitoringSession, MonitoringPass, CaptureSequence, Incident):
    admin.site.register(model, ReadOnlyAdmin)
