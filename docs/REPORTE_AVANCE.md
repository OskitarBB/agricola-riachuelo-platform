# Reporte de avance (Maestro Web §23.2)

**Tareas:** T-W00 a T-W19 (web completa) y API `/api/v1` de la app (Maestro App v2.0 §15) · **Fecha:** 05/10/2026
· **Avance estimado:** ~90 % (falta lo que depende de credenciales y datos reales, ver «Preguntas abiertas»).

## Qué hice

- **Modelo de datos completo** (Anexo B) en 8 apps: cuentas, campo, monitoreo, evidencias, ia, revisión,
  notificaciones y auditoría. Incluye migraciones, admin `/gestion/` (Anexo G.1) y, en Supabase, RLS en todas las
  tablas y REVOKE a `anon`/`authenticated` después de cada `migrate`.
- **API de la app** `/api/v1` (§15): registro, login con celular, refresh con rotación y lista negra, logout, perfil,
  cambio y pedido de contraseña, bootstrap de catálogos, sincronización idempotente (sesiones, pasadas,
  secuencias, incidencias), ticket firmado de Cloudinary y confirmación de fotos con verificación de firma.
  También acepta el formato multipart de la app actual (ADR-W-003). Los errores siguen `ApiErrorBody` con
  `traceId`. JWT y `X-Device-Id`; un celular revocado queda bloqueado en cualquier llamada.
- **Web de revisión** (Anexo D): ingreso con bloqueo por intentos, cambio de contraseña obligatorio, panel con
  indicadores, bandeja HTMX con refresco cada 15 s, caso con visor (zoom, arrastre, pellizco, pantalla completa,
  cajas de la IA, foto original), decisión y corrección con historial, mapa Leaflet, plano de hileras, sesiones con
  galería, reportes CSV, avisos, estado de la IA, usuarios, celulares, destinatarios y auditoría.
- **Diseño**: paleta de la app (verde y dorado), tipografía Inter local y logo de Agrícola Riachuelo. Incluye
  pantalla de carga al ingresar, barra de progreso, transiciones entre vistas (View Transitions), animaciones de
  entrada y contadores. También botones con onda y sonido (se pueden silenciar), avisos flotantes y diálogos de
  confirmación propios. Es responsive en PC (1440), tablet (1024) y celular (390): las tablas pasan a tarjetas y
  el menú a barra horizontal.
- **Actividad en vivo** (ADR-W-002): ingresos desde la app, cuentas nuevas, sesiones sincronizadas o cerradas,
  casos nuevos y decisiones. Aparecen en la campana, el panel y los avisos con sonido, y el contador de pendientes
  se actualiza.
- **worker_ia**: cola con `SELECT … FOR UPDATE SKIP LOCKED`, reintentos con espera y recuperación de tareas
  trabadas. Encola las fotos que quedaron sin tarea y recarga el detector si cambia el modelo activo. Hay tres
  detectores: `simulado`, `onnx` (YOLOv8/11 con NMS, o YOLO26/v10 end2end; con letterbox y recortes) y `yolo`
  (ultralytics). Los avisos de WhatsApp van por plantilla Cloud API o se imprimen en consola.
- **Errores por consola**: una línea por petición con `traceId` (LENTA si pasa 1,5 s), errores de la API con su
  código, errores del navegador reenviados al servidor, resumen al arrancar, chequeos de Django
  (`riachuelo.E00x/W00x`) y el comando `python manage.py diagnostico [--red]`.
- **Cloudinary simulado** para desarrollo (ADR-W-001) y **datos de demostración**: 3 lotes, 576 fotos, casos en
  todos los estados, avisos enviados y con error, y una tarea con error.
- **Arranque en Windows** con `iniciar.bat` (crea `.venv`, `.env` con clave, migra, carga la demo, revisa la
  configuración y abre el worker y la web), además de `scripts/iniciar.sh`.

## Archivos creados o modificados

