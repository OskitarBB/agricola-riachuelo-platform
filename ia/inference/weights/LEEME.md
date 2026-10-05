# Pesos del modelo de IA

Copia aquí el modelo YOLO entrenado y exportado a ONNX (no se sube a Git):

```bash
yolo export model=best.pt format=onnx imgsz=640      # en la máquina del equipo de IA
```

Luego, en `.env`:

```
IA_DETECTOR=onnx
MODEL_PATH=ia/inference/weights/modelo.onnx
```

y registra el modelo en `/gestion/` → **Modelos de IA** (versión, clases en el mismo orden del entrenamiento,
umbral de confianza, IoU, `imgsz` y, si las plagas son pequeñas, `tiling = {"tile": 1280, "overlap": 0.2}`).
Márcalo como **activo**. Comprueba todo con `python manage.py diagnostico`.
