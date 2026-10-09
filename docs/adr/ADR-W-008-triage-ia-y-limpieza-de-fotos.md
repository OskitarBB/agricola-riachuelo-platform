# ADR-W-008 — Triage de la IA en tres franjas y limpieza de fotos

09/10/2026 · Aceptada (pedido del responsable del proyecto) · Plataforma v1.3.1 · App 0.5.1 (CFG-9)

## Contexto

En el piloto casi todas las fotos terminaban en la bandeja como «Pendiente de revisión»: cualquier caja por encima de
`conf_threshold` (0,25) abría un caso, y el especialista tenía que revisar todo. Además, las fotos de prueba y las que
la IA descarta se acumulaban en Cloudinary, en la base y en los celulares, sin forma de borrarlas (R-11 / RN-09 decían
«no borrar evidencia» mientras la política de retención Q-05 seguía abierta).

## Decisión

1. **Triage en tres franjas** por la confianza máxima de la foto, con dos umbrales por modelo (`/gestion/` → Modelos
   de IA o `python manage.py aplicar_triage`):
   - por debajo de `review_threshold` (propuesto 0,50) → la IA la descarta sola: tarea `DESCARTADO_POR_IA`, sin caso
     (no aparece en Casos; las cajas se guardan para medir y reentrenar; el especialista igual puede abrir un caso a
     mano desde la foto);
   - entre los dos umbrales → caso «Pendiente de revisión» para el especialista;
   - desde `auto_confirm_threshold` (propuesto 0,85) → «Confirmado por IA» y aviso (ADR-W-007).
   Vacío = apagado. `aplicar_triage` aplica los umbrales a los casos pendientes que ya abrió la IA y nunca cambia una
   decisión tomada.
2. **Limpieza de fotos** (solo ADMINISTRADOR, escribiendo «ELIMINAR»): borrar una sesión completa o las fotos sin caso
   «Sin indicios / Descartado por la IA» de más de N días. Se borra en la base (casos, decisiones, avisos, análisis),
   en Cloudinary (`delete_resources` con invalidación; si falla, el worker reintenta cada minuto) y en los celulares
   (GET `/api/v1/mobile/deleted-captures`; 410 `SESSION_DELETED` / `CAPTURE_DELETED` impide volver a subirlas).
   Quedan `deleted_captures` y `deleted_sessions` (solo IDs) y la auditoría (`SESION_ELIMINADA`,
   `FOTOS_DESCARTADAS_ELIMINADAS`, `CASO_DESCARTADO_POR_IA`, `MODELO_UMBRALES`).
3. **Miniaturas**: las URLs firmadas llevan el tamaño escrito (`c_limit,w_400,q_auto`) en lugar de transformaciones
   con nombre; la web ya no depende de la consola de Cloudinary.
4. **Avisos simulados**: con `ConsoleClient` la web muestra «Simulado (no enviado)» en vez de «Enviado».

## Consecuencias

- R-11 / RN-09 cambian: la evidencia se conserva salvo que el ADMINISTRADOR la borre con la limpieza. En el celular la
  fila local se conserva (solo se borra el archivo y se cierra la cola).
- Con el modelo de integración actual (fotos de internet) los umbrales no corrigen sus errores: confunde uvas sanas
  con plaga con confianzas de 0,6–0,8. El triage funcionará bien con el modelo v1 entrenado con fotos del fundo.
- La app 0.5.0 trata el 410 como error definitivo; la 0.5.1 lo entiende y borra su copia local.
