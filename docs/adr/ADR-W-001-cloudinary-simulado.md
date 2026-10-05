# ADR-W-001 — Cloudinary simulado en desarrollo

05/10/2026 · Estado: aceptada · Autor: Claude (asistente de desarrollo)

**Contexto.** Sin cuenta de Cloudinary no se puede probar en la laptop el flujo ticket → subida → confirmación →
worker → caso. La web tampoco tiene fotos que mostrar. El Maestro exige URLs firmadas (W-10) y que el API secret
nunca salga del servidor (W-09).

**Decisión.** `evidencias/nube.py` elige el modo una sola vez al arrancar. Con `CLOUDINARY_URL` válido usa el modo
**real**. Si falta y `APP_ENV=dev`, usa el modo **simulado**: la app `simulador` emula la Upload API con la misma
firma del SDK (`api_sign_request` y `verify_api_response_signature`, con un secreto derivado de `SECRET_KEY`).
Guarda los JPEG en `media/cloudinary_simulado/` y entrega las variantes `miniatura`, `revision` y `original` solo
a usuarios con sesión en la web. A las capturas de demostración sin archivo les dibuja una foto ilustrativa.
En `piloto` este modo nunca se activa: las rutas `/dev/` no se montan y `diagnostico.E002` bloquea el arranque.

**Alternativas.** Pedir la cuenta de Cloudinary antes de empezar, o usar mocks solo en pruebas. Ambas dejaban la
demo local sin fotos y sin flujo real con la app.

**Consecuencias.** La web y la app se prueban completas en la laptop. Una franja amarilla («Modo demostración»)
avisa que las fotos son locales. Las pruebas automáticas corren en modo real con credenciales ficticias para
verificar las URLs `authenticated` firmadas.

**Secciones afectadas.** Maestro Web §14 (entrega de fotos) y Maestro App §15.7 y §28.7 (sin cambios de contrato).
