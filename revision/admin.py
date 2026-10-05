from django.contrib import admin

from auditoria.admin import ReadOnlyAdmin
from revision.models import Case, HumanReview

admin.site.register(Case, ReadOnlyAdmin)
admin.site.register(HumanReview, ReadOnlyAdmin)
