# v1.4 (ADR-W-010): largo aproximado de la hilera en metros. Migración aditiva (columna NULL, sin tocar datos).
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("campo", "0004_puntos_del_fundo")]

    operations = [
        migrations.AddField(
            model_name="fieldrow",
            name="length_m",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
