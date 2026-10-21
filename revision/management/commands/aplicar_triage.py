# revision/management/commands/aplicar_triage.py — v1.3.1 (ADR-W-008): fija los umbrales del modelo activo y los
# aplica a los casos «Pendiente de revisión» que abrió la IA.
#
#   python manage.py aplicar_triage --revision 0.50 --auto 0.85 --simular   (solo cuenta, no cambia nada)
#   python manage.py aplicar_triage --revision 0.50 --auto 0.85             (guarda y aplica)
#   python manage.py aplicar_triage --auto apagado                           (sin confirmación automática)
#   python manage.py aplicar_triage --min-cajas-caso 2                       (21/10: con 1 sola caja la IA descarta)
#   python manage.py aplicar_triage --min-cajas 2                            (21/10: cajas mínimas para confirmar sola)
#   python manage.py aplicar_triage --varias 3 --umbral-varias 0.50          (21/10: 3 cajas ≥ 0,50 también confirman)
#   python manage.py aplicar_triage --varias apagado                         (sin la regla de varias cajas)
#   python manage.py aplicar_triage --revisar-confirmados                    (21/10: también revisa los «Confirmado
#                                                                            por IA» sin decisión humana; los que ya no
#                                                                            cumplen vuelven a «Pendiente de revisión»)
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
        parser.add_argument("--min-cajas-caso", type=int,
                            help="Cajas (≥ umbral de revisión) para abrir caso; con menos la IA descarta (1 o más).")
        parser.add_argument("--min-cajas", type=int,
                            help="Cajas que deben alcanzar el umbral --auto para confirmar sola (1 o más).")
        parser.add_argument("--varias", help="Cajas medianas que también confirman (p. ej. 3) o «apagado».")
        parser.add_argument("--umbral-varias", help="Confianza mínima de esas cajas medianas (p. ej. 0.50).")
        parser.add_argument("--revisar-confirmados", action="store_true",
                            help="Los «Confirmado por IA» sin decisión humana que ya no cumplen las reglas vuelven a "
                                 "«Pendiente de revisión» (avisos sin enviar se anulan).")
        parser.add_argument("--simular", action="store_true", help="Solo muestra lo que pasaría; no cambia nada.")

    def handle(self, *args, **o):
        model = ModelConfig.objects.filter(active=True).first()
        if model is None:
            raise CommandError("No hay un modelo activo (/gestion/ → Modelos de IA).")
        rev, auto = _umbral(o["revision"], "revision"), _umbral(o["auto"], "auto")
        nuevo_rev = model.review_threshold if rev is ... else rev
        nuevo_auto = model.auto_confirm_threshold if auto is ... else auto
        if o["min_cajas"] is not None and o["min_cajas"] < 1:
            raise CommandError("--min-cajas debe ser 1 o más.")
        nuevo_min = model.auto_confirm_min_boxes if o["min_cajas"] is None else o["min_cajas"]
        if o["min_cajas_caso"] is not None and o["min_cajas_caso"] < 1:
            raise CommandError("--min-cajas-caso debe ser 1 o más.")
        nuevo_min_caso = model.review_min_boxes if o["min_cajas_caso"] is None else o["min_cajas_caso"]
        if o["varias"] is None:
            nuevo_varias = model.auto_confirm_many_boxes
        elif str(o["varias"]).strip().lower() in ("apagado", "off", "no", "ninguno"):
            nuevo_varias = None
        else:
            try:
                nuevo_varias = int(o["varias"])
            except ValueError:
                raise CommandError("--varias: escribe un número de cajas (p. ej. 3) o «apagado».")
            if nuevo_varias < 1:
                raise CommandError("--varias debe ser 1 o más.")
        uv = _umbral(o["umbral_varias"], "umbral-varias")
        nuevo_uv = model.auto_confirm_many_threshold if uv is ... else uv
        if nuevo_varias and nuevo_uv is None:
            raise CommandError("Para la regla de varias cajas indica también --umbral-varias (p. ej. 0.50).")
        if nuevo_varias and nuevo_rev is not None and nuevo_uv < nuevo_rev:
            raise CommandError("--umbral-varias no puede ser menor que el umbral de revisión.")
        if nuevo_rev is not None and nuevo_auto is not None and nuevo_rev > nuevo_auto:
            raise CommandError("El umbral de revisión no puede ser mayor que el de confirmación automática.")
        campos = ["review_threshold", "review_min_boxes", "auto_confirm_threshold", "auto_confirm_min_boxes",
                  "auto_confirm_many_boxes", "auto_confirm_many_threshold"]
        antes = {c: getattr(model, c) for c in campos}
        despues = dict(zip(campos, [nuevo_rev, nuevo_min_caso, nuevo_auto, nuevo_min, nuevo_varias, nuevo_uv]))
        self.stdout.write(f"Modelo activo: {model}")
        self.stdout.write(f"  umbral de revisión: {antes['review_threshold']} → {nuevo_rev}")
        self.stdout.write(f"  mínimo de cajas para abrir caso: {antes['review_min_boxes']} → {nuevo_min_caso}")
        self.stdout.write(f"  confirmación automática: {antes['auto_confirm_threshold']} → {nuevo_auto}")
        self.stdout.write(f"  mínimo de cajas para confirmar sola: {antes['auto_confirm_min_boxes']} → {nuevo_min}")
        self.stdout.write(f"  varias cajas medianas: {antes['auto_confirm_many_boxes']} con ≥ "
                          f"{antes['auto_confirm_many_threshold']} → {nuevo_varias} con ≥ {nuevo_uv}")
        if not o["simular"] and despues != antes:
            with transaction.atomic():
                for c, v in despues.items():
                    setattr(model, c, v)
                model.save(update_fields=campos)
                audit.record("model_config", model.pk, "MODELO_UMBRALES", None, antes, despues)
        else:
            for c, v in despues.items():
                setattr(model, c, v)
        r = reapply_triage(model, simulate=o["simular"], revisar_confirmados=o["revisar_confirmados"])
        pref = "Se haría" if o["simular"] else "Hecho"
        if r["unidos"]:
            self.stdout.write(f"{pref}: {r['unidos']} caso(s) duplicado(s) de un mismo lugar (2 cámaras) unidos en uno.")
        if o["revisar_confirmados"]:
            self.stdout.write(f"{pref}: {r['devueltos']} caso(s) «Confirmado por IA» vuelven a «Pendiente de revisión» "
                              "(ya no cumplen las reglas).")
        self.stdout.write(self.style.SUCCESS(
            f"{pref}: {r['descartados']} descartados por la IA · {r['confirmados']} confirmados por la IA · "
            f"{r['revision']} quedan para el especialista."))
        if o["simular"]:
            self.stdout.write("Nada cambió (--simular). Ejecuta sin --simular para aplicarlo.")
