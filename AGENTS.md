# Instrucciones para agentes de IA

Antes de cada tarea de la web lee `docs/MAESTRO_WEB.md` (o el PDF `MAESTRO_WEB_v1.0.pdf`) y cumple su sección 1
(reglas W-01 a W-24). Si la tarea toca la API de la app, la cola de IA o Cloudinary, lee también
`docs/MAESTRO_APP_MOVIL.md` (o `MAESTRO_APP_MOVIL_v2.0.pdf`), secciones 15 y 28.

Reglas que más se rompen:

- Sin CDN, npm ni frameworks de JavaScript: HTMX y Leaflet están en `web/static/web/vendor/` (W-01).
- Sin JavaScript en línea (`<script>` sin `src` u `onclick=`): el comportamiento va en `app.js`, `caso.js` o
  `mapa.js` (W-17). `web/tests/test_extras.py` lo comprueba.
- Toda vista de la web lleva `@web_view("permiso")` (W-07).
- La bandeja hace exactamente 6 consultas: no agregues consultas al `base.html` ni a los context processors.
- Los colores indican el estado de revisión, nunca la gravedad (W-12). La IA «sugiere indicios»: nunca diagnostica
  (W-11).
- Los números que van en atributos o en CSS se escriben sin localizar (`|pctnum`, `|stringformat`, W-16).
- `sembrar_demo` está prohibido en piloto (W-22).

Al terminar: `python manage.py check`, `python manage.py makemigrations --check --dry-run` y `python manage.py test`.
Después agrega el reporte de la sección 23.2 en `docs/REPORTE_AVANCE.md` (W-24).
