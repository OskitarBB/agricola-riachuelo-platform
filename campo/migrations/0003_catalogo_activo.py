# campo/migrations/0003_catalogo_activo.py — v1.2 (ADR-W-006): segmentos y marcadores se desactivan en vez de borrarse.
# Solo agrega dos columnas con valor por defecto true (las filas existentes quedan activas). Sin tablas nuevas.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campo", "0002_restricciones_check"),
    ]

    operations = [
        migrations.AddField(
            model_name="fieldsegment",
            name="active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="marker",
            name="active",
            field=models.BooleanField(default=True),
        ),
    ]
