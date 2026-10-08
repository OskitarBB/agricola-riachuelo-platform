# campo/admin.py — Catálogos en Django Admin (/gestion/, solo superusuarios). v1.2 (ADR-W-006, W-03): el día a día se
# hace en la web (Administración → Catálogos, campo/services.py). Aquí no se borra nada («eliminar» = desactivar) y el
# ID no se edita: pasadas, secuencias y casos apuntan a él, y hay celulares sin internet con el catálogo descargado.
from django.contrib import admin

from campo.models import FieldLot, FieldRow, FieldSegment, Marker, QualityProfile


class CatalogoAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("id",) if obj else ()


@admin.register(FieldLot)
class FieldLotAdmin(CatalogoAdmin):
    list_display = ("code", "name", "active")
    list_filter = ("active",)


@admin.register(FieldRow)
class FieldRowAdmin(CatalogoAdmin):
    list_display = ("id", "lot", "number", "plant_count", "active")
    list_filter = ("active", "lot")

    def get_readonly_fields(self, request, obj=None):
        return ("id", "lot", "number") if obj else ()  # el número y el lote forman el ID


@admin.register(FieldSegment)
class FieldSegmentAdmin(CatalogoAdmin):
    list_display = ("code", "row", "start_plant", "end_plant", "is_pilot", "active")
    list_filter = ("active", "is_pilot", "row__lot")


@admin.register(Marker)
class MarkerAdmin(CatalogoAdmin):
    list_display = ("code", "row", "segment", "position", "lat", "lon", "active")
    list_filter = ("active", "row__lot")


admin.site.register(QualityProfile)
