from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from notificaciones.models import Notification

admin.site.register(Notification, ReadOnlyAdmin)