Todo el repositorio, salvo `.gitignore` (actualizado). Lo principal: `config/`, las 8 apps de dominio, `api/`,
`web/` (vistas, plantillas, `static/web/{app.css, app.js, caso.js, mapa.js, iconos.svg, vendor/, sonidos/, img/,
fuentes/}`), `ia/inference/`, `simulador/`, `diagnostico/`, `docs/`, `scripts/`, `iniciar.bat`, `.env.example`,
`requirements*.txt`, `README.md`, `AGENTS.md` y `CLAUDE.md`.

## Migraciones

Iniciales en todas las apps, más `auditoria/0003_tabla_cache.py`, que crea la tabla de caché en la misma base.
`makemigrations --check` no detecta cambios.

## Pruebas

| Comando | Resultado |
|---|---|
| `python manage.py check` | sin observaciones |
| `python manage.py check --deploy` (configuración piloto) | solo `riachuelo.W005`: faltan los pesos del modelo |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `python manage.py test` en PostgreSQL 16 | **128 pruebas OK**: 66 de referencia del Anexo F + 30 de la API + 11 de IA/ONNX/worker + 6 del simulador + 15 extras |
| `python manage.py test` en SQLite | 128 OK (3 omitidas: RLS y concurrencia, solo PostgreSQL) |
| `medir_rendimiento` con 100 000 fotos sintéticas | bandeja 45–61 ms (6 consultas), caso 103 ms, mapa 268 ms con 5 000 puntos, plano 18 ms, panel 15 ms |

Las pruebas extras también verifican W-01 (sin recursos externos), W-17 (sin JavaScript en línea), que todos los
íconos usados existan en el sprite y que los estáticos referenciados existan.

## Capturas o evidencia

`docs/img/web/`: ingreso, panel, bandeja, caso (PC y celular), validación 422, atajos, mapa, plano, usuarios,
tablet y actividad en vivo. La sesión creada por la «app simulada» aparece en la web junto con su caso. También
se probó el flujo completo por HTTP contra la laptop: login → bootstrap → sesión → pasada → secuencia → ticket →
subida → confirmación → worker → caso → decisión → aviso.

## Supuestos (W-04)

1. **Acciones de auditoría nuevas**: `INGRESO_APP`, `CUENTA_REGISTRADA`, `SESION_RECIBIDA`, `SESION_CERRADA`,
   `PASADA_RECIBIDA`, `CAPTURA_CONFIRMADA` y `CONTRASENA_CAMBIADA_APP`. Alimentan la actividad en vivo.
2. **Código `NOT_FOUND`** (404) para `GET /captures/{id}` inexistente, que el contrato no define.
3. **Rutas nuevas**: `/actividad/` (permiso `dashboard.ver`), `/diagnostico/error-cliente/` (CSRF, máximo 30 por
   minuto por IP) y `/dev/…` (solo dev: Cloudinary simulado).
4. **Contraseña de las cuentas demo** `Demo2026`, igual a la del backend simulado de la app (el Anexo G decía
   `Demo2026!`).
5. **Subida multipart** de la app v1 aceptada de forma transitoria (ADR-W-003).
6. **Coordenadas, segmentos y marcadores del piloto son ficticios** hasta recibir los reales.
7. HSTS solo para el dominio de la plataforma: se silenciaron `security.W005` y `W021` porque otros subdominios
   del dominio de Hostinger pueden no tener HTTPS.
8. `MODEL_PATH` relativo se resuelve desde la carpeta del proyecto.

## Preguntas abiertas (lo que falta para el 100 %)

