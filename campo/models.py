# campo/models.py — Catálogos del fundo (tablas field_lots, field_rows, field_segments, markers, quality_profiles).
from django.db import models
from django.db.models import F, Q
from config.restricciones import checks_de_opciones


class FieldLot(models.Model):
    id = models.CharField(primary_key=True, max_length=20)  # p. ej. "SWG1" (Anexo D del maestro móvil)
    code = models.CharField(max_length=20, unique=True)  # "SWG 1"
    name = models.CharField(max_length=80)  # "Lote 1 (Piscina)"
    active = models.BooleanField(default=True)
    # (web v1.0) Contorno del lote en GeoJSON (Polygon o MultiPolygon, WGS84) para el mapa. Opcional.
    geometry = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "field_lots"
        ordering = ["code"]
        verbose_name = "lote"

    def __str__(self):
        return self.code


class FieldRow(models.Model):
    id = models.CharField(primary_key=True, max_length=30)  # "SWG1-H01"
    lot = models.ForeignKey(FieldLot, on_delete=models.PROTECT, related_name="rows")
    number = models.PositiveIntegerField()
    plant_count = models.PositiveIntegerField()
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "field_rows"
        ordering = ["lot_id", "number"]
        constraints = [models.UniqueConstraint(fields=["lot", "number"], name="field_rows_lote_numero")]
        verbose_name = "hilera"

    def __str__(self):
        return f"{self.lot_id} H{self.number:02d}"


class FieldSegment(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    row = models.ForeignKey(FieldRow, on_delete=models.PROTECT, related_name="segments")
    code = models.CharField(max_length=40)
    start_plant = models.PositiveIntegerField()
    end_plant = models.PositiveIntegerField()
    is_pilot = models.BooleanField(default=False)
    # v1.2 (ADR-W-006): «eliminar» = desactivar. Lo inactivo no baja a la app ni se dibuja en el plano, pero la
    # historia (pasadas, secuencias, casos) y la sincronización de celulares sin internet siguen funcionando.
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "field_segments"
        ordering = ["row_id", "start_plant"]
        constraints = [models.CheckConstraint(condition=Q(start_plant__lte=F("end_plant")), name="segmento_rango")]
        verbose_name = "segmento"

    def __str__(self):
        return self.code


class MarkerPosition(models.TextChoices):
    INICIO = "INICIO", "Inicio"
    FIN = "FIN", "Fin"
    INTERMEDIO = "INTERMEDIO", "Intermedio"


@checks_de_opciones
class Marker(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    row = models.ForeignKey(FieldRow, on_delete=models.PROTECT, related_name="markers")
    segment = models.ForeignKey(FieldSegment, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="markers")
    code = models.CharField(max_length=40)
    description = models.CharField(max_length=200, blank=True)
    position = models.CharField(max_length=12, choices=MarkerPosition.choices)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    active = models.BooleanField(default=True)  # v1.2 (ADR-W-006): ver FieldSegment.active

    class Meta:
        db_table = "markers"
        ordering = ["row_id", "code"]
        verbose_name = "marcador"
        verbose_name_plural = "marcadores"

    def __str__(self):
        return self.code


class PointKind(models.TextChoices):
    ENTRADA = "ENTRADA", "Entrada / portón"
    ALMACEN = "ALMACEN", "Almacén"
    POZO = "POZO", "Pozo / reservorio"
    REUNION = "REUNION", "Punto de reunión"
    OFICINA = "OFICINA", "Oficina / caseta"
    OTRO = "OTRO", "Otro"


@checks_de_opciones
class PointOfInterest(models.Model):
    """v1.3 (ADR-W-007): punto con nombre del fundo (entrada, almacén, pozo…) puesto en el mapa satelital por el
    administrador o el supervisor. Se ve en la web y en «Ubicar plaga» de la app. «Eliminar» = desactivar."""

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=PointKind.choices, default=PointKind.OTRO)
    description = models.CharField(max_length=200, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey("cuentas.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "points_of_interest"
        ordering = ["name"]
        verbose_name = "punto del fundo"
        verbose_name_plural = "puntos del fundo"

    def __str__(self):
        return self.name


class QualityProfile(models.Model):
    version = models.CharField(max_length=20, unique=True)  # Q0, Q1…
    params = models.JSONField()
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "quality_profiles"
        verbose_name = "perfil de calidad"
        verbose_name_plural = "perfiles de calidad"

    def __str__(self):
        return self.version
