# auditoria/migrations/0004_auditoria_solo_insercion.py — audit_events es de solo inserción (Maestro Web, Anexo B:
# «Solo se inserta; nunca se edita ni se borra»), también a nivel de base de datos (PostgreSQL/Supabase).
#
# Un trigger rechaza UPDATE y DELETE. Única excepción: poner user_id en NULL sin tocar nada más, que es lo que hace
# Django (on_delete=SET_NULL) si alguna vez se elimina una cuenta; el evento se conserva. Para tareas de desarrollo
# (sembrar_demo ajusta las horas de la demostración) se habilita la edición solo dentro de una transacción con
# SET LOCAL riachuelo.auditoria_mantenimiento = 'on'. TRUNCATE no se bloquea (manage.py flush, pruebas).
# En SQLite (vista previa local) no se instala: la regla la cumplen los servicios, que solo hacen INSERT.
from django.db import migrations

CREAR = """
CREATE OR REPLACE FUNCTION public.riachuelo_auditoria_inmutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF current_setting('riachuelo.auditoria_mantenimiento', true) = 'on' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.user_id IS NULL
       AND (NEW.id, NEW.entity_type, NEW.entity_id, NEW.action, NEW.timestamp, NEW.before, NEW.after, NEW.trace_id)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.entity_type, OLD.entity_id, OLD.action, OLD.timestamp, OLD.before, OLD.after, OLD.trace_id) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_events es de solo inserción: % no permitido', TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'La auditoría no se edita ni se borra (Maestro Web, Anexo B).';
END;
$$;
REVOKE ALL ON FUNCTION public.riachuelo_auditoria_inmutable() FROM PUBLIC;
DROP TRIGGER IF EXISTS audit_events_solo_insercion ON public.audit_events;
CREATE TRIGGER audit_events_solo_insercion BEFORE UPDATE OR DELETE ON public.audit_events
    FOR EACH ROW EXECUTE FUNCTION public.riachuelo_auditoria_inmutable();
"""

QUITAR = """
DROP TRIGGER IF EXISTS audit_events_solo_insercion ON public.audit_events;
DROP FUNCTION IF EXISTS public.riachuelo_auditoria_inmutable();
"""


def instalar(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREAR, params=None)


def desinstalar(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(QUITAR, params=None)


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0003_tabla_cache")]
    operations = [migrations.RunPython(instalar, desinstalar)]
