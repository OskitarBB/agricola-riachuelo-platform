# diagnostico/bd.py — Revisa DATABASE_URL antes de conectar y traduce los errores de conexión a pasos concretos.
# Nunca imprime la contraseña: solo su largo y si tiene caracteres que rompen la URL.
import os
from urllib.parse import unquote, urlsplit

ESPECIALES_URL = set("@#/?:%[]<> \"'")


def url_cruda():
    return (os.environ.get("DATABASE_URL") or "").strip()


def resumen_seguro(url):
    """postgresql://usuario:****(N)@host:puerto/base — sin la contraseña."""
    if not url:
        return "(vacía: se usa SQLite)"
    try:
        p = urlsplit(url)
        clave = unquote(p.password or "")
        return (f"{p.scheme}://{p.username or '?'}:****({len(clave)} caracteres)@{p.hostname or '?'}:"
                f"{p.port or '?'}{p.path or ''}")
    except ValueError:
        return "(no se pudo leer: revisa que no tenga espacios ni comillas)"


def problemas_de_url(url):
    """Errores evidentes en la cadena antes de intentar conectar. Devuelve [(texto, ayuda)]."""
    if not url:
        return []
    errores = []
    if "[YOUR-PASSWORD]" in url.upper() or "<" in url or ">" in url:
        errores.append(("La DATABASE_URL todavía tiene el texto de ejemplo ([YOUR-PASSWORD] o <...>).",
                        "Reemplázalo, incluidos los corchetes, por la contraseña real de la base."))
    if url[:1] in "\"'" or url[-1:] in "\"'":
        errores.append(("La DATABASE_URL está entre comillas.", "Quita las comillas: DATABASE_URL=postgresql://..."))
    if " " in url:
        errores.append(("La DATABASE_URL tiene espacios.", "Debe ser una sola línea sin espacios."))
    if "#" in url:
        errores.append(("La contraseña tiene «#»: todo lo que va después se pierde y la contraseña llega cortada.",
                        "Cambia la contraseña en Supabase por una solo con letras y números."))
    try:
        p = urlsplit(url)
    except ValueError:
        return errores + [("No se pudo leer la DATABASE_URL.", "Copia de nuevo la cadena del Session pooler.")]
    if url.count("@") > 1:
        errores.append(("La contraseña tiene «@»: la dirección del servidor queda mal leída.",
                        "Cambia la contraseña por una solo con letras y números."))
    clave = unquote(p.password or "")
    if p.password is None:
        errores.append(("La DATABASE_URL no tiene contraseña.", "Formato: postgresql://usuario:CONTRASEÑA@host:5432/postgres"))
    elif ESPECIALES_URL & set(clave) and "%" not in (p.password or ""):
        errores.append(("La contraseña tiene caracteres especiales que pueden romper la URL "
                        f"({' '.join(sorted(ESPECIALES_URL & set(clave)))}).",
                        "Lo más simple: cambia la contraseña en Supabase por una solo con letras y números."))
    host = p.hostname or ""
    usuario = p.username or ""
    if host.endswith("pooler.supabase.com"):
        if "." not in usuario:
            errores.append((f"Con el pooler el usuario debe ser «postgres.<id-del-proyecto>», no «{usuario}».",
                            "Copia la cadena completa de Connect → Direct → Session pooler."))
        if p.port == 6543:
            errores.append(("El puerto 6543 es el «Transaction pooler», que no sirve para Django.",
                            "Usa el «Session pooler» (puerto 5432)."))
    if host.startswith("db.") and host.endswith(".supabase.co"):
        errores.append(("Es la «Direct connection» (solo IPv6): en muchas redes de casa no conecta.",
                        "Usa la cadena del «Session pooler» (…pooler.supabase.com:5432)."))
    return errores


def explicar_error(exc):
    """(texto, ayuda) en lenguaje claro para un error de conexión de psycopg/Django."""
    msg = str(exc)
    bajo = msg.lower()
    if "password authentication failed" in bajo:
        return ("Supabase rechazó la contraseña.",
                "1) Supabase → Project Settings → Database → «Reset database password» y escribe una nueva SOLO con "
                "letras y números (16+). 2) Pégala en DATABASE_URL en lugar de la anterior, sin [ ] ni comillas. "
                "3) Espera 1–2 minutos (el pooler tarda en enterarse) y vuelve a intentar.")
    if "tenant or user not found" in bajo or "tenant/user" in bajo:
        return ("El pooler no reconoce el usuario o el proyecto.",
                "El usuario debe ser «postgres.<id-del-proyecto>» y el host el que muestra Supabase para TU proyecto "
                "(la región importa: aws-0-<region>.pooler.supabase.com). Copia la cadena completa otra vez.")
    if ("could not translate host name" in bajo or "getaddrinfo" in bajo or "name or service not known" in bajo
            or "nodename nor servname" in bajo):
        return ("No se encuentra el servidor de la base de datos.",
                "Revisa el host en DATABASE_URL y tu conexión a internet. Si usas db.<id>.supabase.co (IPv6), cambia "
                "al Session pooler.")
    if "connection refused" in bajo:
        return ("El servidor rechazó la conexión (dirección o puerto incorrectos, o PostgreSQL apagado).",
                "Revisa host y puerto en DATABASE_URL: para Supabase, …pooler.supabase.com:5432.")
    if "timeout" in bajo or "timed out" in bajo:
        return ("La base de datos no respondió a tiempo.",
                "Revisa tu internet o firewall; en Supabase, Database → Network Restrictions no debe bloquear tu IP.")
    if "ssl" in bajo:
        return ("Problema con el cifrado (SSL) de la conexión.", "Para Supabase usa DB_SSLMODE=require.")
    if "max client" in bajo or "too many" in bajo or "remaining connection slots" in bajo:
        return ("Supabase no acepta más conexiones en este momento.",
                "Cierra otras ventanas de la plataforma o espera un minuto; revisa el uso en el panel de Supabase.")
    if "does not exist" in bajo and "database" in bajo:
        return ("La base indicada no existe.", "En Supabase la base se llama «postgres»: …:5432/postgres")
    if "project is paused" in bajo or "paused" in bajo:
        return ("El proyecto de Supabase está pausado (plan Free tras 1 semana sin uso).",
                "Reanúdalo en el panel de Supabase (Restore project) y espera unos minutos.")
    return ("No se pudo conectar a la base de datos.", msg.splitlines()[0][:300])
