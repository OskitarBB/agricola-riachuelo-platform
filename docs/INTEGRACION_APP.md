# Integración con la app móvil (`agricola-riachuelo-mobile`)

Contrato `/api/v1` del Maestro App Móvil v2.0, §15. JSON en camelCase, fechas ISO-8601 UTC y rutas sin barra
final (también se acepta con barra). Esquema OpenAPI: `GET /api/v1/schema`.

## 1. Configurar la app

```
EXPO_PUBLIC_API_URL=http://192.168.1.50:8000   # IP de la laptop (la imprime runserver); en piloto https://dominio
EXPO_PUBLIC_USE_MOCK_API=0
```

La laptop se inicia con `iniciar.bat` (o `python manage.py runserver 0.0.0.0:8000`). Laptop y celulares deben
estar en la misma red Wi-Fi.

## 2. Cabeceras y errores

- `Authorization: Bearer <accessToken>` en todo, salvo `health`, `auth/register`, `auth/login`, `auth/refresh`,
  `auth/logout` y `auth/password-reset-requests`.
- `X-Device-Id: <uuid del celular>` en todas las llamadas. Un celular revocado en la web recibe
  `403 DEVICE_REVOKED`, y un token usado desde otro celular recibe `401 TOKEN_EXPIRED`.
- Todo error tiene la forma `{ "code", "message", "fieldErrors"?: [{field, message}], "traceId" }`. Ese
  `traceId` es el mismo que imprime la consola del servidor.

