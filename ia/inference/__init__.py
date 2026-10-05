# ia/inference — Detectores que usa el worker (§28.8 del maestro móvil; tarea T-W11 del Maestro Web).
#
#   IA_DETECTOR=simulado → cajas pseudoaleatorias deterministas (solo dev; para probar el flujo sin pesos).
#   IA_DETECTOR=onnx     → modelo YOLO exportado a ONNX (Ultralytics YOLOv8/11 o YOLO26/v10 sin NMS) con
#                          onnxruntime en CPU, con tiling opcional (model_configs.tiling).
#   IA_DETECTOR=yolo     → ultralytics.YOLO(MODEL_PATH) (.pt u .onnx). Licencia AGPL-3.0 (riesgo R-A6).
#
# Contrato con el worker: detector.analyze(task) → Resultado(boxes, width, height, ms, model_version, raw), con cajas
# en PÍXELES de la imagen analizada después de aplicar la orientación EXIF (sección 14.2 del Maestro Web).
import io
import time
from dataclasses import dataclass, field

from django.conf import settings
from PIL import Image, ImageOps


@dataclass
class Resultado:
    boxes: list
    width: int
    height: int
    ms: int
    model_version: str
    raw: dict = field(default_factory=dict)


class DetectorNoDisponible(Exception):
    """Falta el archivo de pesos o la librería del detector: el worker lo informa y no toma tareas."""


def abrir_imagen(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # cajas en la orientación real de la foto (CP-W14)
    return img.convert("RGB")


class Cronometro:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.t0) * 1000)


def cargar_detector(model_config, nombre=None):
    """Carga el detector UNA vez al arrancar el worker (el modelo queda «caliente»)."""
    nombre = (nombre or settings.IA_DETECTOR or "simulado").lower()
    if nombre == "simulado":
        from ia.inference.simulado import DetectorSimulado

        return DetectorSimulado(model_config)
    if nombre == "onnx":
        from ia.inference.onnx import DetectorOnnx

        return DetectorOnnx(model_config, settings.MODEL_PATH)
    if nombre == "yolo":
        from ia.inference.yolo import DetectorYolo

        return DetectorYolo(model_config, settings.MODEL_PATH)
    raise DetectorNoDisponible(f"IA_DETECTOR desconocido: {nombre} (usa simulado, onnx o yolo)")
