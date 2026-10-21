# 21/10/2026: reglas de confirmación automática por cantidad de cajas (aditiva).
#   · auto_confirm_min_boxes (2): cajas que deben alcanzar el umbral de confirmación automática (una sola no basta).
#   · auto_confirm_many_boxes (3) + auto_confirm_many_threshold (0,50): varias cajas medianas también confirman.
# Los modelos ya registrados toman estos valores por defecto.
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("ia", "0004_triage_tres_franjas")]

    operations = [
        migrations.AddField(
            model_name="modelconfig",
            name="auto_confirm_min_boxes",
            field=models.PositiveSmallIntegerField(
                default=2, verbose_name="mínimo de cajas para confirmar sola",
                help_text="Cajas que deben alcanzar el umbral de confirmación automática (2 = al menos dos indicios)."),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="auto_confirm_many_boxes",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, default=3, verbose_name="cajas medianas para confirmar sola",
                help_text="Ej.: 3. Con esta cantidad de cajas ≥ «umbral de cajas medianas» la IA confirma. "
                          "Vacío = apagada."),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="auto_confirm_many_threshold",
            field=models.FloatField(
                blank=True, null=True, default=0.5, verbose_name="umbral de cajas medianas",
                help_text="Ej.: 0.50. Confianza mínima de cada caja para la regla de varias cajas."),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=Q(auto_confirm_min_boxes__gte=1),
                                              name="model_configs_min_cajas_valido"),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=Q(auto_confirm_many_boxes__isnull=True)
                                              | Q(auto_confirm_many_boxes__gte=1),
                                              name="model_configs_cajas_medianas_valido"),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=Q(auto_confirm_many_threshold__isnull=True)
                                              | (Q(auto_confirm_many_threshold__gt=0)
                                                 & Q(auto_confirm_many_threshold__lte=1)),
                                              name="model_configs_umbral_medianas_valido"),
        ),
    ]
