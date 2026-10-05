# ADR-W-002 — Actividad en vivo en la web (ingresos, cuentas, sesiones y casos)

05/10/2026 · Estado: aceptada · Autor: Claude (asistente de desarrollo)

**Contexto.** Se pidió que la web muestre cada ingreso y cada sesión nueva que llega de la app. El Maestro Web no
usa WebSockets ni servicios extra: el patrón de refresco es el sondeo HTMX (P-2).

**Decisión.** La API registra en auditoría `INGRESO_APP`, `CUENTA_REGISTRADA`, `SESION_RECIBIDA` y
`SESION_CERRADA`, además de las acciones del Maestro. `GET /actividad/` (permiso `dashboard.ver`) devuelve un
fragmento que se reemplaza a sí mismo cada 20 s (`WEB_ACTIVIDAD_POLL_SECONDS`), solo con la pestaña visible.
Trae los eventos con id mayor al último visto y el total de casos pendientes. `app.js` los muestra en la campana,
en el panel y como avisos flotantes con sonido. Los eventos de cuentas solo los ven los administradores.

**Alternativas.** WebSockets o Server-Sent Events (necesitan ASGI y otro proceso, fuera de W-01/W-05). También se
evaluó sondear la tabla de casos, pero así no se verían los ingresos ni las sesiones.

**Consecuencias.** Hay una consulta liviana cada 20 s por pestaña abierta, que la consola no registra salvo
errores. La bandeja sigue en 6 consultas porque el sondeo no toca `base.html`.

**Secciones afectadas.** Maestro Web §7 (nueva ruta `actividad`), §16 (acciones de auditoría nuevas) y §12 (P-2).
