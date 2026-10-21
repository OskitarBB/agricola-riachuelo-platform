# campo/services.py — v1.2 (ADR-W-006): reglas de los catálogos del fundo (lotes, hileras, segmentos y marcadores).
#
# Reglas que no se negocian (traspaso HANDOFF_CATALOGOS_WEB, §3):
#   · «Eliminar» = desactivar. Nunca se borran filas: hay celulares sin internet con el catálogo descargado y las
#     pasadas, secuencias y casos ya registrados apuntan a estos IDs.
#   · Los IDs se generan aquí, no cambian nunca y no se reutilizan (se comprueba incluso contra los inactivos).
#   · El número y el lote de una hilera no se editan (forman su ID).
#   · Toda escritura es atómica y queda en la auditoría (W-02, W-06, W-15).
# La sincronización de la app (monitoreo/services.py) no mira «active»: sigue aceptando IDs desactivados.
#
# v1.4 (ADR-W-010) — SEGMENTOS FIJOS POR HILERA: cada hilera tiene settings.SEGMENTOS_POR_HILERA segmentos (10 por
# defecto, ~20 m cada uno en una hilera de 200 m) y los dos laterales comparten los mismos. Es el máximo de segmentos
# activos (crear, reactivar y dividir lo respetan) y el reparto estándar: partes iguales que cubren todas las plantas,
# un marcador al inicio de cada segmento y uno al final de la hilera. Las hileras antiguas («Hxx completa») siguen
# funcionando; la web las marca como «fuera del estándar» y las puede pasar al reparto estándar por lote.
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from auditoria import services as audit
from campo.models import FieldLot, FieldRow, FieldSegment, Marker, MarkerPosition
from cuentas.models import Role

ROLES_CATALOGOS = (Role.ADMINISTRADOR, Role.SUPERVISOR)  # mismo conjunto que «catalogos.gestionar» (web/permissions)
MAX_HILERAS_POR_ALTA = 300
MAX_LARGO_HILERA_M = 2000
DIVISIONES = ("estandar", "completa", "ninguna")  # al crear hileras: N segmentos, uno de hilera completa o ninguno

ENTIDADES = {"lote": (FieldLot, "field_lot"), "hilera": (FieldRow, "field_row"),
             "segmento": (FieldSegment, "field_segment"), "marcador": (Marker, "marker")}


# ------------------------------------------------------------------ utilidades
def _require(user):
    if not (user and user.is_authenticated and user.is_active and user.has_role(*ROLES_CATALOGOS)):
        raise PermissionDenied("Solo el administrador o el supervisor gestionan los catálogos")


def _limpio(texto):
    return " ".join((texto or "").split())


def _foto(obj, campos):
    return {c: getattr(obj, c) for c in campos}


def _cambios(antes, despues):
    a = {k: v for k, v in antes.items() if despues.get(k) != v}
    d = {k: despues[k] for k in a}
    return a, d


def _bloquear(model, pk):
    try:
        return model.objects.select_for_update().get(pk=pk)
    except model.DoesNotExist as exc:
        raise ValidationError("El elemento ya no existe. Recarga la página.") from exc


def _id_libre(model, base, sufijo_fmt, inicio=1, max_len=40):
    """Primer ID libre con el formato base+sufijo (incluye los inactivos: los IDs no se reutilizan)."""
    k = inicio
    while True:
        candidato = f"{base}{sufijo_fmt.format(k)}"
        if len(candidato) > max_len:
            raise ValidationError("No se pudo generar un identificador: el código es demasiado largo.")
        if not model.objects.filter(pk=candidato).exists():
            return candidato
        k += 1


def segmentos_por_hilera():
    """v1.4 (ADR-W-010): cantidad fija de segmentos por hilera (máximo de activos y reparto estándar)."""
    return settings.SEGMENTOS_POR_HILERA


def plantas_por_largo(largo_m):
    """Plantas de una hilera de `largo_m` metros con la distancia entre plantas del fundo (200 m → 133)."""
    return max(1, round(largo_m / settings.DISTANCIA_ENTRE_PLANTAS_M))


def estado_segmentos(row, activos=None):
    """Cómo está la hilera frente a la regla fija: segmentos activos (n de N), plantas sin segmento (huecos), si
    pasa el límite y si tiene el reparto estándar completo. `activos` evita la consulta si ya se tienen."""
    total = segmentos_por_hilera()
    segs = sorted(activos if activos is not None else row.segments.filter(active=True),
                  key=lambda s: (s.start_plant, s.end_plant))
    huecos, siguiente = [], 1
    for s in segs:
        if s.start_plant > siguiente:
            huecos.append((siguiente, min(s.start_plant - 1, row.plant_count)))
        siguiente = max(siguiente, s.end_plant + 1)
    if siguiente <= row.plant_count:
        huecos.append((siguiente, row.plant_count))
    n = len(segs)
    return {"n": n, "total": total, "huecos": huecos, "excede": n > total,
            "estandar": n == min(total, row.plant_count) and not huecos,
            "metros_por_segmento": round(row.length_m / n, 1) if (row.length_m and n) else None}


