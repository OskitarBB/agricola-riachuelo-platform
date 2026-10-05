# Crea la tabla de caché (web_cache) dentro de `migrate` para que la alcance el post_migrate de seguridad (RLS).
from django.core.management import call_command
from django.db import migrations


def crear(apps, schema_editor):
    call_command("createcachetable", verbosity=0, database=schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0002_initial")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
