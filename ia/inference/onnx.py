# ia/inference/onnx.py — YOLO exportado a ONNX con onnxruntime (CPU). Formatos de salida admitidos:
#   · Ultralytics YOLOv8 / YOLO11: (1, 4 + clases, N) con cx, cy, w, h y puntaje por clase → umbral + NMS.
#   · Ultralytics YOLO26 / YOLOv10 (end2end, sin NMS): (1, N, 6) con x1, y1, x2, y2, puntaje, clase.
# Las cajas vuelven a píxeles de la foto original (sin letterbox) y, con tiling, se unen con un NMS global.
# Exportar desde el equipo de IA: `yolo export model=best.pt format=onnx imgsz=640` (opset por defecto).
import logging
from pathlib import Path

from ia.inference import Cronometro, DetectorNoDisponible, Resultado, abrir_imagen

log = logging.getLogger("riachuelo.ia.onnx")


def letterbox(img, size):
    """Redimensiona manteniendo la proporción y rellena a size×size (gris 114, como Ultralytics)."""
    import numpy as np
    from PIL import Image

    w, h = img.size
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    dx, dy = (size - nw) // 2, (size - nh) // 2
    canvas.paste(img.resize((nw, nh), Image.BILINEAR), (dx, dy))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    return arr.transpose(2, 0, 1)[None], r, dx, dy


def nms(boxes, scores, iou):
    """Supresión de no máximos (numpy). boxes: (N, 4) x1, y1, x2, y2."""
    import numpy as np

    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][ovr <= iou]
    return keep


def _es_end2end(out, num_classes):
    """(N, 6) con x1, y1, x2, y2, puntaje y CLASE ENTERA (YOLO26 / YOLOv10 exportados sin NMS)."""
    import numpy as np

    if out.ndim != 2 or out.shape[-1] != 6 or out.shape[0] < 6:
        return False
    clases = out[:, 5]
    return bool(np.all(np.mod(clases, 1) == 0) and clases.min() >= 0
                and (not num_classes or clases.max() < max(num_classes, 1)))


def decode(output, conf, iou, num_classes=None):
    """Salida cruda del modelo → (boxes xyxy en píxeles del tensor de entrada, scores, clases).
    num_classes (len(model_configs.classes)) resuelve la orientación del tensor sin adivinar."""
    import numpy as np

    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if _es_end2end(out, num_classes):
        sel = out[out[:, 4] >= conf]
        return sel[:, :4], sel[:, 4], sel[:, 5].astype(int)
    canales = 4 + num_classes if num_classes else None
    if canales and out.shape[0] == canales and out.shape[1] != canales:
        out = out.T  # (4 + nc, N) → (N, 4 + nc): YOLOv8 / YOLO11
    elif canales and out.shape[1] == canales:
        pass
    elif out.shape[0] < out.shape[1]:
        out = out.T
    if out.shape[1] < 5:
        raise ValueError(f"Salida del modelo con forma inesperada {tuple(np.shape(output))}: se esperaba (4 + clases, N) "
                         "o (N, 6). Revisa el export y model_configs.classes.")
    cls_scores = out[:, 4:]
    cls = cls_scores.argmax(1)
    scores = cls_scores.max(1)
    m = scores >= conf
    xywh, scores, cls = out[m, :4], scores[m], cls[m]
    boxes = np.empty_like(xywh)
    boxes[:, 0] = xywh[:, 0] - xywh[:, 2] / 2
    boxes[:, 1] = xywh[:, 1] - xywh[:, 3] / 2
    boxes[:, 2] = xywh[:, 0] + xywh[:, 2] / 2
    boxes[:, 3] = xywh[:, 1] + xywh[:, 3] / 2
    keep = []
    for c in np.unique(cls):  # NMS por clase
        idx = np.where(cls == c)[0]
        keep += [int(idx[k]) for k in nms(boxes[idx], scores[idx], iou)]
    keep.sort()
    return boxes[keep], scores[keep], cls[keep]


