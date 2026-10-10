# revision/management/commands/aplicar_triage.py — v1.3.1 (ADR-W-008): fija los umbrales del modelo activo y los
# aplica a los casos «Pendiente de revisión» que abrió la IA.
#
#   python manage.py aplicar_triage --revision 0.50 --auto 0.85 --simular   (solo cuenta, no cambia nada)
#   python manage.py aplicar_triage --revision 0.50 --auto 0.85             (guarda y aplica)
#   python manage.py aplicar_triage --auto apagado                           (sin confirmación automática)
#
# Por debajo de --revision la IA descarta la foto (deja de ser caso); desde --auto la confirma y se avisa por WhatsApp;
# en medio queda para el especialista. Las decisiones ya tomadas nunca cambian.
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from auditoria import services as audit
from ia.models import ModelConfig
from revision.services import reapply_triage


def _umbral(valor, nombre):
    if valor is None:
        return ...  # sin cambio
    if str(valor).strip().lower() in ("apagado", "off", "no", "ninguno"):
        return None
    try:
        v = float(str(valor).replace(",", "."))
    except ValueError:
        raise CommandError(f"--{nombre}: escribe un número entre 0 y 1 (por ejemplo 0.50) o «apagado».")
    if not 0 < v <= 1:
        raise CommandError(f"--{nombre}: debe estar entre 0 y 1.")
    return v


class Command(BaseCommand):
    help = "Fija los umbrales de triage del modelo activo y los aplica a los casos pendientes abiertos por la IA."

    def add_arguments(self, parser):
        parser.add_argument("--revision", help="Umbral de revisión (p. ej. 0.50) o «apagado».")
        parser.add_argument("--auto", help="Umbral de confirmación automática (p. ej. 0.85) o «apagado».")
        parser.add_argument("--simular", action="store_true", help="Solo muestra lo que pasaría; no cambia nada.")

    def handle(self, *args, **o):
        model = ModelConfig.objects.filter(active=True).first()
        if model is None:
            raise CommandError("No hay un modelo activo (/gestion/ → Modelos de IA).")
        rev, auto = _umbral(o["revision"], "revision"), _umbral(o["auto"], "auto")
        nuevo_rev = model.review_threshold if rev is ... else rev
        nuevo_auto = model.auto_confirm_threshold if auto is ... else auto
        if nuevo_rev is not None and nuevo_auto is not None and nuevo_rev > nuevo_auto:
            raise CommandError("El umbral de revisión no puede ser mayor que el de confirmación automática.")
        antes = {"review_threshold": model.review_threshold, "auto_confirm_threshold": model.auto_confirm_threshold}
        despues = {"review_threshold": nuevo_rev, "auto_confirm_threshold": nuevo_auto}
        self.stdout.write(f"Modelo activo: {model}")
        self.stdout.write(f"  umbral de revisión: {antes['review_threshold']} → {nuevo_rev}")
        self.stdout.write(f"  confirmación automática: {antes['auto_confirm_threshold']} → {nuevo_auto}")
        if not o["simular"] and despues != antes:
            with transaction.atomic():
                model.review_threshold, model.auto_confirm_threshold = nuevo_rev, nuevo_auto
                model.save(update_fields=["review_threshold", "auto_confirm_threshold"])
                audit.record("model_config", model.pk, "MODELO_UMBRALES", None, antes, despues)
        else:
            model.review_threshold, model.auto_confirm_threshold = nuevo_rev, nuevo_auto
        r = reapply_triage(model, simulate=o["simular"])
        pref = "Se haría" if o["simular"] else "Hecho"
        if r["unidos"]:
            self.stdout.write(f"{pref}: {r['unidos']} caso(s) duplicado(s) de un mismo lugar (2 cámaras) unidos en uno.")
        self.stdout.write(self.style.SUCCESS(
            f"{pref}: {r['descartados']} descartados por la IA · {r['confirmados']} confirmados por la IA · "
            f"{r['revision']} quedan para el especialista."))
        if o["simular"]:
            self.stdout.write("Nada cambió (--simular). Ejecuta sin --simular para aplicarlo.")
