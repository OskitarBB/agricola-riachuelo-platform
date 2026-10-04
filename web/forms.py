"""Forms for the review web."""
from django import forms

from revision.models import ReviewStatus


class CaseDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, "Confirmar"),
            (ReviewStatus.DESCARTADO, "Descartar"),
            (ReviewStatus.EVIDENCIA_INSUFICIENTE, "Evidencia insuficiente"),
        ],
        widget=forms.RadioSelect,
    )
    observation = forms.CharField(
        label="Observacion",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Notas de la revision"}),
    )