def metros_de(row, seg):
    """Largo aproximado de un segmento en metros (None si la hilera no tiene largo)."""
    if not row.length_m or not row.plant_count:
        return None
    return round(row.length_m * (seg.end_plant - seg.start_plant + 1) / row.plant_count, 1)


def _verificar_limite(row, excluir=None):
    activos = row.segments.filter(active=True)
    if excluir is not None:
        activos = activos.exclude(pk=excluir)
    total = segmentos_por_hilera()
    if activos.count() >= total:
        raise ValidationError(f"La hilera ya tiene {total} segmentos activos, que es la cantidad fija por hilera. "
                              "Desactiva uno o usa «Dividir» para rehacerlos.")


def id_de_lote(code):
    """«SWG 1» → «SWG1»: mayúsculas, sin tildes ni espacios ni símbolos. Si ya existe, sufijo -2, -3…"""
    base = unicodedata.normalize("NFKD", code).encode("ascii", "ignore").decode().upper()
    base = re.sub(r"[^A-Z0-9-]", "", base)[:16] or "LOTE"
    if not FieldLot.objects.filter(pk=base).exists():
        return base
    return _id_libre(FieldLot, base, "-{}", inicio=2, max_len=20)


def sesiones_en_curso(rows):
    """Cantidad de sesiones no cerradas en el servidor con pasadas en esas hileras (aviso, no bloquea)."""
    from monitoreo.models import MonitoringPass, SessionStatus

    return (MonitoringPass.objects.filter(row__in=rows).exclude(session__status=SessionStatus.CLOSED)
            .values("session_id").distinct().count())


def _sin_solape(row, inicio, fin, excluir=None):
    otros = FieldSegment.objects.filter(row=row, active=True, start_plant__lte=fin, end_plant__gte=inicio)
    if excluir is not None:
        otros = otros.exclude(pk=excluir)
    choque = otros.order_by("start_plant").first()
    if choque:
        raise ValidationError({"start_plant": f"Se cruza con el segmento «{choque.code}» "
                                              f"(plantas {choque.start_plant} a {choque.end_plant})."})


def _codigo_unico(model, row, code, excluir=None):
    qs = model.objects.filter(row=row, active=True, code__iexact=code)
    if excluir is not None:
        qs = qs.exclude(pk=excluir)
    if qs.exists():
        raise ValidationError({"code": "Ya hay otro activo con ese código en esta hilera."})


# ------------------------------------------------------------------ lotes
def crear_lote(user, code, name):
    _require(user)
    code, name = _limpio(code), _limpio(name)
    errores = {}
    if not code:
        errores["code"] = "Escribe el código del lote (por ejemplo, SWG 4)."
    elif len(code) > 20:
        errores["code"] = "Máximo 20 caracteres."
    elif FieldLot.objects.filter(code__iexact=code).exists():
        errores["code"] = "Ya existe un lote con ese código."
    if not name:
        errores["name"] = "Escribe el nombre del lote."
    if errores:
        raise ValidationError(errores)
    with transaction.atomic():
        lot = FieldLot.objects.create(id=id_de_lote(code), code=code, name=name[:80], active=True)
        audit.record("field_lot", lot.pk, "CATALOGO_CREADO", user, None, {"code": code, "name": lot.name})
    return lot


def editar_lote(user, lot_id, code, name):
    _require(user)
    code, name = _limpio(code), _limpio(name)
    errores = {}
    if not code or len(code) > 20:
        errores["code"] = "Escribe un código de 1 a 20 caracteres."
    if not name:
        errores["name"] = "Escribe el nombre del lote."
    if errores:
        raise ValidationError(errores)
    with transaction.atomic():
        lot = _bloquear(FieldLot, lot_id)
        if FieldLot.objects.filter(code__iexact=code).exclude(pk=lot.pk).exists():
            raise ValidationError({"code": "Ya existe un lote con ese código."})
        antes = _foto(lot, ("code", "name"))
        lot.code, lot.name = code, name[:80]
        lot.save(update_fields=["code", "name"])
        a, d = _cambios(antes, _foto(lot, ("code", "name")))
        if d:
            audit.record("field_lot", lot.pk, "CATALOGO_EDITADO", user, a, d)
    return lot


