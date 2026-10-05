# ia/inference/yolo.py — Detector con la librería ultralytics (pesos .pt u .onnx). Opcional: requirements-ia.txt.
from pathlib import Path

from ia.inference import Cronometro, DetectorNoDisponible, Resultado, abrir_imagen


class DetectorYolo:
    nombre = "yolo"

    def __init__(self, model_config, model_path):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorNoDisponible("Instala ultralytics (requirements-ia.txt) o usa IA_DETECTOR=onnx.") from exc
        if not Path(model_path).exists():
            raise DetectorNoDisponible(f"No existe MODEL_PATH={model_path}")
        self.model = model_config
        self.yolo = YOLO(str(model_path))

    def analyze(self, task):
        import numpy as np

        from evidencias import nube

        img = abrir_imagen(nube.download_original(task.capture))
        w, h = img.size
        with Cronometro() as t:
            res = self.yolo.predict(np.asarray(img), imgsz=self.model.imgsz, conf=self.model.conf_threshold,
                                    iou=self.model.iou_threshold, verbose=False)[0]
            names = res.names or {}
            boxes = []
            for xyxy, conf, cls in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
                idx = int(cls)
                clases = self.model.classes or []
                nombre = clases[idx] if idx < len(clases) else names.get(idx, f"clase_{idx}")
                boxes.append({"class_name": nombre, "confidence": round(float(conf), 4),
                              "x_min": round(xyxy[0], 1), "y_min": round(xyxy[1], 1),
                              "x_max": round(xyxy[2], 1), "y_max": round(xyxy[3], 1)})
        return Resultado(boxes, w, h, t.ms, self.model.version, {"detector": "yolo", "cajas": len(boxes)})
