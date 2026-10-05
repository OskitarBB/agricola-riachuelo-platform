# config/restricciones.py — Restricciones CHECK en la base de datos para los campos con estados controlados.
#
# Los TextChoices de Django solo validan en formularios y serializadores; la base de datos aceptaría cualquier texto.
# Este decorador agrega, a partir de las opciones de cada campo, un CHECK por campo (p. ej. users_status_valido)
# y los rangos físicos de coordenadas, precisión GPS y confianza. Así ni un error de código ni una edición desde el
# panel de Supabase pueden dejar un estado inexistente o una latitud imposible (informe, cap. X §10.7).
# Se declaran en Meta.constraints, por lo que viajan en las migraciones y valen igual en PostgreSQL y en SQLite.
from django.db.models import CheckConstraint, Q

RANGOS = {
    "lat": (-90, 90),
    "lon": (-180, 180),
    "gps_accuracy_m": (0, None),
    "max_confidence": (0, 1),
}


def _nombre(tabla, columna):
    return f"{tabla}_{columna}_valido"[:63]


def checks_de_opciones(model):
    """Decorador de modelos: un CHECK por cada campo con choices y por cada campo de RANGOS."""
    meta = model._meta
    actuales = {c.name for c in meta.constraints}
    nuevos = []
    for field in meta.local_concrete_fields:
        nombre = _nombre(meta.db_table, field.column)
        if nombre in actuales:
            continue
        condicion = None
        if field.choices:
            condicion = Q(**{f"{field.name}__in": [str(v) for v, _ in field.flatchoices]})
        elif field.name in RANGOS:
            minimo, maximo = RANGOS[field.name]
            condicion = Q(**{f"{field.name}__gte": minimo})
            if maximo is not None:
                condicion &= Q(**{f"{field.name}__lte": maximo})
        if condicion is None:
            continue
        if field.null:
            condicion |= Q(**{f"{field.name}__isnull": True})
        nuevos.append(CheckConstraint(condition=condicion, name=nombre))
    if nuevos:
        meta.constraints = [*meta.constraints, *nuevos]
        # ModelState.from_model (migraciones) lee las restricciones solo si están en original_attrs.
        meta.original_attrs["constraints"] = meta.constraints
    return model