# ------------------------------------------------------------------ hileras
def _segmento_completo(row):
    """Segmento «Hxx completa» (planta 1 a plant_count) con marcadores de inicio y fin, como el script del VPS."""
    n = f"H{row.number:02d}"
    seg_id = f"{row.pk}-S1" if not FieldSegment.objects.filter(pk=f"{row.pk}-S1").exists() else \
        _id_libre(FieldSegment, f"{row.pk}-S", "{}", inicio=2)
    seg = FieldSegment.objects.create(id=seg_id, row=row, code=f"{n} completa", start_plant=1,
                                      end_plant=row.plant_count, active=True)
    marcadores = []
    for sufijo, pos, nombre in (("INI", MarkerPosition.INICIO, "inicio"), ("FIN", MarkerPosition.FIN, "fin")):
        if Marker.objects.filter(row=row, active=True, code__iexact=f"{n} {nombre}").exists():
            continue  # ya hay un marcador activo con ese código en la hilera: no se duplica
        mid = f"{row.pk}-{sufijo}"
        if Marker.objects.filter(pk=mid).exists():
            mid = _id_libre(Marker, f"{row.pk}-M", "{}")
        marcadores.append(Marker.objects.create(
            id=mid, row=row, segment=seg, code=f"{n} {nombre}", position=pos, active=True,
            description=f"{nombre.capitalize()} de la hilera {row.number}"))
    return seg, marcadores


def _validar_largo(largo_m, campo="largo_m"):
    if largo_m is not None and not 1 <= largo_m <= MAX_LARGO_HILERA_M:
        raise ValidationError({campo: f"El largo va de 1 a {MAX_LARGO_HILERA_M} metros."})


def crear_hileras(user, lot_id, desde, hasta, plantas=None, segmento_completo=True, largo_m=None, division=None):
    """Alta en bloque. Salta los números que ya existen (activos o no). Devuelve (creadas, saltadas).
    v1.4 (ADR-W-010): `largo_m` (metros) se guarda en cada hilera y, si faltan las plantas, las calcula con la
    distancia entre plantas. `division`: «estandar» (N segmentos con marcadores), «completa» (un segmento de hilera
    completa con inicio y fin) o «ninguna»; si no se indica, se usa `segmento_completo` como antes."""
    _require(user)
    if division is None:
        division = "completa" if segmento_completo else "ninguna"
    errores = {}
    if desde is None or desde < 1:
        errores["desde"] = "El primer número debe ser 1 o más."
    if hasta is None or (desde and hasta < desde):
        errores["hasta"] = "El último número no puede ser menor que el primero."
    if largo_m is not None and not 1 <= largo_m <= MAX_LARGO_HILERA_M:
        errores["largo_m"] = f"El largo va de 1 a {MAX_LARGO_HILERA_M} metros."
    elif plantas is None and largo_m:
        plantas = plantas_por_largo(largo_m)
    if plantas is None or plantas < 1:
        errores["plantas"] = "Escribe cuántas plantas tiene cada hilera (1 o más) o su largo en metros."
    if division not in DIVISIONES:
        errores["division"] = "Elige cómo crear los segmentos."
    if not errores and hasta - desde + 1 > MAX_HILERAS_POR_ALTA:
        errores["hasta"] = f"Máximo {MAX_HILERAS_POR_ALTA} hileras por vez."
    if errores:
        raise ValidationError(errores)
    with transaction.atomic():
        lot = _bloquear(FieldLot, lot_id)
        if not lot.active:
            raise ValidationError("El lote está desactivado: reactívalo antes de agregar hileras.")
        existentes = set(FieldRow.objects.filter(lot=lot, number__range=(desde, hasta)).values_list("number", flat=True))
        creadas, saltadas = [], sorted(existentes)
        for n in range(desde, hasta + 1):
            if n in existentes:
                continue
            rid = f"{lot.pk}-H{n:02d}"
            if FieldRow.objects.filter(pk=rid).exists():
                rid = _id_libre(FieldRow, f"{rid}-", "{}", inicio=2, max_len=30)
            row = FieldRow.objects.create(id=rid, lot=lot, number=n, plant_count=plantas, length_m=largo_m,
                                          active=True)
            if division == "estandar":
                _dividir(row, _rangos_estandar(row.plant_count), con_marcadores=True, nueva=True)
            elif division == "completa":
                _segmento_completo(row)
            creadas.append(n)
        audit.record("field_lot", lot.pk, "CATALOGO_LOTE_HILERAS", user, None,
                     {"desde": desde, "hasta": hasta, "plantas": plantas, "largoM": largo_m, "division": division,
                      "segmentoCompleto": division == "completa", "creadas": creadas, "saltadas": saltadas})
    return creadas, saltadas


def completar_hileras_sin_segmento(user, lot_id):
    """Crea el segmento de hilera completa (con inicio y fin) en cada hilera activa del lote sin segmentos activos."""
    _require(user)
    with transaction.atomic():
        lot = _bloquear(FieldLot, lot_id)
        rows = list(FieldRow.objects.filter(lot=lot, active=True).exclude(segments__active=True).order_by("number"))
        for row in rows:
            _segmento_completo(row)
        if rows:
            audit.record("field_lot", lot.pk, "CATALOGO_LOTE_HILERAS", user, None,
                         {"completadas": [r.number for r in rows], "segmentoCompleto": True})
    return len(rows)


_SIN_CAMBIO = object()


