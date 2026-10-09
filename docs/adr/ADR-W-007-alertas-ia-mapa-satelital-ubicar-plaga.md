# ADR-W-007 — Alertas automáticas de la IA, mapa satelital, «Ubicar plaga» y edición de cuentas (web v1.3)

08/10/2026 · Estado: aceptada (pedido de Oscar, PM del equipo) · Autor: Claude (asistente de desarrollo)

**Contexto.** Con la plataforma y el worker de IA en producción, el equipo pidió: (1) que solo el administrador
corrija los datos de ingreso de las cuentas; (2) que la IA no dependa siempre del especialista: si está segura,
avisar de inmediato; si no, que el especialista decida, incluso dejando el caso como «posible plaga» para que el
encargado vaya a verlo; (3) un mapa satelital tipo Google Earth donde dibujar lotes, hileras y puntos; (4) que en la
app el operador o el especialista vean las alertas en un mapa y se dejen guiar hasta el lugar. Hasta la v1.2 regían
RN-W03/RN-W07 (sin decisión humana no hay aviso) y la regla 28.10 del maestro móvil (la API nunca devuelve a la app
URLs de fotos ni resultados de la IA).

**Decisión.**

1. **Cuentas.** Usuarios → «Editar» (`/administracion/usuarios/<id>/editar/`, permiso `usuarios.gestionar`): nombre,
   correo (usuario de ingreso), celular, código y asignar una contraseña concreta (con «cambiarla al ingresar»).
   Servicios `cuentas.update_account` y `cuentas.set_password_by_admin` (solo ADMINISTRADOR, auditados como
   `CUENTA_EDITADA` y `CONTRASENA_ASIGNADA`, nunca con la contraseña). Cambiar el correo o la contraseña cierra la
   sesión de la app (lista negra de refresh). En `/gestion/` esos campos pasan a solo lectura.
2. **Estados nuevos del caso** (migraciones `revision/0003`, `ia/0003`, `notificaciones/0003`):
   * `CONFIRMADO_POR_IA`: el worker lo pone al abrir el caso si alguna caja alcanza
     `model_configs.auto_confirm_threshold` (campo nuevo, **vacío = apagado**). Se encolan avisos de WhatsApp sin
     decisión humana (`notifications.review` nulo, `kind = CASO_CONFIRMADO_IA`, plantilla `WHATSAPP_TEMPLATE_IA`,
     por defecto la misma). Auditoría `CASO_CONFIRMADO_POR_IA` con confianza, umbral y versión del modelo.
   * `POSIBLE_PLAGA`: decisión nueva del especialista (sin aviso de WhatsApp, observación opcional, tecla **P**).
   * El especialista sigue decidiendo los `CONFIRMADO_POR_IA` («Decidir»): confirmar no duplica avisos; descartar o
     posible anula los avisos pendientes (lo enviado no se retira, Q-W07). La bandeja abre por defecto en
     «Por revisar» (pendientes + confirmados por IA).
   * RN-W03 queda: avisan `CONFIRMADO_POR_ESPECIALISTA` y `CONFIRMADO_POR_IA`. Colores nuevos (estado, no gravedad,
     W-12): confirmado por IA fucsia `#c11574`, posible plaga naranja `#ef6820`.
3. **Mapa satelital** (`/mapa/`): fondo Esri World Imagery con nombres y vías (sin clave; atribución visible) y
   OpenStreetMap; centro por defecto en el fundo (14°01'40.1"S 75°41'57.2"W). Lotes sombreados con área y perímetro,
   hileras como línea entre sus marcadores de inicio y fin, puntos con nombre (tabla nueva `points_of_interest`,
   migración `campo/0004`), medir distancias y distancia más corta entre lotes. Administrador y supervisor
   (`catalogos.gestionar`) dibujan el contorno de los lotes, marcan inicio y fin de cada hilera (crea los marcadores
   si faltan; pasa sola a la siguiente hilera) y colocan o eliminan puntos: `POST /mapa/editar/` (JSON + CSRF),
   servicios en `campo/services.py`, auditados. Sin bibliotecas nuevas (W-01): todo en `mapa.js` sobre Leaflet.
4. **API para «Ubicar plaga»**: `GET /api/v1/mobile/pest-reports?days=30` (máx. 90). Devuelve los casos
   `CONFIRMADO_POR_IA`, `CONFIRMADO_POR_ESPECIALISTA`, `POSIBLE_PLAGA` y `PENDIENTE_REVISION` (no descartados ni
   evidencia insuficiente) con lote, hilera, lateral, segmento, marcador, coordenadas y fuente, clase, observación y
   **miniatura firmada**, más las capas del fundo. **Excepción explícita a 28.10**, solo lectura.
5. **Especialista en la app**: `MOBILE_ROLES` incluye ESPECIALISTA_FITOSANITARIO para ingresar, pero las rutas de
   monitoreo y sincronización exigen `MOBILE_FIELD_ROLES` (operador y administrador) con `api.permissions.FieldWork`:
   el especialista recibe 403 `ROLE_NOT_ALLOWED` ahí. El supervisor sigue solo en la web.

**Consecuencias.** Más avisos y más rápido, con riesgo de falsas alarmas si el umbral se activa con un modelo poco
validado: por eso nace apagado y se activa por modelo en `/gestion/` solo con `tools/ia/verificar_onnx.py` sobre fotos
del fundo. La app necesita una versión nueva para «Ubicar plaga» (ADR 0009 de la app). Las imágenes satelitales
dependen de internet y de los términos de Esri (uso con atribución).
