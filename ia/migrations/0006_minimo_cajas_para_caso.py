# 21/10/2026: «mínimo de cajas para abrir caso» (aditiva). Con menos cajas (≥ umbral de revisión) la IA descarta la
# foto: una sola caja (p. ej. un reflejo blanco en la uva) ya no abre caso. Los modelos ya registrados quedan con 2.
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("ia", "0005_minimo_cajas_confirmacion")]

    operations = [
        migrations.AddField(
            model_name="modelconfig",
            name="review_min_boxes",
            field=models.PositiveSmallIntegerField(
                default=2, verbose_name="mínimo de cajas para abrir caso",
                help_text="Con menos cajas (≥ umbral de revisión) la IA descarta la foto. 1 = una sola caja abre caso."),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=Q(review_min_boxes__gte=1),
                                              name="model_configs_min_cajas_caso_valido"),
        ),
    ]
