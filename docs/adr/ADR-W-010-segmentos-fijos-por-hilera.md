# ADR-W-010 — Cantidad fija de segmentos por hilera y lotes estándar

20/10/2026 · Estado: propuesta para el equipo (pedido de Oscar) · Autor: Claude (asistente de desarrollo)

**Contexto.** La web permite crear segmentos y la app los usa para ubicar cada foto (lote → hilera → lateral →
segmento → marcador). No había una cantidad definida: `MAX_SEGMENTOS_POR_HILERA = 50` solo se aplicaba al
«Dividir»; «Nuevo segmento» y «Reactivar» no tenían tope, así que una hilera podía quedar con decenas de segmentos
y la app no sabía cuántos esperar. Las 83 hileras reales del piloto tienen un solo segmento «Hxx completa», con lo
que la plaga solo se ubica por hilera. Además se pidió cargar 10 lotes con hileras de ≈200 m.

**Decisión.**

1. **Cantidad fija:** `SEGMENTOS_POR_HILERA = 10` (variable de entorno, 1 a 50). Es el **máximo de segmentos
   activos** por hilera (crear, reactivar y dividir lo respetan) y el **reparto estándar**: partes iguales que cubren
   todas las plantas, contiguas, con un marcador al inicio de cada segmento (`Hxx Sk inicio`, el primero INICIO y el
   resto INTERMEDIO) y uno al final (`Hxx fin`, FIN). Los **dos laterales comparten los mismos segmentos**.
   Con 200 m: 10 segmentos de ≈20 m (≈13 plantas); la foto se ubica con ±10 m aunque no haya GPS.
2. **Largo de la hilera:** `FieldRow.length_m` (metros, opcional; migración aditiva `campo/0005`). Si al crear
   hileras solo se da el largo, las plantas salen de `DISTANCIA_ENTRE_PLANTAS_M = 1,5` (1904 plantas/ha del Excel de
   mapeo = 3,5 m × 1,5 m): 200 m → 133 plantas. La web muestra los metros de cada segmento.
3. **Web:** «Agregar hileras» pide largo o plantas y crea por defecto el reparto estándar; cada hilera muestra
   «n/10» y avisa si está fuera del estándar (menos o más segmentos, o plantas sin segmento); el lote tiene «Aplicar
   10 segmentos» (`estandarizar_lote`), que solo cambia las hileras que no cumplen. Al dividir, si el inicio y el fin
   de la hilera ya estaban ubicados en el mapa, los marcadores nuevos heredan esas coordenadas y los intermedios se
   interpolan. Auditoría: `CATALOGO_LOTE_SEGMENTOS` (nueva) y las de siempre.
4. **API:** el bootstrap agrega `rows[].lengthM` y `segmentRules = {perRow, plantSpacingM}` (campos nuevos,
   compatibles con la app v0.5.x). La sincronización no cambia.
5. **Lotes estándar:** comando `crear_lotes_estandar` (por defecto `LOTE 01`…`LOTE 10`, 20 hileras de 200 m), con las
   mismas reglas y auditoría que la web, idempotente, sin tocar SWG 1, SWG 2 ni SWG 5. Se permite en el piloto: son
   catálogos, no evidencia (W-22).

**Alternativas.** Segmentos por metros sin plantas (cambia el modelo y la app; las plantas siguen siendo la unidad
del Excel de mapeo). Segmentos distintos por lateral (duplica marcadores y no aporta: los dos lados de la hilera
recorren las mismas plantas). Un tope «suave» solo de aviso (no resuelve que la app sepa cuántos esperar).

**Consecuencias.** Las hileras antiguas siguen funcionando con su segmento completo; se pasan al estándar cuando el
equipo lo decida («Aplicar 10 segmentos» por lote). El bootstrap crece (≈2 000 segmentos y ≈2 300 marcadores con los
10 lotes): la app lo guarda en una transacción. Pendiente: coordenadas reales de inicio y fin de cada hilera
(Q-01) para que los marcadores intermedios tengan ubicación aproximada.
