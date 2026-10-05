-- docs/perf/datos_sinteticos.sql — Datos sintéticos para medir rendimiento (sección 18 del Maestro Web, Anexo H.1).
-- SOLO en una COPIA de dev:
--   createdb -T riachuelo riachuelo_perf        (después de `python manage.py sembrar_demo` en riachuelo)
--   psql -d riachuelo_perf -f docs/perf/datos_sinteticos.sql
--   DATABASE_URL=postgres://…/riachuelo_perf python manage.py medir_rendimiento --email especialista@demo.pe
-- Genera 100 000 capturas (1 de cada 15 rechazada por calidad), sus análisis (≈ 20 % con indicio) y un caso por indicio.
WITH ref AS (SELECT c.sequence_id, c.session_id, c.pass_id, c.device_id, c.camera_user_id, c.operator_user_id
             FROM captures c LIMIT 1)
INSERT INTO captures (capture_id, sequence_id, session_id, pass_id, lateral_code, device_id, camera_role, camera_user_id,
                      operator_user_id, captured_at, width, height, size_bytes, md5, quality_status, retake_context,
                      app_version, cloudinary_public_id, cloudinary_version, cloudinary_bytes, cloudinary_format,
                      confirmed_at, replaces_capture_id, cloudinary_width, cloudinary_height)
SELECT gen_random_uuid(), ref.sequence_id, ref.session_id, ref.pass_id, 'LATERAL_A', ref.device_id, 'CAMERA_1',
       ref.camera_user_id, ref.operator_user_id,
       now() - (g % 60) * interval '1 day' - (g % 600) * interval '1 minute', 3000, 4000, 3900000, md5(g::text),
       CASE WHEN g % 15 = 0 THEN 'REPETIR_NITIDEZ' ELSE 'UTILIZABLE' END, NULL, '0.3.0', 'perf/' || g, 1,
       3900000, 'jpg', now(), NULL, NULL, NULL
FROM generate_series(1, 100000) g, ref;

INSERT INTO ai_tasks (task_id, capture_id, model_config_id, status, requested_at, available_at, attempts, processing_ms,
                      model_version, locked_by, error_message)
SELECT gen_random_uuid(), c.capture_id, (SELECT id FROM model_configs WHERE active),
       CASE WHEN random() < 0.2 THEN 'INDICIO_SUGERIDO_POR_IA' ELSE 'SIN_INDICIOS_IA' END,
       c.captured_at, c.captured_at, 1, 150 + (random() * 200)::int, 'demo-0', '', ''
FROM captures c WHERE c.cloudinary_public_id LIKE 'perf/%' AND c.quality_status = 'UTILIZABLE';

CREATE TEMP TABLE filas AS SELECT row_number() OVER () - 1 AS i, id, lot_id FROM field_rows;

INSERT INTO review_cases (id, capture_id, ai_task_id, origin, status, notification_status, detections_count,
                          max_confidence, session_id, pass_id, sequence_id, lot_id, row_id, lateral_code, segment_id,
                          marker_id, lat, lon, gps_accuracy_m, location_source, captured_at, opened_at, decided_at,
                          decided_by_id)
SELECT gen_random_uuid(), t.capture_id, t.task_id, 'IA',
       (ARRAY['PENDIENTE_REVISION','CONFIRMADO_POR_ESPECIALISTA','DESCARTADO','EVIDENCIA_INSUFICIENTE'])[
           1 + (abs(hashtext(t.task_id::text)) % 4)],
       'NO_APLICA', 1, random(), c.session_id, c.pass_id, c.sequence_id, f.lot_id, f.id, 'LATERAL_A', NULL, NULL,
       -14.06 - random() * 0.01, -75.73 + random() * 0.01, 5, 'GPS', c.captured_at, c.captured_at + interval '1 hour',
       NULL, NULL
FROM ai_tasks t JOIN captures c ON c.capture_id = t.capture_id
JOIN filas f ON f.i = abs(hashtext(t.task_id::text)) % (SELECT count(*) FROM filas)
WHERE t.status = 'INDICIO_SUGERIDO_POR_IA' AND c.cloudinary_public_id LIKE 'perf/%';

UPDATE review_cases SET decided_at = opened_at + interval '3 hours',
       decided_by_id = (SELECT id FROM users WHERE email = 'especialista@demo.pe')
WHERE status <> 'PENDIENTE_REVISION' AND decided_at IS NULL;

ANALYZE;
SELECT (SELECT count(*) FROM captures) AS capturas, (SELECT count(*) FROM ai_tasks) AS tareas,
       (SELECT count(*) FROM review_cases) AS casos;
