# ADR-W-004 — Integridad y seguridad garantizadas por la base de datos

05/10/2026 · Estado: aceptada · Autor: Claude (asistente de desarrollo)

**Contexto.** El informe (cap. X §10.7 y XII §12.1) pide CHECK de estados controlados, una auditoría inalterable y
que la base esté aislada. En el Anexo B los estados son `TextChoices`, que Django solo valida en formularios. La
regla «la auditoría solo se inserta» la cumplían únicamente los servicios. Con Supabase, el panel permite editar
filas a mano.

**Decisión.**

1. `config/restricciones.py` agrega a 17 modelos un **CHECK por cada campo con estados** y por los rangos físicos
   (lat, lon, precisión GPS, confianza). Es un decorador que lee las opciones del propio campo, así que nunca se
   desincronizan. Viaja en las migraciones `0002_restricciones_check` y funciona en PostgreSQL y SQLite.
2. `auditoria/migrations/0004` instala en PostgreSQL un **trigger que rechaza UPDATE y DELETE** sobre
   `audit_events`. Solo permite poner `user_id` en NULL (on_delete=SET_NULL). Hay una vía de mantenimiento
   (`SET LOCAL riachuelo.auditoria_mantenimiento = 'on'`) que solo usa `sembrar_demo` en dev.
3. `auditoria/seguridad_bd.py` revoca además funciones, el uso del esquema `public` y los privilegios por defecto
   de secuencias y funciones a `anon` y `authenticated`.
4. Nuevos comandos `respaldo` (pg_dump) y `mantenimiento` (sesiones, tokens y caché vencidos), y nuevos chequeos de
   `diagnostico`: TLS, trigger, CHECK y espacio usado contra `DB_LIMITE_MB`.

**Alternativas.** Validar solo en Python (no protege del panel ni de errores futuros). Poner CHECK escritos a mano
por modelo (se desincronizan con las opciones). Políticas RLS con roles de base (innecesarias: nadie más que Django
se conecta).

**Consecuencias.** Un estado nuevo en un `TextChoices` requiere `makemigrations`, que lo detecta solo. Editar la
auditoría desde el panel ya no es posible sin la vía de mantenimiento. El administrador de la base sigue pudiendo
quitar el trigger: protege de errores y ediciones accidentales, no de quien tiene la contraseña.

**Secciones afectadas.** Maestro Web, Anexo B (restricciones adicionales); Maestro App §28.4 (seguridad);
`docs/ARQUITECTURA_DATOS.md`.
