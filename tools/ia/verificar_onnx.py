# tools/ia/verificar_onnx.py — QUÉ HACE: prueba un modelo.onnx FUERA del servidor con exactamente el mismo código
# que usa el worker del VPS (ia.inference.onnx.DetectorOnnx.analizar_imagen: letterbox, decodificación, NMS y
# tiling). Si aquí funciona, en el worker funciona igual.
#
#   · Analiza las fotos de --imagenes (fotos COMPLETAS, p. ej. prueba_completa/images de cortar_mosaicos.py).
#   · Guarda cada foto con sus cajas dibujadas en --salida y todos los resultados en resultados.json.
#   · Si se pasa --etiquetas, mide contra las cajas reales: por FOTO (¿la foto con plaga abrió caso?, ¿la foto
#     sana dio falsa alarma?) y por CAJA (coincidencia con IoU >= --iou-match).
#   · Con --barrido repite la medición para varios umbrales de confianza y sugiere conf_threshold.
#   · Mide el tiempo por foto (en el VPS, con 0,7 CPU, será más lento que en una laptop).
#   · Imprime la configuración lista para copiar en /gestion/ → Modelos de IA (con el sha256 del archivo).
#
# Uso (desde la raíz del repositorio; requiere Django, Pillow, numpy y onnxruntime):
#   python tools/ia/verificar_onnx.py --modelo modelo.onnx --imagenes datos/dataset_v1/prueba_completa/images \
#       --etiquetas datos/dataset_v1/prueba_completa/labels --salida verificacion --barrido
import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from PIL import Image, ImageDraw, ImageOps  # noqa: E402

from ia.inference.onnx import DetectorOnnx  # noqa: E402