def tiles(width, height, tile, overlap):
    """Recortes solapados que cubren la foto (insectos pequeños: §28.8 paso 4)."""
    if not tile or (width <= tile and height <= tile):
        return [(0, 0, width, height)]
    step = max(1, int(tile * (1 - overlap)))
    xs = list(range(0, max(1, width - tile) + 1, step))
    ys = list(range(0, max(1, height - tile) + 1, step))
    if xs[-1] + tile < width:
        xs.append(width - tile)
    if ys[-1] + tile < height:
        ys.append(height - tile)
    return [(x, y, min(x + tile, width), min(y + tile, height)) for y in ys for x in xs]


class DetectorOnnx:
    nombre = "onnx"

    def __init__(self, model_config, model_path):
        try:
            import numpy  # noqa: F401
            import onnxruntime as ort
        except ImportError as exc:
            raise DetectorNoDisponible("Instala requirements-ia.txt (onnxruntime y numpy).") from exc
        if not Path(model_path).exists():
            raise DetectorNoDisponible(f"No existe MODEL_PATH={model_path}")
        self.model = model_config
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        shape = self.session.get_inputs()[0].shape
        self.size = int(shape[-1]) if isinstance(shape[-1], int) else int(model_config.imgsz or 640)
        log.info("Modelo ONNX cargado: %s (entrada %s px, %s)", model_path, self.size, model_config.version)

    def _nombre_clase(self, idx):
        clases = self.model.classes or []
        return clases[idx] if 0 <= idx < len(clases) else f"clase_{idx}"

    def _inferir(self, img):
        x, r, dx, dy = letterbox(img, self.size)
        out = self.session.run(None, {self.input: x})[0]
        boxes, scores, cls = decode(out, self.model.conf_threshold, self.model.iou_threshold,
                                    len(self.model.classes or []) or None)
        if len(boxes):
            boxes[:, [0, 2]] = (boxes[:, [0, 2]] - dx) / r
            boxes[:, [1, 3]] = (boxes[:, [1, 3]] - dy) / r
        return boxes, scores, cls

    def analyze(self, task):
        import numpy as np

        from evidencias import nube

        data = nube.download_original(task.capture)
        img = abrir_imagen(data)
        w, h = img.size
        cfg = self.model.tiling or {}
        with Cronometro() as t:
            all_b, all_s, all_c = [], [], []
            recortes = tiles(w, h, int(cfg.get("tile", 0) or 0), float(cfg.get("overlap", 0.2)))
            for (x1, y1, x2, y2) in recortes:
                b, s, c = self._inferir(img.crop((x1, y1, x2, y2)) if len(recortes) > 1 else img)
                if len(b):
                    b[:, [0, 2]] += x1
                    b[:, [1, 3]] += y1
                    all_b.append(b), all_s.append(s), all_c.append(c)
            boxes = []
            if all_b:
                b, s, c = np.concatenate(all_b), np.concatenate(all_s), np.concatenate(all_c)
                keep = nms(b, s, self.model.iou_threshold) if len(recortes) > 1 else list(range(len(b)))
                for i in keep:
                    x_min, y_min = float(max(0, b[i, 0])), float(max(0, b[i, 1]))
                    x_max, y_max = float(min(w, b[i, 2])), float(min(h, b[i, 3]))
                    if x_max - x_min < 1 or y_max - y_min < 1:
                        continue
                    boxes.append({"class_name": self._nombre_clase(int(c[i])), "confidence": round(float(s[i]), 4),
                                  "x_min": round(x_min, 1), "y_min": round(y_min, 1),
                                  "x_max": round(x_max, 1), "y_max": round(y_max, 1)})
        return Resultado(boxes, w, h, t.ms, self.model.version,
                         {"detector": "onnx", "recortes": len(recortes), "cajas": len(boxes)})