| Necesito | Para qué |
|---|---|
| `DATABASE_URL` de Supabase (Session pooler, puerto 5432) | Pasar de SQLite o PostgreSQL local a la base del piloto. `migrate` aplica RLS solo |
| `CLOUDINARY_URL` y crear las transformaciones `miniatura` y `revision` | Fotos reales firmadas (`diagnostico --red` las prueba) |
| WhatsApp Cloud API: token permanente, phone number ID, versión de Graph y plantilla `caso_confirmado` aprobada (6 parámetros) | Envío real de avisos |
| Pesos YOLO entrenados (`best.pt` o `.onnx`), clases en orden, `imgsz`, umbrales y si conviene recortes | Activar `IA_DETECTOR=onnx` |
| Contornos GeoJSON reales de los lotes y códigos reales de segmentos y marcadores | Mapa y plano exactos |
| Números de los destinatarios con consentimiento | Avisos del piloto |
| Datos del hosting (VPS o Python en Hostinger) | Despliegue con gunicorn y el worker como servicio |

## Riesgos o deuda

- La app debe migrar al ticket v2.0 antes del piloto con 3 celulares. En multipart cada foto (unos 4 MB) pasa por
  el servidor.
- Detector `yolo` (ultralytics) tiene licencia AGPL-3.0 (R-A6): se recomienda `onnx`.
- En SQLite la web y el worker comparten un archivo: sirve para la vista previa, no para el piloto.
- Los maestros (`MAESTRO_WEB.md` y `MAESTRO_APP_MOVIL.md`) deben copiarse a `docs/` desde el proyecto.

---

## Actualización 05/10/2026 — Arquitectura de datos y seguridad de la base

- **Qué hice.** Escribí `docs/ARQUITECTURA_DATOS.md`: qué va en Supabase, Cloudinary y el servidor; modelo de 38
  tablas con diagrama; correspondencia con el capítulo X del informe; integridad; seguridad en capas; casillas del
  panel de Supabase y de Cloudinary; capacidad medida; respaldo y retención. Además:
  - CHECK de estados y rangos en 17 modelos (`config/restricciones.py`, migraciones `0002_restricciones_check`);
  - trigger de auditoría de solo inserción (`auditoria/migrations/0004`);
  - revocaciones ampliadas a la Data API;
  - comandos `respaldo` y `mantenimiento`;
  - chequeos nuevos en `diagnostico` (TLS, trigger, CHECK, espacio).
  - ADR-W-004.
- **Migraciones.** `0002_restricciones_check` en cuentas, campo, monitoreo, evidencias, ia, revision y
  notificaciones, y `auditoria/0004_auditoria_solo_insercion`.
- **Pruebas.** 131 OK en PostgreSQL y 131 OK en SQLite (5 omitidas, solo para PostgreSQL). Se verificó que el
  respaldo de `respaldo` se restaura con `pg_restore` y conserva datos y trigger. Con 100 000 fotos la base mide
  unos 103 MB.
- **Supuestos.** El usuario de conexión sigue siendo el dueño de las tablas (`postgres`, Maestro §28.4). Un rol
  dedicado queda como mejora futura. La vía de mantenimiento de la auditoría solo la usa `sembrar_demo` en dev.
- **Pendiente recordado.** Pasar el detector de `simulado` a `onnx` cuando llegue el modelo YOLO entrenado (pesos,
  clases, `imgsz`, umbrales). Los pasos están en `ia/inference/weights/LEEME.md`.


---

## Actualización 05/10/2026 — Alta de cuentas desde la web y tipos de cuenta (ADR-W-005)

- **Qué hice.** En **Administración → Usuarios** agregué «Nueva cuenta»: el administrador crea cuentas activas con
  contraseña temporal (se muestra una vez, con botón «Copiar») y cambio obligatorio al primer ingreso. Primero se
  elige el tipo: **Plataforma web** (especialista, supervisor y/o administrador) o **App móvil** (operador de
  campo). Se agregó la tarjeta «Reglas de las cuentas». Las reglas se aplican en el servidor
  (`cuentas.services.validate_roles`): «Operador de campo» va solo y no se combina con roles de la web, también al
  aprobar solicitudes y al cambiar roles. El login explica cómo se obtiene una cuenta. La pantalla de cambio de
  contraseña rotula «Contraseña temporal» cuando corresponde. Django Admin ya no crea usuarios (W-03).