def editar_hilera(user, row_id, plant_count, length_m=_SIN_CAMBIO):
    """Plantas y (v1.4) largo aproximado en metros. Si sube el número de plantas, las últimas quedan sin segmento:
    la web lo muestra como hueco y «Dividir» rehace el reparto estándar."""
    _require(user)
    if plant_count is None or plant_count < 1:
        raise ValidationError({"plant_count": "La hilera debe tener 1 planta o más."})
    if length_m is not _SIN_CAMBIO:
        _validar_largo(length_m, "length_m")
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        mayor = row.segments.filter(active=True).aggregate(m=Max("end_plant"))["m"] or 0
        if plant_count < mayor:
            raise ValidationError({"plant_count": f"Hay un segmento activo que llega a la planta {mayor}: "
                                                  "ajústalo o desactívalo antes de bajar el número de plantas."})
        antes = _foto(row, ("plant_count", "length_m"))
        row.plant_count = plant_count
        if length_m is not _SIN_CAMBIO:
            row.length_m = length_m
        row.save(update_fields=["plant_count", "length_m"])
        a, d = _cambios(antes, _foto(row, ("plant_count", "length_m")))
        if d:
            audit.record("field_row", row.pk, "CATALOGO_EDITADO", user, a, d)
    return row


# ------------------------------------------------------------------ segmentos
def _validar_segmento(row, code, inicio, fin, excluir=None):
    errores = {}
    if not code:
        errores["code"] = "Escribe el código del segmento."
    elif len(code) > 40:
        errores["code"] = "Máximo 40 caracteres."
    if inicio is None or inicio < 1:
        errores["start_plant"] = "La planta de inicio debe ser 1 o más."
    if fin is None or (inicio and fin < inicio):
        errores["end_plant"] = "La planta final no puede ser menor que la de inicio."
    elif fin > row.plant_count:
        errores["end_plant"] = f"La hilera tiene {row.plant_count} plantas."
    if errores:
        raise ValidationError(errores)
    _codigo_unico(FieldSegment, row, code, excluir)
    _sin_solape(row, inicio, fin, excluir)


def crear_segmento(user, row_id, code, start_plant, end_plant, is_pilot=False):
    _require(user)
    code = _limpio(code)
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        if not row.active:
            raise ValidationError("La hilera está desactivada: reactívala antes de agregar segmentos.")
        _verificar_limite(row)  # v1.4 (ADR-W-010): antes no había tope al crear segmentos uno por uno
        _validar_segmento(row, code, start_plant, end_plant)
        seg = FieldSegment.objects.create(id=_id_libre(FieldSegment, f"{row.pk}-S", "{}"), row=row, code=code,
                                          start_plant=start_plant, end_plant=end_plant, is_pilot=bool(is_pilot))
        audit.record("field_segment", seg.pk, "CATALOGO_CREADO", user, None,
                     {"row": row.pk, "code": code, "start_plant": start_plant, "end_plant": end_plant,
                      "is_pilot": seg.is_pilot})
    return seg


def editar_segmento(user, segment_id, code, start_plant, end_plant, is_pilot=False):
    _require(user)
    code = _limpio(code)
    campos = ("code", "start_plant", "end_plant", "is_pilot")
    with transaction.atomic():
        seg = _bloquear(FieldSegment, segment_id)
        row = FieldRow.objects.get(pk=seg.row_id)
        if seg.active:
            _validar_segmento(row, code, start_plant, end_plant, excluir=seg.pk)
        else:
            raise ValidationError("El segmento está desactivado: reactívalo para editarlo.")
        antes = _foto(seg, campos)
        seg.code, seg.start_plant, seg.end_plant, seg.is_pilot = code, start_plant, end_plant, bool(is_pilot)
        seg.save(update_fields=list(campos))
        a, d = _cambios(antes, _foto(seg, campos))
        if d:
            audit.record("field_segment", seg.pk, "CATALOGO_EDITADO", user, a, d)
    return seg


def rangos_division(plant_count, partes=None, cada=None):
    """[(inicio, fin)] para dividir una hilera en N partes iguales o cada K plantas (nunca más segmentos que la
    cantidad fija por hilera)."""
    maximo = segmentos_por_hilera()
    if partes:
        if partes < 1 or partes > min(maximo, plant_count):
            raise ValidationError({"valor": f"Elige de 1 a {min(maximo, plant_count)} partes "
                                            f"(la cantidad fija por hilera es {maximo})."})
        base, resto = divmod(plant_count, partes)
        rangos, inicio = [], 1
        for i in range(partes):
            largo = base + (1 if i < resto else 0)
            rangos.append((inicio, inicio + largo - 1))
            inicio += largo
        return rangos
    if cada:
        if cada < 1 or cada > plant_count:
            raise ValidationError({"valor": f"Elige de 1 a {plant_count} plantas por segmento."})
        rangos = [(i, min(i + cada - 1, plant_count)) for i in range(1, plant_count + 1, cada)]
        if len(rangos) > maximo:
            raise ValidationError({"valor": f"Saldrían {len(rangos)} segmentos; el máximo por hilera es {maximo}."})
        return rangos
    raise ValidationError({"valor": "Indica en cuántas partes o cada cuántas plantas."})


