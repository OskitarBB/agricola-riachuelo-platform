# campo/services.py — v1.2 (ADR-W-006): reglas de los catálogos del fundo (lotes, hileras, segmentos y marcadores).
#
# Reglas que no se negocian (traspaso HANDOFF_CATALOGOS_WEB, §3):
#   · «Eliminar» = desactivar. Nunca se borran filas: hay celulares sin internet con el catálogo descargado y las
#     pasadas, secuencias y casos ya registrados apuntan a estos IDs.
#   · Los IDs se generan aquí, no cambian nunca y no se reutilizan (se comprueba incluso contra los inactivos).
#   · El número y el lote de una hilera no se editan (forman su ID).
#   · Toda escritura es atómica y queda en la auditoría (W-02, W-06, W-15).
# La sincronización de la app (monitoreo/services.py) no mira «active»: sigue aceptando IDs desactivados.
import re
import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from auditoria import services as audit
from campo.models import FieldLot, FieldRow, FieldSegment, Marker, MarkerPosition
from cuentas.models import Role

ROLES_CATALOGOS = (Role.ADMINISTRADOR, Role.SUPERVISOR)  # mismo conjunto que «catalogos.gestionar» (web/permissions)
MAX_HILERAS_POR_ALTA = 300
MAX_SEGMENTOS_POR_HILERA = 50

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


def crear_hileras(user, lot_id, desde, hasta, plantas, segmento_completo=True):
    """Alta en bloque. Salta los números que ya existen (activos o no). Devuelve (creadas, saltadas)."""
    _require(user)
    errores = {}
    if desde is None or desde < 1:
        errores["desde"] = "El primer número debe ser 1 o más."
    if hasta is None or (desde and hasta < desde):
        errores["hasta"] = "El último número no puede ser menor que el primero."
    if plantas is None or plantas < 1:
        errores["plantas"] = "Escribe cuántas plantas tiene cada hilera (1 o más)."
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
            row = FieldRow.objects.create(id=rid, lot=lot, number=n, plant_count=plantas, active=True)
            if segmento_completo:
                _segmento_completo(row)
            creadas.append(n)
        audit.record("field_lot", lot.pk, "CATALOGO_LOTE_HILERAS", user, None,
                     {"desde": desde, "hasta": hasta, "plantas": plantas, "segmentoCompleto": bool(segmento_completo),
                      "creadas": creadas, "saltadas": saltadas})
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


def editar_hilera(user, row_id, plant_count):
    _require(user)
    if plant_count is None or plant_count < 1:
        raise ValidationError({"plant_count": "La hilera debe tener 1 planta o más."})
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        mayor = row.segments.filter(active=True).aggregate(m=Max("end_plant"))["m"] or 0
        if plant_count < mayor:
            raise ValidationError({"plant_count": f"Hay un segmento activo que llega a la planta {mayor}: "
                                                  "ajústalo o desactívalo antes de bajar el número de plantas."})
        antes = row.plant_count
        row.plant_count = plant_count
        row.save(update_fields=["plant_count"])
        if antes != plant_count:
            audit.record("field_row", row.pk, "CATALOGO_EDITADO", user, {"plant_count": antes},
                         {"plant_count": plant_count})
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
    """[(inicio, fin)] para dividir una hilera en N partes iguales o cada K plantas."""
    if partes:
        if partes < 1 or partes > min(MAX_SEGMENTOS_POR_HILERA, plant_count):
            raise ValidationError({"valor": f"Elige de 1 a {min(MAX_SEGMENTOS_POR_HILERA, plant_count)} partes."})
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
        if len(rangos) > MAX_SEGMENTOS_POR_HILERA:
            raise ValidationError({"valor": f"Saldrían {len(rangos)} segmentos; el máximo es "
                                            f"{MAX_SEGMENTOS_POR_HILERA}."})
        return rangos
    raise ValidationError({"valor": "Indica en cuántas partes o cada cuántas plantas."})


def dividir_hilera(user, row_id, partes=None, cada=None, con_marcadores=True):
    """Reemplaza los segmentos activos de la hilera por segmentos nuevos (los anteriores y sus marcadores se
    desactivan: la historia se conserva). Con marcadores: inicio de cada segmento y fin de la hilera."""
    _require(user)
    with transaction.atomic():
        row = _bloquear(FieldRow, row_id)
        if not row.active:
            raise ValidationError("La hilera está desactivada: reactívala antes de dividirla.")
        rangos = rangos_division(row.plant_count, partes, cada)
        viejos = list(row.segments.filter(active=True).values_list("pk", flat=True))
        marc_viejos = list(Marker.objects.filter(segment_id__in=viejos, active=True).values_list("pk", flat=True))
        FieldSegment.objects.filter(pk__in=viejos).update(active=False)
        Marker.objects.filter(pk__in=marc_viejos).update(active=False)
        n = f"H{row.number:02d}"
        nuevos = []
        for i, (ini, fin) in enumerate(rangos, start=1):
            seg = FieldSegment.objects.create(id=_id_libre(FieldSegment, f"{row.pk}-S", "{}"), row=row,
                                              code=f"{n} S{i}", start_plant=ini, end_plant=fin, active=True)
            nuevos.append(seg)
            if con_marcadores:
                _codigo_libre_o_error(row, f"{n} S{i} inicio")
                Marker.objects.create(id=_id_libre(Marker, f"{row.pk}-M", "{}"), row=row, segment=seg,
                                      code=f"{n} S{i} inicio", active=True,
                                      position=MarkerPosition.INICIO if i == 1 else MarkerPosition.INTERMEDIO,
                                      description=f"Inicio del segmento {i} (planta {ini})")
        if con_marcadores and nuevos:
            _codigo_libre_o_error(row, f"{n} fin")
            Marker.objects.create(id=_id_libre(Marker, f"{row.pk}-M", "{}"), row=row, segment=nuevos[-1],
                                  code=f"{n} fin", position=MarkerPosition.FIN, active=True,
                                  description=f"Fin de la hilera {row.number} (planta {row.plant_count})")
        audit.record("field_row", row.pk, "CATALOGO_EDITADO", user,
                     {"segmentosActivos": viejos, "marcadoresDesactivados": marc_viejos},
                     {"segmentosActivos": [s.pk for s in nuevos], "rangos": [list(r) for r in rangos]})
    return nuevos


def _codigo_libre_o_error(row, code):
    if Marker.objects.filter(row=row, active=True, code__iexact=code).exists():
        raise ValidationError(f"Ya hay un marcador activo «{code}» en la hilera: desactívalo o cámbiale el código "
                              "antes de dividir.")


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
            _validar_segmento(obj.row, obj.code, obj.start_plant, obj.end_plant, excluir=obj.pk)
        if tipo == "marcador":
            if obj.segment_id and not obj.segment.active:
                raise ValidationError("Primero reactiva su segmento, o edítalo sin segmento.")
            _codigo_unico(Marker, obj.row, obj.code, excluir=obj.pk)
        obj.active = True
        obj.save(update_fields=["active"])
        audit.record(entidad, obj.pk, "CATALOGO_REACTIVADO", user, {"active": False}, {"active": True})
    return obj
