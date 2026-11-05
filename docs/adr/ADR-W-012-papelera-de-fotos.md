# ADR-W-012 — Papelera de fotos (borrado individual a mano)

05/11/2026 · Estado: aceptada por Oscar · Autor: Claude (asistente de desarrollo)

**Contexto.** La limpieza (ADR-W-008) borra sesiones completas o descartadas antiguas, pero no había forma de quitar
una foto suelta (de prueba, mal tomada o equivocada). Borrar de inmediato es riesgoso: un clic equivocado pierde
evidencia.

**Decisión.**

1. **Solo el ADMINISTRADOR** (permiso `papelera.gestionar`) ve «Eliminar esta foto» en la foto, en el caso y sobre
   cada miniatura de la sesión. La foto no se borra: va a la **papelera** (`captures.trashed_at`, `trashed_by`,
   `trash_reason`; migración aditiva `evidencias/0004`).
2. **En la papelera** la foto no aparece en la bandeja, el mapa, el plano, el panel, las sesiones, «Descartadas por la
   IA», la exportación ni en «Ubicar plaga» de la app; la IA no la analiza y su caso no se decide (el servicio lo
   vuelve a comprobar, RN-W01). Si es la foto principal de un caso, el caso se oculta con ella y sus avisos pendientes
   se anulan. Los demás roles reciben 404; el administrador la ve con un aviso y el botón «Restaurar».
3. **Restaurar** deja todo como estaba (los avisos anulados no se reenvían). **Borrar para siempre** (una foto o
   «Vaciar la papelera» escribiendo ELIMINAR) usa la misma ruta que la limpieza: base en una transacción →
   Cloudinary → los celulares borran su copia (`DeletionReason.PAPELERA`).
4. **A los 30 días** (`PAPELERA_DIAS`) el worker borra solas las fotos vencidas.
5. Todo queda en la auditoría: `FOTO_A_PAPELERA`, `FOTO_RESTAURADA`, `FOTOS_PAPELERA_ELIMINADAS`, `PAPELERA_VACIADA`,
   `PAPELERA_VENCIDAS_ELIMINADAS`.

**Consecuencias.** W-14 (evidencia inmutable) suma esta excepción, como la limpieza: solo el administrador y con
registro. La bandeja sigue en 6 consultas (el filtro va en la misma consulta).
