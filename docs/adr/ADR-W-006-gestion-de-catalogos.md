# ADR-W-006 — Gestión de catálogos del fundo desde la web

07/10/2026 · Estado: aceptada (pedido del equipo; traspaso `HANDOFF_CATALOGOS_WEB.md`) · Autor: Claude (asistente de desarrollo)

**Contexto.** Para iniciar una pasada, la app necesita lote → hilera → segmento → marcador de inicio. En el piloto
solo había lotes e hileras, y los catálogos solo se editaban en `/gestion/` (Django Admin), uno por uno y con la
opción de borrar. El 07/10 hubo que crear 83 segmentos «hilera completa» con un script por SSH. Borrar un marcador
o segmento pone en NULL la ubicación de pasadas y secuencias ya registradas, y un celular sin internet con el
catálogo descargado no podría sincronizar si un ID desaparece.

**Decisión.**

1. Nueva pantalla **Administración → Catálogos** (`/administracion/catalogos/`, lote y hilera), con el permiso
   nuevo `catalogos.gestionar` para **administrador y supervisor**. Altas en bloque de hileras (con segmento de
   hilera completa y marcadores de inicio y fin), «Completar hileras sin segmento», «Dividir en segmentos» (N partes
   o cada K plantas, con vista previa), alta y edición de segmentos y marcadores.
2. **«Eliminar» = desactivar.** `FieldSegment.active` y `Marker.active` (migración `campo/0003_catalogo_activo`,
   solo `ADD COLUMN … DEFAULT true`). Desactivar un segmento desactiva sus marcadores; lote e hilera ocultan lo de
   adentro sin tocarlo, para poder reactivar. Reactivar exige que el padre esté activo.
3. **IDs generados en el servidor, inmutables y sin reutilizar** (también contra los inactivos): lote desde el
   código (`SWG 1` → `SWG1`, sufijo `-2`…), hilera `{lote}-H{nn}`, segmento `{hilera}-S{k}`, marcadores
   `{hilera}-INI`/`-FIN` para la hilera completa y `{hilera}-M{k}` el resto. Conviven con los creados por el script.
   El número y el lote de una hilera no se editan.
4. Reglas en `campo/services.py` (atómicas y auditadas: `CATALOGO_CREADO`, `CATALOGO_EDITADO`,
   `CATALOGO_DESACTIVADO`, `CATALOGO_REACTIVADO`, `CATALOGO_LOTE_HILERAS`): rangos `1 ≤ inicio ≤ fin ≤ plantas`,
   sin solape entre segmentos activos, códigos únicos entre los activos de la hilera, no bajar las plantas por
   debajo de un segmento activo, lat/lon juntas y en rango. Aviso (no bloqueo) si hay sesiones sin cerrar en la zona.
5. `GET /api/v1/mobile/bootstrap` devuelve solo segmentos y marcadores activos y les agrega `"active": true`
   (campo nuevo, compatible). La sincronización (`monitoreo/services.py`) no se tocó: sigue aceptando IDs
   desactivados. El plano dibuja solo segmentos activos y sigue contando los casos de los desactivados.
6. Django Admin deja de borrar catálogos y muestra el ID como solo lectura al editar (W-03).

**Alternativas.** Seguir en Django Admin (sin reglas ni acciones en bloque, y con borrado). Borrado lógico con fecha
(`deleted_at`): más complejo sin beneficio para el piloto. Permitir editar el número de hilera (rompe el ID).

**Consecuencias.** Una migración aditiva. RN-W08 se precisa: los catálogos sí se administran desde la web (no son
datos de campo). Queda para después: editar el contorno del lote (sigue en `/gestion/`) y la importación por CSV.
Las rutas, el permiso, las acciones de auditoría y los mensajes nuevos deben pasar al Maestro Web en su próxima
versión (§6.3, §7.2, §9 y Anexo D.5).
