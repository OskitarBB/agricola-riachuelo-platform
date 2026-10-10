# ADR-W-009 — La IA decide por lugar con las dos cámaras

09/10/2026 · Aceptada (pedido del responsable del proyecto) · Plataforma v1.3.3 · App sin cambios (0.5.1)

## Contexto

En cada secuencia las dos cámaras fotografían el mismo punto de la hilera, para validar dos veces. Hasta v1.3.2 cada
foto se decidía sola: en una prueba la cámara 1 quedó «Descartado por la IA» y la cámara 2 abrió caso en el mismo
lugar; y si las dos veían indicio se abrían dos casos y salían dos avisos.

## Decisión

1. **Un solo caso por lugar (secuencia)**, con la regla elegida «basta una cámara»: manda la foto de mayor confianza.
   - Las dos bajo el umbral de revisión → la IA descarta el lugar (las dos fotos quedan en «Descartadas por la IA»).
   - Si una alcanza el umbral de revisión → caso del lugar; si alcanza el umbral automático → «Confirmado por IA» y un
     solo aviso.
   - Si la otra cámara llega después: con más confianza pasa a ser la foto principal del caso pendiente
     (`CASO_FOTO_PRINCIPAL_OTRA_CAMARA`) y puede confirmarlo; con menos, solo lo respalda
     (`CASO_RESPALDADO_OTRA_CAMARA`). Una decisión tomada nunca cambia (RN-W06).
   - Con una sola foto (la otra falló o se rechazó por calidad) se aplican las tres franjas como antes.
2. La foto de la otra cámara no aparece sola en «Descartadas por la IA», no se borra en la limpieza de descartadas y,
   al abrirla, lleva al caso del lugar. «Abrir caso» sobre ella devuelve el caso existente.
3. El caso muestra la otra cámara con lo que vio la IA (estado y confianza máxima).
4. `aplicar_triage` primero une los casos pendientes duplicados de un mismo lugar (queda el de mayor confianza, o el
   ya decidido; `CASO_UNIDO_AL_LUGAR`).

## Consecuencias

- Sin migraciones: el caso sigue anclado en una foto (`capture`) y ya tenía `sequence`. Las dos cámaras se serializan
  con un bloqueo de la fila de la secuencia, así dos workers no abren dos casos del mismo lugar.
- La app no cambia: «Ubicar plaga» recibe un caso por lugar.
- «Basta una cámara» prioriza no perder plagas: habrá algo más de casos que con «deben coincidir».