def _rangos_estandar(plant_count):
    """Reparto estándar: la cantidad fija de partes iguales (o una por planta si la hilera es más corta)."""
    return rangos_division(plant_count, partes=min(segmentos_por_hilera(), plant_count))


def _punto_extremo(row, posicion):
    """(lat, lon) del marcador activo de inicio o fin de la hilera si está en el extremo de verdad (planta 1 o la
    última) y tiene coordenadas; si no, None."""
    m = _extremo(row, posicion)
    if m is None or m.lat is None or m.lon is None:
        return None
    if m.segment_id:
        seg = m.segment
        if posicion == MarkerPosition.INICIO and seg.start_plant != 1:
            return None
        if posicion == MarkerPosition.FIN and seg.end_plant != row.plant_count:
            return None
    return m.lat, m.lon


def _interpolar(ini, fin, planta, plant_count):
    """Coordenada aproximada de una planta sobre la línea recta entre el inicio y el fin de la hilera."""
    if ini is None or fin is None:
        return (ini if planta == 1 else None) or (fin if planta == plant_count else None) or (None, None)
    t = (planta - 1) / max(1, plant_count - 1)
    return round(ini[0] + t * (fin[0] - ini[0]), 7), round(ini[1] + t * (fin[1] - ini[1]), 7)


def _ids_libres(model, prefijo, cantidad, max_len=40):
    """`cantidad` IDs libres «prefijo1», «prefijo2»… con UNA consulta (incluye inactivos: no se reutilizan)."""
    usados = set(model.objects.filter(pk__startswith=prefijo).values_list("pk", flat=True))
    libres, k = [], 1
    while len(libres) < cantidad:
        candidato = f"{prefijo}{k}"
        if len(candidato) > max_len:
            raise ValidationError("No se pudo generar un identificador: el código es demasiado largo.")
        if candidato not in usados:
            libres.append(candidato)
        k += 1
    return libres


def _dividir(row, rangos, con_marcadores=True, nueva=False):
    """Desactiva los segmentos activos de la hilera (y sus marcadores) y crea los nuevos. Si el inicio y el fin de la
    hilera ya estaban ubicados en el mapa, los marcadores nuevos heredan esas coordenadas y los intermedios se
    interpolan: los casos sin GPS siguen teniendo ubicación aproximada (±medio segmento). Pocas consultas por
    hilera (IDs libres de una vez y bulk_create): el alta de cientos de hileras en Supabase no se hace eterna.
    `nueva=True` (hilera recién creada) se salta lo que no puede existir todavía.
    Devuelve (nuevos, segmentos_viejos, marcadores_viejos). Sin auditoría: la hace quien llama."""
    ini = fin = None
    viejos, marc_viejos = [], []
    if not nueva:
        ini, fin = _punto_extremo(row, MarkerPosition.INICIO), _punto_extremo(row, MarkerPosition.FIN)
        viejos = list(row.segments.filter(active=True).values_list("pk", flat=True))
        marc_viejos = list(Marker.objects.filter(segment_id__in=viejos, active=True).values_list("pk", flat=True))
        FieldSegment.objects.filter(pk__in=viejos).update(active=False)
        Marker.objects.filter(pk__in=marc_viejos).update(active=False)
    n = f"H{row.number:02d}"
    total = len(rangos)
    nuevos = [FieldSegment(id=sid, row=row, code=f"{n} S{i}", start_plant=a, end_plant=b, active=True)
              for i, (sid, (a, b)) in enumerate(zip(_ids_libres(FieldSegment, f"{row.pk}-S", total), rangos), 1)]
    FieldSegment.objects.bulk_create(nuevos)
    if con_marcadores and nuevos:
        ocupados = set() if nueva else {c.lower() for c in Marker.objects.filter(row=row, active=True)
                                        .values_list("code", flat=True)}
        mids = iter(_ids_libres(Marker, f"{row.pk}-M", total + 1))
        marcadores = []
        for i, seg in enumerate(nuevos, start=1):
            lat, lon = _interpolar(ini, fin, seg.start_plant, row.plant_count)
            marcadores.append(Marker(
                id=next(mids), row=row, segment=seg, code=f"{n} S{i} inicio", active=True, lat=lat, lon=lon,
                position=MarkerPosition.INICIO if i == 1 else MarkerPosition.INTERMEDIO,
                description=f"Inicio del segmento {i} de {total} (planta {seg.start_plant})"))
        lat, lon = fin or (None, None)
        marcadores.append(Marker(id=next(mids), row=row, segment=nuevos[-1], code=f"{n} fin", active=True,
                                 position=MarkerPosition.FIN, lat=lat, lon=lon,
                                 description=f"Fin de la hilera {row.number} (planta {row.plant_count})"))
        for m in marcadores:
            if m.code.lower() in ocupados:
                raise ValidationError(f"Ya hay un marcador activo «{m.code}» en la hilera: desactívalo o cámbiale el "
                                      "código antes de dividir.")
        Marker.objects.bulk_create(marcadores)
    return nuevos, viejos, marc_viejos


