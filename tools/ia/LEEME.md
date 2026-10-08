# tools/ia — Entrenar, verificar y activar el modelo YOLO

QUÉ HAY: herramientas para el equipo de IA. El worker del VPS no las usa; solo lee `deploy/modelos/modelo.onnx`.

| Archivo | Para qué |
| --- | --- |
| `entrenar_yolo_colab.ipynb` | Entrenar en Google Colab (GPU T4). Abrir en Colab desde GitHub o subirlo a Drive. |
| `cortar_mosaicos.py` | Fotos completas etiquetadas → recortes de 1280 px + data.yaml (mismo corte que el worker). |
| `verificar_onnx.py` | Probar un `modelo.onnx` con el mismo código del worker, medir y sugerir `conf_threshold`. |
| `python manage.py exportar_dataset` | Bajar fotos del piloto para etiquetar (`--modo fotos`) o reentrenar con las decisiones del especialista (`--modo revisados`). |

Clases v1, en este orden: `chanchito_blanco`, `melaza_fumagina`. Tiling: `{"tile": 1280, "overlap": 0.2}`.

Uso local (Windows, con el `.venv` de la plataforma y `pip install onnxruntime`):

```
.venv\Scripts\python tools\ia\verificar_onnx.py --modelo modelo.onnx --imagenes fotos_prueba --salida verificacion
```

Exportar fotos en el VPS (el contenedor es de solo lectura; se usa un volumen):

```
mkdir -p /srv/riachuelo/datasets && chown 10001:10001 /srv/riachuelo/datasets
cd /srv/riachuelo/deploy && docker compose run --rm -v /srv/riachuelo/datasets:/salida web \
    python manage.py exportar_dataset --modo fotos --lote SWG5 --desde 2026-10-10 --salida /salida/swg5_fotos
cd /srv/riachuelo/datasets && tar czf swg5_fotos.tgz swg5_fotos     # luego, desde la PC: scp root@IP:/srv/riachuelo/datasets/swg5_fotos.tgz .
```

Guía completa: doc «Guía YOLO — Chanchito blanco (Riachuelo)» en el proyecto de Claude «INTEGRADOR II».
