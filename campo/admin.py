from django.contrib import admin

from campo.models import FieldLot, FieldRow, FieldSegment, Marker, QualityProfile


@admin.register(FieldLot)
class FieldLotAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active")


@admin.register(FieldRow)
class FieldRowAdmin(admin.ModelAdmin):
    list_display = ("id", "lot", "number", "plant_count", "active")
    list_filter = ("lot",)


@admin.register(FieldSegment)
class FieldSegmentAdmin(admin.ModelAdmin):
    list_display = ("code", "row", "start_plant", "end_plant", "is_pilot")
    list_filter = ("is_pilot", "row__lot")


@admin.register(Marker)
class MarkerAdmin(admin.ModelAdmin):
    list_display = ("code", "row", "segment", "position", "lat", "lon")
    list_filter = ("row__lot",)


admin.site.register(QualityProfile)