def dividir_hilera(user, row_id, partes=None, cada=None, con_marcadores=True):
    """Reemplaza los segmentos activos de la hilera por segmentos nuevos (los anteriores y sus marcadores se
    desactivan: la historia se conserva). Con marcadores: inicio de cada segmento y fin de la hilera."""
    _require(user)
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        if not row.active:
            raise ValidationError("La hilera está desactivada: reactívala antes de dividirla.")
        rangos = rangos_division(row.plant_count, partes, cada)
        nuevos, viejos, marc_viejos = _dividir(row, rangos, con_marcadores)
        audit.record("field_row", row.pk, "CATALOGO_EDITADO", user,
                     {"segmentosActivos": viejos, "marcadoresDesactivados": marc_viejos},
                     {"segmentosActivos": [s.pk for s in nuevos], "rangos": [list(r) for r in rangos]})
    return nuevos


def estandarizar_lote(user, lot_id):
    """v1.4 (ADR-W-010): pasa al reparto estándar (N segmentos iguales con marcadores) las hileras activas del lote
    que no lo tienen. Las que ya lo cumplen no se tocan. Devuelve los números de hilera cambiados."""
    _require(user)
    with transaction.atomic():
        lot = _bloquear(FieldLot, lot_id)
        if not lot.active:
            raise ValidationError("El lote está desactivado: reactívalo antes de cambiar sus segmentos.")
        cambiadas = []
        for row in (FieldRow.objects.select_for_update().filter(lot=lot, active=True)
                    .prefetch_related("segments").order_by("number")):
            activos = [s for s in row.segments.all() if s.active]
            if estado_segmentos(row, activos)["estandar"]:
                continue
            rangos = _rangos_estandar(row.plant_count)
            nuevos, viejos, marc_viejos = _dividir(row, rangos, con_marcadores=True)
            audit.record("field_row", row.pk, "CATALOGO_EDITADO", user,
                         {"segmentosActivos": viejos, "marcadoresDesactivados": marc_viejos},
                         {"segmentosActivos": [s.pk for s in nuevos], "rangos": [list(r) for r in rangos]})
            cambiadas.append(row.number)
        if cambiadas:
            audit.record("field_lot", lot.pk, "CATALOGO_LOTE_SEGMENTOS", user, None,
                         {"hileras": cambiadas, "segmentosPorHilera": segmentos_por_hilera()})
    return cambiadas


# ------------------------------------------------------------------ marcadores
def _validar_marcador(row, code, position, segment, lat, lon, excluir=None):
    errores = {}
    if not code:
        errores["code"] = "Escribe el código del marcador."
    elif len(code) > 40:
        errores["code"] = "Máximo 40 caracteres."
    if position not in MarkerPosition.values:
        errores["position"] = "Elige inicio, fin o intermedio."
    if segment is not None and (segment.row_id != row.pk or not segment.active):
        errores["segment"] = "El segmento debe ser uno activo de esta misma hilera."
    if (lat is None) != (lon is None):
        errores["lat"] = "Escribe latitud y longitud juntas, o deja las dos vacías."
    else:
        if lat is not None and not -90 <= lat <= 90:
            errores["lat"] = "La latitud va de -90 a 90."
        if lon is not None and not -180 <= lon <= 180:
            errores["lon"] = "La longitud va de -180 a 180."
    if errores:
        raise ValidationError(errores)
    _codigo_unico(Marker, row, code, excluir)


def crear_marcador(user, row_id, code, position, segment_id=None, description="", lat=None, lon=None):
    _require(user)
    code, description = _limpio(code), _limpio(description)[:200]
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        if not row.active:
            raise ValidationError("La hilera está desactivada: reactívala antes de agregar marcadores.")
        segment = FieldSegment.objects.filter(pk=segment_id).first() if segment_id else None
        _validar_marcador(row, code, position, segment, lat, lon)
        m = Marker.objects.create(id=_id_libre(Marker, f"{row.pk}-M", "{}"), row=row, segment=segment, code=code,
                                  position=position, description=description, lat=lat, lon=lon)
        audit.record("marker", m.pk, "CATALOGO_CREADO", user, None,
                     {"row": row.pk, "code": code, "position": position, "segment": segment_id or None,
                      "lat": lat, "lon": lon})
    return m


