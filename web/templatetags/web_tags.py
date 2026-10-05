# web/templatetags/web_tags.py — Insignias de estado (color + icono + texto; nunca solo color: RNF-W06) y utilidades
# de presentación. Los números que van a atributos o CSS se escriben sin localizar (W-16).
from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

# estado → (clase CSS, icono). Los colores de los casos indican ESTADO DE REVISIÓN, nunca gravedad (W-12).
BADGES = {
    # revisión del caso
    "PENDIENTE_REVISION": ("b-pendiente", "◷"),
    "CONFIRMADO_POR_ESPECIALISTA": ("b-confirmado", "✔"),
    "DESCARTADO": ("b-descartado", "✕"),
    "EVIDENCIA_INSUFICIENTE": ("b-insuficiente", "?"),
    # análisis de IA
    "PENDIENTE_DE_ANALISIS": ("b-neutro", "◷"),
    "EN_ANALISIS": ("b-proceso", "⟳"),
    "INDICIO_SUGERIDO_POR_IA": ("b-indicio", "◆"),
    "SIN_INDICIOS_IA": ("b-neutro", "○"),
    "ERROR_DE_ANALISIS": ("b-error", "⚠"),
    # avisos
    "NO_APLICA": ("b-neutro", "–"),
    "PENDIENTE_ENVIO": ("b-pendiente", "◷"),
    "ENVIADO": ("b-ok", "✔"),
    "ERROR_ENVIO": ("b-error", "⚠"),
    # cuentas, sesiones, pasadas, calidad
    "ACTIVO": ("b-ok", "●"), "PENDIENTE_APROBACION": ("b-pendiente", "◷"),
    "RECHAZADO": ("b-descartado", "✕"), "BLOQUEADO": ("b-error", "⛔"),
    "CLOSED": ("b-ok", "✔"), "COMPLETED": ("b-ok", "✔"), "INCOMPLETE": ("b-pendiente", "◐"),
    "UTILIZABLE": ("b-ok", "✔"), "PENDIENTE_REVISION_TECNICA": ("b-pendiente", "◷"),
    "REPETIR_NITIDEZ": ("b-descartado", "↺"), "REPETIR_EXPOSICION": ("b-descartado", "↺"),
    "ERROR_CAMARA": ("b-error", "⚠"),
    # v1.0+: sesiones abiertas que llegan de la app
    "ACTIVE": ("b-proceso", "▶"), "PAUSED": ("b-pendiente", "❚❚"), "CLOSING": ("b-proceso", "⟳"),
    "READY": ("b-neutro", "○"), "PREPARING": ("b-neutro", "○"), "DRAFT": ("b-neutro", "○"),
}

# Color del avatar por rol (Integrador §9.7 «Avatar de usuario»): identifica el rol, no un estado.
ROLE_TONES = {"ADMINISTRADOR": "av-admin", "ESPECIALISTA_FITOSANITARIO": "av-especialista",
              "SUPERVISOR": "av-supervisor", "OPERADOR_CAMPO": "av-operador"}


@register.simple_tag
def badge(value, label=None):
    css, icon = BADGES.get(str(value), ("b-neutro", "•"))
    return format_html('<span class="badge {}"><span aria-hidden="true">{}</span> {}</span>', css, icon,
                       label or str(value))


@register.simple_tag
def icono(nombre, clase=""):
    """Ícono del sprite web/static/web/iconos.svg (Lucide, licencia ISC). Decorativo: siempre va con texto."""
    return format_html('<svg class="ico {}" aria-hidden="true" focusable="false"><use href="{}#i-{}"></use></svg>',
                       clase, static("web/iconos.svg"), nombre)


@register.simple_tag
def avatar(user, size=""):
    roles = sorted(getattr(user, "roles", []) or [])
    tone = ROLE_TONES.get(roles[0], "av-operador") if roles else "av-operador"
    for preferido in ("ADMINISTRADOR", "ESPECIALISTA_FITOSANITARIO", "SUPERVISOR"):
        if preferido in roles:
            tone = ROLE_TONES[preferido]
            break
    return format_html('<span class="avatar {} {}" aria-hidden="true">{}</span>', tone, size,
                       getattr(user, "initials", "?"))


@register.filter
def duracion(td):
    """timedelta → «3 d 4 h», «2 h 15 min» o «8 min»."""
    if td is None:
        return "—"
    minutes = int(td.total_seconds() // 60)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {mins} min"
    return f"{mins} min"


@register.filter
def pct(part, total):
    try:
        return f"{100 * part / total:.0f} %" if total else "—"
    except (TypeError, ZeroDivisionError):
        return "—"


@register.filter
def pctnum(part, total):
    """Porcentaje sin localizar para atributos y CSS (W-16): «46.48»."""
    try:
        return f"{100 * part / total:.2f}" if total else "0"
    except (TypeError, ZeroDivisionError):
        return "0"


@register.filter
def get(d, key):
    return (d or {}).get(key, 0)


@register.simple_tag
def bar_width(value, maximum, full=100):
    """Ancho relativo (0–full) para dibujar hileras proporcionales a su número de plantas en el plano."""
    try:
        return f"{round(full * value / maximum, 2):.2f}" if maximum else "0"
    except (TypeError, ZeroDivisionError):
        return "0"


@register.simple_tag
def saludo():
    """Saludo según la hora de Lima (TIME_ZONE)."""
    from django.utils import timezone

    h = timezone.localtime().hour
    return "Buenos días" if 5 <= h < 12 else "Buenas tardes" if 12 <= h < 19 else "Buenas noches"


@register.filter
def primer_nombre(user):
    return (getattr(user, "full_name", "") or "").split(" ")[0]


ICONO_EVENTO = {"sesion": "sesiones", "caso": "chispa", "decision": "casos", "cuenta": "user-plus", "ingreso": "celulares"}


@register.filter
def icono_evento(tipo):
    return ICONO_EVENTO.get(tipo, "actividad")


def _corto(valor):
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, (list, tuple)):
        return ", ".join(_corto(v) for v in valor) or "—"
    if isinstance(valor, dict):
        return ", ".join(f"{k}: {_corto(v)}" for k, v in valor.items()) or "—"
    texto = str(valor)
    if len(texto) == 36 and texto.count("-") == 4:  # UUID: basta el prefijo para reconocerlo
        return texto[:8]
    return texto if len(texto) <= 60 else texto[:57] + "…"


@register.filter
def cambios(evento):
    """Auditoría legible: [(campo, antes, después)] a partir de before/after (JSON) de un AuditEvent."""
    antes, despues = evento.before or {}, evento.after or {}
    if not isinstance(antes, dict) or not isinstance(despues, dict):
        return [("valor", _corto(antes), _corto(despues))]
    claves = list(dict.fromkeys([*antes.keys(), *despues.keys()]))
    return [(k, _corto(antes.get(k)) if k in antes else None, _corto(despues.get(k)) if k in despues else None)
            for k in claves]