| HTTP | Códigos |
|---|---|
| 400 | `VALIDATION_ERROR`, `PASSWORD_POLICY` |
| 401 | `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `REFRESH_INVALID` |
| 403 | `ACCOUNT_PENDING`, `ACCOUNT_REJECTED`, `ACCOUNT_BLOCKED`, `ROLE_NOT_ALLOWED`, `DEVICE_REVOKED` |
| 404 | `SESSION_NOT_FOUND`, `PASS_NOT_FOUND`, `SEQUENCE_NOT_FOUND`, `NOT_FOUND` (*supuesto*: `GET /captures/{id}`) |
| 409 | `EMAIL_ALREADY_REGISTERED`, `CAPTURE_CONFLICT`, `UPLOAD_MISMATCH` |
| 413 | `PAYLOAD_TOO_LARGE` |
| 422 | `UPLOAD_SIGNATURE_INVALID` |
| 429 | `TOO_MANY_ATTEMPTS` (login: 5 fallos → 15 min; además 10 por minuto por IP) |
| 500 / 502 | `INTERNAL_ERROR` (la app reintenta) |

## 3. Endpoints

| Método y ruta | Respuesta |
|---|---|
| `GET /health` | `{status:"UP", serverTime}` (503 si no hay base de datos) |
| `POST /auth/register` | 201 `{userId, status:"PENDIENTE_APROBACION"}`. La cuenta aparece **en vivo** en la web y el administrador la aprueba en *Usuarios* |
| `POST /auth/login` | `{accessToken, accessTokenExpiresAt, refreshToken, refreshTokenExpiresAt, user, serverTime}`. Registra o actualiza el celular y se ve en vivo en la web |
| `POST /auth/refresh` | Igual que login. Rota el refresh y el anterior queda invalidado |
| `POST /auth/logout` | 204 |
| `GET /auth/me` | `UserProfile` |
| `POST /auth/change-password` | 204 (quita `mustChangePassword`) |
| `POST /auth/password-reset-requests` | 202 siempre; el pedido se atiende en la web |
| `GET /mobile/bootstrap` | `{catalogVersion, lots, rows, segments, markers, lateralCodes, qualityProfile, serverTime}`. Solo lo activo; desde v1.2 segmentos y marcadores traen `"active": true` (ADR-W-006) |
| `POST /sessions` | 201 o 200 `{sessionId, status}`. Idempotente; una sesión `CLOSED` no se reabre |
| `POST /sessions/{id}/passes` | 201 o 200 `{passId, status}` |
| `POST /sessions/{id}/sequences/batch` | `{accepted, duplicates}` (máximo 200 por petición) |
| `POST /sessions/{id}/incidents/batch` | `{accepted, duplicates}` |
| `POST /captures/{id}/upload-ticket` | v2.0: `{captureId, alreadyConfirmed, upload:{url, fields, publicId, expiresAt, maxBytes}, serverTime}` |
| `POST /captures/upload` | 201 o 200 `{captureId, status:"SINCRONIZADO", duplicate}` (ver §4) |
| `GET /captures/{id}` | Estado de una captura (diagnóstico) |
| `GET /mobile/pest-reports?days=30` | v1.3 (ADR-W-007), «Ubicar plaga»: `{reports:[{caseId, status, statusLabel, origin, label, maxConfidence, capturedAt, decidedAt, lot, row, lateralCode, lateralLabel, segment, marker, lat, lon, gpsAccuracyM, locationSource, observation, thumbnailUrl}], farm:{lots, rows, points, center}, days, serverTime}`. Operador, administrador y especialista |

Desde la v1.3 el **especialista** puede ingresar a la app, pero solo para «Ubicar plaga»: las rutas de sesiones,
pasadas, secuencias, incidencias y fotos le responden 403 `ROLE_NOT_ALLOWED`.

Los campos que la app envía y que el contrato no tiene **no se rechazan**: se avisan una vez en la consola
(«La app envió campos fuera del contrato…»). Así una versión nueva de la app no bloquea la sincronización.

## 4. Fotos: dos formas aceptadas

### A. App actual (v1, lo que hoy hace `src/api/syncApi.ts`)

`POST /captures/upload` **multipart** con `file` (JPEG) y `metadata` (JSON en texto, `CaptureUploadMetadata`).
El servidor:

1. valida la metadata, el lateral de la pasada, los usuarios, el tamaño y el **md5** del archivo;
2. sube la foto a Cloudinary con `type=authenticated` y `overwrite=false`, o al simulado en dev;
3. verifica la firma de la respuesta de Cloudinary y, en una sola transacción, guarda la captura, su calidad y la
   **tarea de IA** pendiente.

Si la app reintenta, responde 200 con `duplicate: true` sin volver a subir. Con `API_SUBIDA_MULTIPART=false`
este camino se desactiva cuando la app migre a la forma B.

### B. Flujo v2.0 (§15.7): la foto no pasa por el servidor

1. `POST /captures/{captureId}/upload-ticket` con `{captureId, sessionId, passId, sequenceId, sizeBytes, md5, mimeType}`.
2. La app sube **multipart** a `upload.url` con todos los `upload.fields` y `file`. Cloudinary responde
   `public_id, version, signature, bytes, format, width, height, etag`.
3. `POST /captures/upload` **JSON** con `{metadata, cloudinary:{publicId, version, signature, bytes, format, width, height, etag}}`.

En dev sin `CLOUDINARY_URL`, `upload.url` apunta a la propia laptop
(`http://<IP>:8000/dev/cloudinary/v1_1/riachuelo-simulado/image/upload`) con la misma firma del SDK.

## 5. Lo que pasa después (sin acción de la app)

`worker_ia` toma la tarea, descarga el original firmado, corre YOLO (con recortes si se configuraron) y, si hay
cajas, abre un **caso** `PENDIENTE_REVISION` (o `CONFIRMADO_POR_IA` si la confianza alcanza el umbral automático del
modelo, y entonces avisa por WhatsApp sin esperar). El caso aparece en la bandeja y en la campana de la web en menos de
20 s. Cuando el especialista **confirma**, el worker envía el WhatsApp con el enlace al caso. Salvo
`GET /mobile/pest-reports` (v1.3, ADR-W-007), la API no devuelve URLs de fotos ni resultados de la IA a la app (§28.10).

## 6. Probar sin celular

```powershell
python manage.py test api simulador        # 36 pruebas del contrato, incluido el flujo completo en la laptop
```
