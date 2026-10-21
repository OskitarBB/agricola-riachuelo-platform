# campo/management/commands/crear_lotes_estandar.py — v1.4 (ADR-W-010): carga los lotes estándar del fundo.
#
#   python manage.py crear_lotes_estandar --simular     # muestra lo que haría, sin escribir
#   python manage.py crear_lotes_estandar               # 10 lotes «LOTE 01»…«LOTE 10» × 20 hileras de ≈200 m
#   docker compose exec web python manage.py crear_lotes_estandar --usuario admin@agricolariachuelo.org   (VPS)
#
# Cada hilera nace con el reparto estándar: settings.SEGMENTOS_POR_HILERA segmentos iguales (10 → ≈20 m c/u), un
# marcador al inicio de cada segmento y uno al final. Las plantas salen del largo y de DISTANCIA_ENTRE_PLANTAS_M
# (200 m / 1,5 m = 133). Usa las mismas reglas que la web (campo/services.py): IDs del servidor, auditoría con el
# usuario indicado y nada se borra. Es idempotente: un lote que ya existe (por código) no se duplica y solo se le
# agregan las hileras que falten. No toca ningún otro lote (SWG 1, SWG 2, SWG 5…). Se permite en el piloto porque
# son catálogos, no evidencia de campo (W-22 solo prohíbe mezclar datos de demostración con evidencia real).
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from campo import services as cat
from campo.models import FieldLot
from cuentas.models import Role, User


class Command(BaseCommand):
    help = "Crea los lotes estándar (por defecto 10 × 20 hileras de 200 m) con sus segmentos y marcadores."

    def add_arguments(self, parser):
        parser.add_argument("--lotes", type=int, default=10, help="Cuántos lotes (por defecto 10)")
        parser.add_argument("--desde", type=int, default=1, help="Número del primer lote (por defecto 1 → LOTE 01)")
        parser.add_argument("--hileras", type=int, default=20, help="Hileras por lote (por defecto 20)")
        parser.add_argument("--largo", type=int, default=200, help="Largo aproximado de cada hilera en metros")
        parser.add_argument("--prefijo", default="LOTE", help="Código del lote: «<prefijo> 01» (por defecto LOTE)")
        parser.add_argument("--usuario", help="Correo del administrador o supervisor que firma la auditoría")
        parser.add_argument("--simular", action="store_true", help="Solo muestra lo que haría")

    def _usuario(self, email):
        if email:
            user = User.objects.filter(email__iexact=email.strip()).first()
            if user is None:
                raise CommandError(f"No existe la cuenta {email}.")
        else:
            user = next((u for u in User.objects.order_by("pk")
                         if u.is_active and u.has_role(Role.ADMINISTRADOR)), None)
            if user is None:
                raise CommandError("No hay un administrador activo. Crea uno o indica --usuario.")
        if not (user.is_active and user.has_role(*cat.ROLES_CATALOGOS)):
            raise CommandError(f"{user.email} no es administrador ni supervisor activo.")
        return user

    def handle(self, *args, **o):
        lotes, desde, hileras, largo = o["lotes"], o["desde"], o["hileras"], o["largo"]
        if not 1 <= lotes <= 50:
            raise CommandError("--lotes va de 1 a 50.")
        if not 1 <= desde <= 99:
            raise CommandError("--desde va de 1 a 99.")
        if not 1 <= hileras <= cat.MAX_HILERAS_POR_ALTA:
            raise CommandError(f"--hileras va de 1 a {cat.MAX_HILERAS_POR_ALTA}.")
        if not 1 <= largo <= cat.MAX_LARGO_HILERA_M:
            raise CommandError(f"--largo va de 1 a {cat.MAX_LARGO_HILERA_M} m.")
        prefijo = " ".join(o["prefijo"].split()).upper() or "LOTE"
        plantas = cat.plantas_por_largo(largo)
        n_seg = min(cat.segmentos_por_hilera(), plantas)
        codigos = [f"{prefijo} {k:02d}" for k in range(desde, desde + lotes)]
        self.stdout.write(f"Plan: {lotes} lote(s) ({codigos[0]} a {codigos[-1]}) × {hileras} hileras de ≈{largo} m "
                          f"= {plantas} plantas por hilera, {n_seg} segmentos de ≈{largo / n_seg:.0f} m y "
                          f"{n_seg + 1} marcadores por hilera.")
        if o["simular"]:
            for code in codigos:
                lot = FieldLot.objects.filter(code__iexact=code).first()
                estado = "nuevo" if lot is None else (f"ya existe ({lot.pk}, {lot.rows.count()} hileras)"
                                                      + ("" if lot.active else ", INACTIVO: se salta"))
                self.stdout.write(f"  · {code}: {estado}")
            self.stdout.write("Simulación: no se escribió nada.")
            return
        user = self._usuario(o["usuario"])
        resumen = {"lotes_nuevos": 0, "hileras_nuevas": 0, "saltados": []}
        with transaction.atomic():
            for k, code in zip(range(desde, desde + lotes), codigos):
                lot = FieldLot.objects.filter(code__iexact=code).first()
                if lot is None:
                    lot = cat.crear_lote(user, code, f"Lote {k:02d} · {hileras} hileras de {largo} m")
                    resumen["lotes_nuevos"] += 1
                elif not lot.active:
                    resumen["saltados"].append(code)
                    self.stdout.write(self.style.WARNING(f"  ! {code} está desactivado: no se toca."))
                    continue
                creadas, saltadas = cat.crear_hileras(user, lot.pk, 1, hileras, plantas, largo_m=largo,
                                                      division="estandar")
                resumen["hileras_nuevas"] += len(creadas)
                self.stdout.write(f"  ✔ {code} ({lot.pk}): {len(creadas)} hilera(s) nuevas"
                                  + (f", {len(saltadas)} ya existían" if saltadas else ""))
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {resumen['lotes_nuevos']} lote(s) y {resumen['hileras_nuevas']} hilera(s) nuevas. "
            "En la app: Catálogos → Actualizar."))
