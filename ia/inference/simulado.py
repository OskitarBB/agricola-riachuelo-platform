# ia/inference/simulado.py — Detector SIMULADO (solo APP_ENV=dev): no hay pesos todavía, pero el flujo completo
# (cola → cajas → caso → bandeja → decisión → aviso) se puede probar. Determinista por captura: la misma foto
# siempre produce el mismo resultado. Probabilidad de indicio: IA_SIMULADO_PROBABILIDAD (0.2 por defecto).
import hashlib
import random

from django.conf import settings

from evidencias import nube
from ia.inference import Cronometro, Resultado, abrir_imagen


class DetectorSimulado:
    nombre = "simulado"

    def __init__(self, model_config):
        self.model = model_config

    def _tamano(self, capture):
        """Tamaño real de la foto si hay archivo (subida al simulado o a Cloudinary); si no, el que informó la app."""
        try:
            if nube.es_simulado():
                path = nube.ruta_simulada(capture.cloudinary_public_id)
                if not path.exists():
                    return capture.width, capture.height
                img = abrir_imagen(path.read_bytes())
            else:
                img = abrir_imagen(nube.download_original(capture))
            return img.width, img.height
        except Exception:  # noqa: BLE001 — si no se puede leer, se usa el tamaño informado
            return capture.width, capture.height

    def analyze(self, task):
        capture = task.capture
        with Cronometro() as t:
            w, h = self._tamano(capture)
            rnd = random.Random(int(hashlib.sha1(str(capture.pk).encode()).hexdigest()[:8], 16))
            boxes = []
            clase = (self.model.classes or ["chanchito_blanco"])[0]
            if rnd.random() < settings.IA_SIMULADO_PROBABILIDAD:
                for _ in range(rnd.randint(1, 3)):
                    bw, bh = rnd.uniform(0.03, 0.10) * w, rnd.uniform(0.03, 0.08) * h
                    x, y = rnd.uniform(0.05 * w, 0.9 * w - bw), rnd.uniform(0.35 * h, 0.85 * h - bh)
                    boxes.append({"class_name": clase, "confidence": round(rnd.uniform(0.3, 0.95), 3),
                                  "x_min": round(x, 1), "y_min": round(y, 1),
                                  "x_max": round(x + bw, 1), "y_max": round(y + bh, 1)})
        return Resultado(boxes, w, h, max(t.ms, rnd.randint(60, 240)), self.model.version,
                         {"detector": "simulado", "cajas": len(boxes)})