- **Archivos.** `cuentas/services.py` (`validate_roles`, `account_kind`, `create_account`,
  `_generate_temporary_password`), `cuentas/validators.py` (`PHONE_RE` compartido), `cuentas/admin.py`,
  `api/v1/serializers.py` (usa `PHONE_RE`), `web/forms.py` (`NuevaCuentaForm`), `web/views.py`
  (`usuario_nuevo`), `web/urls.py`, `web/messages.py`, `web/templates/web/usuarios.html`, `login.html`,
  `cambiar_contrasena.html`, `web/static/web/app.js`, `app.css`, pruebas y `docs/adr/ADR-W-005`.
- **Migraciones.** Ninguna (usa `users`, `user_roles` y `audit_events`).
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios y **149 pruebas OK** en PostgreSQL
  (16 nuevas: alta web y app, roles mezclados, correo repetido o pendiente, permisos, primer ingreso con la temporal,
  Django Admin). Revisión en navegador a 1440 px y 390 px sin errores de consola.
- **Supuestos (W-04).** Ruta `/administracion/usuarios/nueva/`, acción de auditoría `CUENTA_CREADA` y textos nuevos
  definidos en esta entrega a pedido del equipo; deben pasar al Maestro Web en su próxima versión.
- **Preguntas abiertas.** ¿El aviso de privacidad debe aceptarse también en la web para las cuentas creadas por el
  administrador? (En la app se acepta al registrarse.)

---

## Actualización 07/10/2026 — Gestión de catálogos desde la web (ADR-W-006)

- **Qué hice.** Nueva sección **Administración → Catálogos** para administrador y supervisor (permiso
  `catalogos.gestionar`):
  - lotes con conteos, alta y edición;
  - hileras en bloque con segmento de hilera completa y marcadores de inicio y fin;
  - «Completar hileras sin segmento»;
  - por hilera: plantas, segmentos (alta, edición en línea, «Dividir en segmentos» con vista previa) y marcadores
    (alta y edición, posición, segmento, coordenadas opcionales);
  - desactivar y reactivar en cascada; nunca se borra.
  Reglas en `campo/services.py` (IDs generados y no reutilizados, rangos, solapes, códigos únicos, auditoría). El
  bootstrap de la app filtra segmentos y marcadores inactivos; el plano dibuja solo segmentos activos y conserva el
  conteo de casos; Django Admin ya no borra catálogos.
- **Archivos.** `campo/models.py`, `campo/migrations/0003_catalogo_activo.py`, `campo/services.py` (nuevo),
  `campo/admin.py`, `campo/tests/test_catalogos.py` (nuevo), `api/v1/views.py` (bootstrap), `api/tests/test_api.py`,
  `web/permissions.py`, `web/forms.py`, `web/views.py`, `web/urls.py`, `web/queries.py`, `web/messages.py`,
  `web/templates/web/base.html`, `catalogos.html`, `catalogo_lote.html`, `catalogo_hilera.html`,
  `web/static/web/app.js`, `app.css`, `web/tests/test_views.py`, `docs/adr/ADR-W-006`, `docs/INTEGRACION_APP.md`.
- **Migraciones.** `campo/0003_catalogo_activo` (dos columnas `active` con valor por defecto true; sin tablas nuevas).
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **170 pruebas OK** en PostgreSQL y en
  SQLite (21 nuevas: IDs y choques con inactivos, alta en bloque, validaciones, división, cascadas, auditoría,
  bootstrap sin inactivos y con `catalogVersion` nuevo, sincronización con catálogo desactivado, permisos, plano,
  Django Admin). La bandeja sigue en 6 consultas. Revisión en navegador a 1440 px y 390 px, sin errores de consola
  ni desplazamiento horizontal.