def editar_marcador(user, marker_id, code, position, segment_id=None, description="", lat=None, lon=None):
    _require(user)
    code, description = _limpio(code), _limpio(description)[:200]
    campos = ("code", "position", "segment_id", "description", "lat", "lon")
    with transaction.atomic():
        m = _bloquear(Marker, marker_id)
        if not m.active:
            raise ValidationError("El marcador está desactivado: reactívalo para editarlo.")
        row = FieldRow.objects.get(pk=m.row_id)
        segment = FieldSegment.objects.filter(pk=segment_id).first() if segment_id else None
        _validar_marcador(row, code, position, segment, lat, lon, excluir=m.pk)
        antes = _foto(m, campos)
        m.code, m.position, m.segment, m.description, m.lat, m.lon = code, position, segment, description, lat, lon
        m.save(update_fields=["code", "position", "segment", "description", "lat", "lon"])
        a, d = _cambios(antes, _foto(m, campos))
        if d:
            audit.record("marker", m.pk, "CATALOGO_EDITADO", user, a, d)
    return m


# ------------------------------------------------------------------ desactivar y reactivar
def desactivar(user, tipo, pk):
    """Lote o hilera: deja de verse en la app y en el plano junto con lo de adentro (sin tocar sus hijos, para
    poder reactivar). Segmento: también desactiva sus marcadores. Devuelve el aviso de sesiones en curso (o 0)."""
    _require(user)
    model, entidad = ENTIDADES[tipo]
    with transaction.atomic():
        obj = _bloquear(model, pk)
        if not obj.active:
            return 0
        obj.active = False
        obj.save(update_fields=["active"])
        extra = {}
        if tipo == "segmento":
            ids = list(obj.markers.filter(active=True).values_list("pk", flat=True))
            Marker.objects.filter(pk__in=ids).update(active=False)
            extra["marcadoresDesactivados"] = ids
        audit.record(entidad, obj.pk, "CATALOGO_DESACTIVADO", user, {"active": True}, {"active": False, **extra})
    rows = {"lote": FieldRow.objects.filter(lot_id=pk), "hilera": FieldRow.objects.filter(pk=pk),
            "segmento": FieldRow.objects.filter(pk=getattr(obj, "row_id", None)),
            "marcador": FieldRow.objects.filter(pk=getattr(obj, "row_id", None))}[tipo]
    return sesiones_en_curso(rows)


def reactivar(user, tipo, pk):
    _require(user)
    model, entidad = ENTIDADES[tipo]
    with transaction.atomic():
        obj = _bloquear(model, pk)
        if obj.active:
            return obj
        if tipo == "hilera" and not obj.lot.active:
            raise ValidationError("Primero reactiva el lote.")
        if tipo in ("segmento", "marcador"):
            row = obj.row
            if not (row.active and row.lot.active):
                raise ValidationError("Primero reactiva la hilera (y su lote).")
        if tipo == "segmento":
            _verificar_limite(obj.row, excluir=obj.pk)  # v1.4: reactivar tampoco pasa la cantidad fija
            _validar_segmento(obj.row, obj.code, obj.start_plant, obj.end_plant, excluir=obj.pk)
        if tipo == "marcador":
            if obj.segment_id and not obj.segment.active:
                raise ValidationError("Primero reactiva su segmento, o edítalo sin segmento.")
            _codigo_unico(Marker, obj.row, obj.code, excluir=obj.pk)
        obj.active = True
        obj.save(update_fields=["active"])
        audit.record(entidad, obj.pk, "CATALOGO_REACTIVADO", user, {"active": False}, {"active": True})
    return obj


# ------------------------------------------------------------------ v1.3 (ADR-W-007): mapa satelital editable
MAX_VERTICES = 500