CLASES_V1 = ["chanchito_blanco", "melaza_fumagina"]
EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COLORES = ["#d92d20", "#7a5af8", "#0ba5ec", "#f79009", "#12b76a"]
UMBRALES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def leer_verdad(etq: Path, w, h):
    out = []
    if etq.exists():
        for linea in etq.read_text(encoding="utf-8").splitlines():
            p = linea.split()
            if len(p) >= 5:
                c, cx, cy, bw, bh = int(float(p[0])), *map(float, p[1:5])
                out.append((c, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
    return out


def medir(resultados, clases, conf, iou_match):
    """Métricas para un umbral: por foto (cualquier clase y por clase) y por caja."""
    m = {"conf": conf, "fotos": len(resultados)}
    fp_img = fn_img = tp_img = tn_img = 0
    por_clase = {c: {"tp": 0, "fp": 0, "fn": 0, "img_tp": 0, "img_fn": 0} for c in clases}
    for r in resultados:
        pred = [b for b in r["cajas"] if b["confidence"] >= conf]
        verdad = r["verdad"]
        hay_plaga, alarma = bool(verdad), bool(pred)
        tp_img += hay_plaga and alarma
        fn_img += hay_plaga and not alarma
        fp_img += alarma and not hay_plaga
        tn_img += not hay_plaga and not alarma
        for ci, cname in enumerate(clases):
            v = [g[1:] for g in verdad if g[0] == ci]
            p = sorted([b for b in pred if b["class_name"] == cname], key=lambda b: -b["confidence"])
            usadas = set()
            for b in p:
                caja = (b["x_min"], b["y_min"], b["x_max"], b["y_max"])
                mejor, j = 0.0, -1
                for k, g in enumerate(v):
                    if k not in usadas and iou(caja, g) > mejor:
                        mejor, j = iou(caja, g), k
                if mejor >= iou_match:
                    usadas.add(j)
                    por_clase[cname]["tp"] += 1
                else:
                    por_clase[cname]["fp"] += 1
            por_clase[cname]["fn"] += len(v) - len(usadas)
            if v:
                por_clase[cname]["img_tp" if p else "img_fn"] += 1
    m["fotos_con_plaga_detectadas"] = f"{tp_img}/{tp_img + fn_img}"
    m["recall_foto"] = round(tp_img / (tp_img + fn_img), 3) if tp_img + fn_img else None
    m["falsas_alarmas_foto"] = f"{fp_img}/{fp_img + tn_img}"
    m["precision_foto"] = round(tp_img / (tp_img + fp_img), 3) if tp_img + fp_img else None
    for c, d in por_clase.items():
        d["recall_caja"] = round(d["tp"] / (d["tp"] + d["fn"]), 3) if d["tp"] + d["fn"] else None
        d["precision_caja"] = round(d["tp"] / (d["tp"] + d["fp"]), 3) if d["tp"] + d["fp"] else None
    m["por_clase"] = por_clase
    return m


def dibujar(img, cajas, clases, destino: Path):
    lienzo = img.copy()
    d = ImageDraw.Draw(lienzo)
    grosor = max(3, lienzo.width // 600)
    for b in cajas:
        color = COLORES[clases.index(b["class_name"]) % len(COLORES)] if b["class_name"] in clases else "#ffffff"
        d.rectangle([b["x_min"], b["y_min"], b["x_max"], b["y_max"]], outline=color, width=grosor)
        d.text((b["x_min"] + 4, max(0, b["y_min"] - 14)), f"{b['class_name']} {b['confidence']:.2f}", fill=color)
    lienzo.thumbnail((1600, 1600))
    lienzo.save(destino, quality=85)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verifica un modelo ONNX con el mismo código del worker.")
    ap.add_argument("--modelo", required=True, help="Ruta a modelo.onnx")
    ap.add_argument("--imagenes", required=True, help="Carpeta con fotos completas")
    ap.add_argument("--etiquetas", help="Carpeta con las etiquetas YOLO de esas fotos (para medir)")
    ap.add_argument("--clases", nargs="+", default=CLASES_V1, help="Mismo orden que en el entrenamiento")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.45, help="IoU del NMS (iou_threshold)")
    ap.add_argument("--tile", type=int, default=1280, help="0 = sin tiling (toda la foto a imgsz)")
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--iou-match", type=float, default=0.3, help="IoU para contar una caja como acierto")
    ap.add_argument("--barrido", action="store_true", help="Medir con varios umbrales y sugerir conf_threshold")
    ap.add_argument("--salida", default="verificacion_onnx")
    ap.add_argument("--version", default="2026.10-v1", help="Versión para la configuración sugerida")
    ap.add_argument("--limite", type=int, default=0, help="Máximo de fotos (0 = todas)")
    args = ap.parse_args(argv)

    modelo = Path(args.modelo)
    conf_base = min([args.conf] + (UMBRALES if args.barrido else []))
    tiling = {"tile": args.tile, "overlap": args.overlap} if args.tile else {}
    cfg = SimpleNamespace(classes=args.clases, conf_threshold=conf_base, iou_threshold=args.iou, imgsz=args.imgsz,
                          tiling=tiling, version=args.version)
    detector = DetectorOnnx(cfg, modelo)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fotos = sorted(p for p in Path(args.imagenes).iterdir() if p.suffix.lower() in EXT)
    if args.limite:
        fotos = fotos[: args.limite]
    if not fotos:
        sys.exit(f"No hay fotos en {args.imagenes}")
    resultados, tiempos = [], []
    for i, foto in enumerate(fotos, 1):
        with Image.open(foto) as im:
            img = ImageOps.exif_transpose(im).convert("RGB")
        t0 = time.perf_counter()
        res = detector.analizar_imagen(img)
        tiempos.append((time.perf_counter() - t0) * 1000)
        verdad = leer_verdad(Path(args.etiquetas) / f"{foto.stem}.txt", *img.size) if args.etiquetas else []
        visibles = [b for b in res.boxes if b["confidence"] >= args.conf]
        resultados.append({"foto": foto.name, "ancho": res.width, "alto": res.height, "ms": round(tiempos[-1]),
                           "recortes": res.raw.get("recortes"), "cajas": res.boxes, "verdad": verdad})
        dibujar(img, visibles, args.clases, salida / f"{foto.stem}_cajas.jpg")
        print(f"[{i}/{len(fotos)}] {foto.name}: {len(visibles)} caja(s), {res.raw.get('recortes')} recorte(s), "
              f"{tiempos[-1]:.0f} ms")

    print(f"\nTiempo por foto: media {statistics.mean(tiempos):.0f} ms, máximo {max(tiempos):.0f} ms "
          f"(en el VPS con 0,7 CPU espera 2 a 3 veces más).")
    informe = {"modelo": str(modelo), "sha256": sha256(modelo), "tiempos_ms": {
        "media": round(statistics.mean(tiempos)), "max": round(max(tiempos))}, "resultados": resultados}

    if args.etiquetas:
        umbrales = UMBRALES if args.barrido else [args.conf]
        tabla = [medir(resultados, args.clases, u, args.iou_match) for u in umbrales]
        informe["metricas"] = tabla
        print("\nconf  | fotos con plaga detectadas | falsas alarmas en fotos sanas | "
              + " | ".join(f"{c}: recall/precisión caja" for c in args.clases))
        for m in tabla:
            print(f"{m['conf']:.2f}  | {m['fotos_con_plaga_detectadas']:>26} | {m['falsas_alarmas_foto']:>29} | "
                  + " | ".join(f"{m['por_clase'][c]['recall_caja']}/{m['por_clase'][c]['precision_caja']}"
                               for c in args.clases))
        if args.barrido:
            # Regla de la guía: el umbral MÁS ALTO que todavía detecta al menos el 85 % de las fotos con plaga.
            aptos = [m for m in tabla if (m["recall_foto"] or 0) >= 0.85]
            sugerido = max(aptos, key=lambda m: m["conf"])["conf"] if aptos else min(UMBRALES)
            informe["conf_sugerido"] = sugerido
            print(f"\nconf_threshold sugerido: {sugerido} "
                  + ("(detecta >= 85 % de las fotos con plaga)" if aptos else
                     "(NINGÚN umbral llega al 85 %: el modelo necesita más datos antes de activarlo)"))
            args.conf = sugerido

    config = {"name": f"yolo-{'-'.join(c.split('_')[0] for c in args.clases)}", "version": args.version,
              "weights_uri": "modelos/modelo.onnx", "weights_sha256": informe["sha256"], "classes": args.clases,
              "conf_threshold": args.conf, "iou_threshold": args.iou, "imgsz": detector.size, "tiling": tiling,
              "active": True}
    informe["model_config"] = config
    (salida / "resultados.json").write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    (salida / "model_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nConfiguración para /gestion/ → Modelos de IA (también en model_config.json):")
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"\nFotos con cajas dibujadas y resultados.json en: {salida}")


if __name__ == "__main__":
    main()