- **Decisiones del equipo (sección 10 del traspaso).** Editan administrador y supervisor; el contorno del lote sigue
  en `/gestion/`; la importación CSV queda para cuando lleguen los marcadores reales.
- **Supuestos (W-04).** Códigos automáticos: segmento completo «Hxx completa», marcadores «Hxx inicio» y «Hxx fin»;
  al dividir, «Hxx S{i}», «Hxx S{i} inicio» (INICIO el primero, INTERMEDIO los demás) y «Hxx fin».

---

## Actualización 08/10/2026 — Herramientas para entrenar y activar el modelo YOLO

- **Qué hice.** Herramientas para pasar de fotos etiquetadas a un `modelo.onnx` listo para el worker, sin cambiar el
  contrato del worker ni la base:
  - `tools/ia/entrenar_yolo_colab.ipynb`: entrenamiento en Google Colab (GPU T4) con datos en Google Drive, reanuda
    si Colab se desconecta, exporta a ONNX y verifica.
  - `tools/ia/cortar_mosaicos.py`: junta datasets propios y públicos, renombra clases, divide train/val/test por
    grupo (secuencia) y corta recortes de 1280 px con la misma rejilla del worker (`ia.inference.onnx.tiles`).
  - `tools/ia/verificar_onnx.py`: analiza fotos completas con `DetectorOnnx.analizar_imagen` (el mismo código del
    worker), mide aciertos por foto y por caja, barre umbrales, mide tiempos e imprime la configuración para
    `/gestion/` con el sha256.
  - `python manage.py exportar_dataset --modo fotos|revisados`: baja fotos del piloto (orientadas, sin EXIF) para
    etiquetar y, en modo revisados, convierte las decisiones del especialista en etiquetas (confirmado → cajas de la
    IA menos las rechazadas; confirmado sin cajas → foto sin etiqueta para dibujarla; descartado → negativa). Solo
    lectura.
  - `ia/inference/onnx.py`: `analyze()` ahora delega en `analizar_imagen(img)` (mismo comportamiento) para que la
    verificación fuera del servidor use exactamente el código de producción.
- **Archivos.** `ia/inference/onnx.py`, `ia/management/commands/exportar_dataset.py` (nuevo),
  `ia/tests/test_exportar_dataset.py` (nuevo), `tools/ia/` (nuevo: LEEME.md, cortar_mosaicos.py, verificar_onnx.py,
  entrenar_yolo_colab.ipynb).
- **Migraciones.** Ninguna.
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **174 pruebas OK** (4 nuevas). Verificado
  con Ultralytics 8.4: YOLO26n exportado a ONNX con salida cruda (1, 84, 8400) da las mismas cajas que Ultralytics
  (±4 px); la salida sin NMS (1, 300, 6) también se lee. Un modelo de 2 clases entrenado con datos sintéticos pasó
  por cortar_mosaicos → entrenamiento → ONNX → verificar_onnx con 12 recortes por foto de 4000 × 3000 (unos 0,75 s
  por foto en 2 núcleos).
- **Dependencias (W-21).** Ninguna nueva en la plataforma. Ultralytics, onnx y onnxslim solo se instalan en Colab
  (entrenamiento); el worker sigue con onnxruntime y numpy.
- **Supuestos (W-04).** Clases de la v1: `chanchito_blanco`, `melaza_fumagina` (en ese orden). Tiling de producción
  `{"tile": 1280, "overlap": 0.2}`.

---

## Actualización 08/10/2026 (tarde) — v1.3: cuentas, alertas automáticas de la IA, mapa satelital y «Ubicar plaga» (ADR-W-007)

