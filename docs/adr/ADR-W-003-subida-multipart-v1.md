# ADR-W-003 — Aceptar la subida multipart de la app actual (v1) además del ticket v2.0

05/10/2026 · Estado: aceptada (transitoria) · Autor: Claude (asistente de desarrollo)

**Contexto.** El Maestro App v2.0 define que la app sube la foto directo a Cloudinary con un ticket firmado. La app
del repositorio (`src/api/syncApi.ts`) todavía envía `file` + `metadata` por multipart a `POST /captures/upload`.
Ese cambio corresponde a la Fase 4.

**Decisión.** `POST /captures/upload` atiende los dos formatos según el `Content-Type`. Con **JSON** sigue el flujo
v2.0. Con **multipart** valida la metadata y el md5 y sube la foto a Cloudinary desde el servidor con los mismos
parámetros del ticket. Luego confirma por el mismo servicio, con la misma verificación de firma, transacción y cola
de IA. Se desactiva con `API_SUBIDA_MULTIPART=false`.

**Alternativas.** Exigir primero el cambio de la app (bloquea la integración) o un endpoint aparte (rompe el
contrato que la app ya usa).

**Consecuencias.** La app actual se conecta sin cambios. En multipart la foto pasa por el servidor, lo que
consume más ancho de banda que la v2.0. Conviene migrar la app al ticket antes del piloto con 3 celulares.

**Secciones afectadas.** Maestro App §15.7 (compatibilidad hacia atrás, sin cambiar la v2.0).