def _coordenada(par, campo="coordenadas"):
    """[lat, lon] o (lat, lon) → (lat, lon) en rango, o ValidationError."""
    try:
        lat, lon = float(par[0]), float(par[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ValidationError({campo: "Coordenadas inválidas."}) from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValidationError({campo: "La latitud va de -90 a 90 y la longitud de -180 a 180."})
    return round(lat, 7), round(lon, 7)


def validar_poligono(geometry):
    """GeoJSON Polygon (WGS84, [lon, lat]) con un solo anillo de 3 a MAX_VERTICES vértices distintos. Cierra el
    anillo si hace falta y redondea a 7 decimales (~1 cm). Devuelve la geometría limpia."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValidationError({"geometry": "El contorno debe ser un polígono (GeoJSON Polygon)."})
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or len(rings) != 1 or not isinstance(rings[0], list):
        raise ValidationError({"geometry": "El contorno debe tener un solo anillo, sin huecos."})
    ring = []
    for p in rings[0]:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise ValidationError({"geometry": "Vértice inválido."})
        lat, lon = _coordenada((p[1], p[0]), "geometry")
        ring.append([lon, lat])
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len({tuple(p) for p in ring}) < 3:
        raise ValidationError({"geometry": "Marca al menos 3 vértices distintos."})
    if len(ring) > MAX_VERTICES:
        raise ValidationError({"geometry": f"Máximo {MAX_VERTICES} vértices."})
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


def fijar_contorno_lote(user, lot_id, geometry):
    """Dibuja (o borra, con geometry=None) el contorno del lote en el mapa satelital."""
    _require(user)
    limpio = validar_poligono(geometry) if geometry is not None else None
    with transaction.atomic():
        lot = _bloquear(FieldLot, lot_id)
        antes = {"vertices": len(lot.geometry["coordinates"][0]) - 1} if lot.geometry else {"vertices": 0}
        lot.geometry = limpio
        lot.save(update_fields=["geometry"])
        audit.record("field_lot", lot.pk, "LOTE_CONTORNO", user, antes,
                     {"vertices": len(limpio["coordinates"][0]) - 1 if limpio else 0})
    return lot


def _extremo(row, posicion):
    """Marcador activo de inicio o fin de la hilera (el «-INI»/«-FIN» del segmento completo si existe)."""
    sufijo = "INI" if posicion == MarkerPosition.INICIO else "FIN"
    qs = Marker.objects.filter(row=row, active=True, position=posicion)
    return qs.filter(pk=f"{row.pk}-{sufijo}").first() or qs.order_by("pk").first()


def fijar_extremos_hilera(user, row_id, inicio=None, fin=None):
    """Fija las coordenadas de los marcadores de INICIO y FIN de la hilera con dos clics en el mapa. Si la hilera no
    tiene esos marcadores, los crea (código «Hxx inicio» / «Hxx fin»). La hilera se dibuja como línea entre ambos y los
    casos sin GPS toman la coordenada de su marcador (revision.services.case_location)."""
    _require(user)
    if inicio is None and fin is None:
        raise ValidationError("Marca el inicio, el fin o los dos.")
    puntos = {MarkerPosition.INICIO: _coordenada(inicio, "inicio") if inicio is not None else None,
              MarkerPosition.FIN: _coordenada(fin, "fin") if fin is not None else None}
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        if not row.active:
            raise ValidationError("La hilera está desactivada: reactívala antes de ubicarla en el mapa.")
        n = f"H{row.number:02d}"
        resultado = {}
        for posicion, coord in puntos.items():
            if coord is None:
                continue
            m = _extremo(row, posicion)
            nombre = "inicio" if posicion == MarkerPosition.INICIO else "fin"
            if m is None:
                seg = row.segments.filter(active=True).order_by("start_plant").first()
                m = crear_marcador(user, row.pk, f"{n} {nombre}", posicion, seg.pk if seg else None,
                                   f"{nombre.capitalize()} de la hilera {row.number}", *coord)
            else:
                antes = {"lat": m.lat, "lon": m.lon}
                m.lat, m.lon = coord
                m.save(update_fields=["lat", "lon"])
                audit.record("marker", m.pk, "MARCADOR_UBICADO", user, antes, {"lat": m.lat, "lon": m.lon})
            resultado[nombre] = m
    return resultado


def _validar_punto(name, kind, lat, lon):
    from campo.models import PointKind

    errores = {}
    if not name:
        errores["name"] = "Escribe el nombre del punto."
    elif len(name) > 80:
        errores["name"] = "Máximo 80 caracteres."
    if kind not in PointKind.values:
        errores["kind"] = "Tipo de punto inválido."
    if errores:
        raise ValidationError(errores)
    return _coordenada((lat, lon))


def crear_punto(user, name, kind, lat, lon, description=""):
    from campo.models import PointOfInterest

    _require(user)
    name, description = _limpio(name), _limpio(description)[:200]
    lat, lon = _validar_punto(name, kind, lat, lon)
    with transaction.atomic():
        p = PointOfInterest.objects.create(name=name, kind=kind, description=description, lat=lat, lon=lon,
                                           created_by=user)
        audit.record("point", p.pk, "PUNTO_CREADO", user, None,
                     {"name": name, "kind": kind, "lat": lat, "lon": lon})
    return p


def editar_punto(user, point_id, name, kind, lat, lon, description=""):
    from campo.models import PointOfInterest

    _require(user)
    name, description = _limpio(name), _limpio(description)[:200]
    lat, lon = _validar_punto(name, kind, lat, lon)
    campos = ("name", "kind", "description", "lat", "lon")
    with transaction.atomic():
        p = _bloquear(PointOfInterest, point_id)
        if not p.active:
            raise ValidationError("El punto está eliminado.")
        antes = _foto(p, campos)
        p.name, p.kind, p.description, p.lat, p.lon = name, kind, description, lat, lon
        p.save(update_fields=list(campos))
        a, d = _cambios(antes, _foto(p, campos))
        if d:
            audit.record("point", p.pk, "PUNTO_EDITADO", user, a, d)
    return p


def eliminar_punto(user, point_id):
    """«Eliminar» = desactivar (queda en la auditoría y se puede consultar)."""
    from campo.models import PointOfInterest

    _require(user)
    with transaction.atomic():
        p = _bloquear(PointOfInterest, point_id)
        if p.active:
            p.active = False
            p.save(update_fields=["active"])
            audit.record("point", p.pk, "PUNTO_ELIMINADO", user, {"active": True}, {"active": False})
    return p