- **Qué hice.**
  - **Usuarios → Editar** (solo administrador): nombre, correo de ingreso, celular, código y asignar contraseña
    (con «cambiarla al ingresar»). Cambiar correo o contraseña cierra la sesión de la app. En `/gestion/` esos campos
    quedan de solo lectura.
  - **Alertas**: estados `CONFIRMADO_POR_IA` (la IA confirma sola si alguna caja alcanza el umbral del modelo y se
    avisa por WhatsApp sin esperar al especialista) y `POSIBLE_PLAGA` (decisión del especialista, sin WhatsApp).
    Umbral `auto_confirm_threshold` por modelo en `/gestion/` → Modelos de IA, **vacío = apagado**. La bandeja abre
    en «Por revisar» (pendientes + confirmados por IA); panel, tablero, plano, mapa y atajos (P) actualizados.
  - **Mapa satelital** del fundo (Esri World Imagery + nombres, OSM como alternativa), centrado en
    14°01'40.1"S 75°41'57.2"W: lotes sombreados con área y perímetro, hileras, puntos con nombre, medir distancias y
    distancia entre lotes. Administrador y supervisor dibujan contornos, marcan inicio y fin de hileras (pasa sola a
    la siguiente) y colocan puntos.
  - **API** `GET /api/v1/mobile/pest-reports` para «Ubicar plaga» y acceso del especialista a la app solo para eso
    (las rutas de monitoreo le responden 403).
- **Archivos.** `cuentas/services.py`, `cuentas/models.py`, `cuentas/admin.py`, `cuentas/tests/test_editar_cuentas.py`
  (nuevo), `revision/models.py`, `revision/services.py`, `revision/tests/test_alertas_ia.py` (nuevo), `ia/models.py`,
  `notificaciones/models.py`, `notificaciones/services.py`, `notificaciones/whatsapp.py`, `campo/models.py`,
  `campo/services.py`, `campo/tests/test_mapa_satelital.py` (nuevo), `api/permissions.py` (nuevo), `api/v1/views.py`,
  `api/v1/urls.py`, `api/tests/test_ubicar_plaga.py` (nuevo), `web/views.py`, `web/urls.py`, `web/forms.py`,
  `web/queries.py`, `web/messages.py`, `web/templatetags/web_tags.py`, plantillas `usuario_editar.html` (nueva),
  `usuarios.html`, `mapa.html`, `dashboard.html`, `plano.html`, `partials/panel_decision.html`, `web/static/web/mapa.js`,
  `caso.js`, `app.css`, `config/settings.py`, `.env.example`, `deploy/env.piloto.plantilla`, `docs/adr/ADR-W-007`,
  `docs/INTEGRACION_APP.md`.
- **Migraciones.** `campo/0004_puntos_del_fundo` (tabla `points_of_interest`), `ia/0003_umbral_auto_y_estados_v13`
  (columna `auto_confirm_threshold`, CHECK), `revision/0003_estados_ia_y_posible_plaga` y
  `notificaciones/0003_aviso_confirmado_por_ia` (`review` nulo, tipo de aviso nuevo, CHECK actualizados).
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **203 pruebas OK** (29 nuevas). La bandeja
  sigue en 6 consultas. Probado en navegador (Playwright, 1440 px y 390 px): dibujar contorno, marcar hilera con paso
  automático a la siguiente, colocar punto, medir y distancia entre lotes, sin errores de JavaScript ni desplazamiento
  horizontal (las teselas no cargan en el entorno de prueba por no tener internet).
- **Dependencias (W-21).** Ninguna nueva. Teselas externas: Esri World Imagery (sin clave, con atribución).
- **Supuestos (W-04).** Alertas visibles en la app: confirmados (IA y especialista), posibles plagas y casos en
  revisión; «Posible plaga» no envía WhatsApp; el supervisor sigue sin app.


## v1.3.1 — 09/10/2026 · Triage de la IA, limpieza de fotos y miniaturas (ADR-W-008)

