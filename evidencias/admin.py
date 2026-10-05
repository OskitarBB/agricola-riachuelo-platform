from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from evidencias.models import Capture

admin.site.register(Capture, ReadOnlyAdmin)
