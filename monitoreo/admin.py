"""Catalog and monitoring data admin."""
from django.contrib import admin

from monitoreo.models import CropRow, Farm, FieldPass, Lot, MonitoringSession, SessionCamera


admin.site.register(Farm)
admin.site.register(Lot)
admin.site.register(CropRow)
admin.site.register(MonitoringSession)
admin.site.register(SessionCamera)
admin.site.register(FieldPass)