- **Qué se hizo.**
  - **Miniaturas**: las URLs firmadas llevan el tamaño en la propia URL (`c_limit,w_400,q_auto` y `w_1600`); ya no
    dependen de las transformaciones con nombre de Cloudinary (las de antes respondían 400 y quedaron en la caché).
  - **Triage en tres franjas**: `model_configs.review_threshold` (nuevo) y `auto_confirm_threshold`. Debajo del umbral
    de revisión la tarea queda `DESCARTADO_POR_IA` y no se abre caso; en medio, el especialista; desde el umbral
    automático, «Confirmado por IA». Comando `python manage.py aplicar_triage --revision 0.50 --auto 0.85 [--simular]`.
  - **Limpieza de fotos** (solo administrador): «Eliminar sesión» en Sesiones y Administración → Limpieza de fotos
    (descartadas por la IA de más de N días). Borra base, Cloudinary (con reintento del worker) y avisa a los
    celulares por `GET /api/v1/mobile/deleted-captures`; lo borrado responde 410 si un celular intenta subirlo.
  - **Avisos**: con WhatsApp en modo consola se ve «Simulado (no enviado)».
- **Migraciones.** `ia/0004_triage_tres_franjas` (columna `review_threshold`, estado `DESCARTADO_POR_IA`, CHECK) y
  `evidencias/0003_fotos_eliminadas` (tablas `deleted_captures` y `deleted_sessions`).
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **223 pruebas OK** (20 nuevas). Con la app
  0.5.1: jest 144, simulado 9/9, red local 9/9, integración 32/32 (2 pasos nuevos de limpieza).
- **Cambio de regla.** R-11 / RN-09: la evidencia se puede borrar solo con la limpieza del administrador (ADR-W-008).


## v1.3.2 — 09/10/2026 · Página «Descartadas por la IA»

- **Qué se hizo.** Las fotos que la IA descarta (indicio débil bajo el umbral de revisión, o sin indicios) ya se ven
  en la web: Casos → pestaña **«Descartadas por la IA»** (`/casos/descartadas-ia/`, permiso `bandeja.ver`). Una fila
  por foto sin caso, con miniatura, resultado, ubicación, fecha y confianza máxima; filtros por resultado, lote, fechas
  y orden. Al abrir la foto se ve la confianza frente al umbral de revisión y el botón «Abrir caso para revisión» para
  rescatar un falso negativo (la foto sale de la lista al tener caso). Los contadores «Sin indicios» y «Descartado por
  la IA» del panel enlazan a la lista filtrada. La bandeja principal muestra debajo de los casos la franja
  **«Descartadas por la IA»** (total y últimas 8 miniaturas, con los filtros de lote y fechas), cargada aparte con HTMX
  para que la bandeja siga en 6 consultas; y el filtro «Estado» tiene la opción «Descartadas por la IA».
- **Migraciones.** Ninguna. **API de la app.** Sin cambios: «Ubicar plaga» sigue mostrando solo confirmados,
  posibles plagas y casos en revisión.
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **231 pruebas OK** (8 nuevas). La bandeja
  sigue en 6 consultas.


## v1.3.3 — 09/10/2026 · La IA decide por lugar con las dos cámaras (ADR-W-009)

- **Qué se hizo.** Las dos fotos de una secuencia (mismo lugar) se deciden juntas con la regla «basta una cámara»:
  un solo caso por lugar, anclado en la foto de mayor confianza; si la otra cámara llega después y ve más, pasa a ser
  la principal y puede confirmar el caso. Las dos bajas → el lugar se descarta. Una sola foto → tres franjas como
  antes. La foto de la otra cámara no sale sola en «Descartadas por la IA», no la borra la limpieza y su página lleva
  al caso del lugar; el caso muestra qué vio la IA en la otra cámara. `aplicar_triage` une los casos pendientes
  duplicados de un mismo lugar.
- **Migraciones.** Ninguna. **App.** Sin cambios.
- **Pruebas.** `check` sin problemas, `makemigrations --check` sin cambios, **239 pruebas OK** (8 nuevas).
