# tools/ia/cortar_mosaicos.py — QUÉ HACE: prepara el dataset de entrenamiento de YOLO a partir de fotos completas
# etiquetadas (formato YOLO: images/ + labels/ o la exportación «YOLO» de Roboflow/CVAT).
#
#   1. Junta varias fuentes: --propias (fotos del fundo) y --externas (datasets públicos, solo van a train).
#   2. Renombra las clases de cada fuente a las nuestras (--mapa Mealybug=chanchito_blanco) y descarta las demás.
#   3. Divide las fotos PROPIAS en train / val / test por GRUPO (las fotos de la misma secuencia o de la misma foto
#      original nunca quedan repartidas entre train y test: así la prueba no hace trampa).
#   4. Corta cada foto en recortes (tiles) con la MISMA función que usa el worker en producción
#      (ia.inference.onnx.tiles), recorta las cajas y guarda los recortes con plaga + una parte de recortes vacíos
#      (negativos).
#   5. Copia las fotos completas de test a prueba_completa/ para medir después con tools/ia/verificar_onnx.py,
#      que simula el worker real sobre la foto entera.
#   6. Escribe data.yaml (para Ultralytics) y resumen.json (conteos por división y clase).
#
# Uso (desde la raíz del repositorio de la plataforma; requiere Pillow, numpy y Django instalados):
#   python tools/ia/cortar_mosaicos.py --propias datos/propias --externas datos/roboflow_mealybug \
#       --mapa Mealybug=chanchito_blanco --mapa mealybugs=chanchito_blanco --salida datos/dataset_v1
import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from PIL import Image, ImageOps  # noqa: E402

from ia.inference.onnx import tiles  # noqa: E402  — misma rejilla de recortes que el worker

CLASES_V1 = ["chanchito_blanco", "melaza_fumagina"]
EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MIN_VISIBLE = 0.4  # fracción mínima del área de la caja que debe quedar dentro del recorte
MIN_PX = 4  # lado mínimo (px) de una caja recortada


def leer_nombres(raiz: Path):
    """Nombres de clase de la fuente según su data.yaml (lista o diccionario). None si no hay data.yaml."""
    for yaml_path in list(raiz.glob("data.yaml")) + list(raiz.glob("*/data.yaml")):
        texto = yaml_path.read_text(encoding="utf-8", errors="ignore")
        try:
            import yaml  # PyYAML viene con Ultralytics

            datos = yaml.safe_load(texto) or {}
            nombres = datos.get("names")
            if isinstance(nombres, dict):
                return [nombres[k] for k in sorted(nombres, key=int)]
            if isinstance(nombres, list):
                return nombres
        except ImportError:
            m = re.search(r"names:\s*\[(.*?)\]", texto, re.S)
            if m:
                return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    return None


def ruta_etiqueta(img: Path) -> Path:
    partes = list(img.parts)
    for i in range(len(partes) - 1, -1, -1):
        if partes[i] == "images":
            partes[i] = "labels"
            return Path(*partes).with_suffix(".txt")
    return img.with_suffix(".txt")


def grupo_de(img: Path) -> str:
    """Fotos del mismo grupo van juntas. Quita el sufijo de Roboflow (_jpg.rf.<hash>) y, si el nombre trae «__»
    (lo pone exportar_dataset: LOTE-HILERA__SECUENCIA__CAPTURA), agrupa por todo lo anterior al último «__»."""
    nombre = re.sub(r"_(jpe?g|png)\.rf\.[0-9a-f]+$", "", img.stem, flags=re.I)
    return nombre.rsplit("__", 1)[0] if "__" in nombre else nombre


def division_de(grupo: str, semilla: int, fracciones):
    h = int(hashlib.sha1(f"{semilla}:{grupo}".encode()).hexdigest(), 16) % 10_000 / 10_000
    if h < fracciones[0]:
        return "train"
    if h < fracciones[0] + fracciones[1]:
        return "val"
    return "test"


def leer_cajas(etq: Path, nombres_fuente, mapa, clases, ancho, alto, avisos: Counter):
    """YOLO normalizado → lista (id_clase_nuestra, x1, y1, x2, y2) en píxeles."""
    cajas = []
    if not etq.exists():
        return cajas
    for linea in etq.read_text(encoding="utf-8", errors="ignore").splitlines():
        p = linea.split()
        if len(p) < 5:
            continue
        idx = int(float(p[0]))
        nombre = nombres_fuente[idx] if nombres_fuente and idx < len(nombres_fuente) else (
            clases[idx] if idx < len(clases) else f"clase_{idx}")
        destino = mapa.get(nombre.lower(), nombre if nombre in clases else None)
        if destino is None:
            avisos[f"descartada:{nombre}"] += 1
            continue
        if len(p) > 5:  # polígono (segmentación): se usa su rectángulo
            xs, ys = [float(v) for v in p[1::2]], [float(v) for v in p[2::2]]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        else:
            cx, cy, w, h = map(float, p[1:5])
            x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        cajas.append((clases.index(destino), x1 * ancho, y1 * alto, x2 * ancho, y2 * alto))
    return cajas


def cajas_en_recorte(cajas, x0, y0, x1, y1):
    out = []
    for c, a, b, d, e in cajas:
        area = max(0.0, d - a) * max(0.0, e - b)
        ca, cb, cd, ce = max(a, x0), max(b, y0), min(d, x1), min(e, y1)
        if cd - ca < MIN_PX or ce - cb < MIN_PX or area <= 0:
            continue
        if (cd - ca) * (ce - cb) / area < MIN_VISIBLE:
            continue
        out.append((c, ca - x0, cb - y0, cd - x0, ce - y0))
    return out


def escribir_yolo(ruta: Path, cajas, ancho, alto):
    lineas = [f"{c} {((a + d) / 2) / ancho:.6f} {((b + e) / 2) / alto:.6f} {(d - a) / ancho:.6f} {(e - b) / alto:.6f}"
              for c, a, b, d, e in cajas]
    ruta.write_text("\n".join(lineas) + ("\n" if lineas else ""), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__ or "Prepara el dataset YOLO con recortes.")
    ap.add_argument("--propias", nargs="*", default=[], help="Carpetas con fotos propias etiquetadas")
    ap.add_argument("--externas", nargs="*", default=[], help="Carpetas con datasets públicos (solo train)")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--clases", nargs="+", default=CLASES_V1, help="Clases en el ORDEN del modelo")
    ap.add_argument("--mapa", action="append", default=[], help="NombreFuente=nuestra_clase (repetible)")
    ap.add_argument("--tile", type=int, default=1280, help="Lado del recorte en px de la foto (0 = sin recortes)")
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--negativos", type=float, default=0.25, help="Fracción de recortes vacíos por división")
    ap.add_argument("--division", nargs=3, type=float, default=[0.7, 0.15, 0.15], metavar=("TRAIN", "VAL", "TEST"))
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--calidad", type=int, default=95, help="Calidad JPEG de los recortes")
    args = ap.parse_args(argv)

    clases = list(args.clases)
    mapa = {}
    for m in args.mapa:
        origen, _, destino = m.partition("=")
        if destino not in clases:
            ap.error(f"--mapa {m}: «{destino}» no está en --clases {clases}")
        mapa[origen.strip().lower()] = destino
    for c in clases:
        mapa.setdefault(c.lower(), c)

    salida = Path(args.salida)
    for d in ("train", "val", "test"):
        (salida / "images" / d).mkdir(parents=True, exist_ok=True)
        (salida / "labels" / d).mkdir(parents=True, exist_ok=True)
    (salida / "prueba_completa" / "images").mkdir(parents=True, exist_ok=True)
    (salida / "prueba_completa" / "labels").mkdir(parents=True, exist_ok=True)

    rnd = random.Random(args.semilla)
    avisos, conteo = Counter(), defaultdict(Counter)
    vacios = defaultdict(list)  # división → [(img, x0, y0, x1, y1, nombre)]
    fuentes = [(Path(p), False) for p in args.propias] + [(Path(p), True) for p in args.externas]
    if not fuentes:
        ap.error("Indica al menos una carpeta con --propias o --externas")

    for raiz, externa in fuentes:
        nombres = leer_nombres(raiz)
        imagenes = sorted(p for p in raiz.rglob("*") if p.suffix.lower() in EXT and "labels" not in p.parts)
        print(f"{raiz}: {len(imagenes)} imágenes, clases de la fuente: {nombres or clases}")
        for img_path in imagenes:
            div = "train" if externa else division_de(grupo_de(img_path), args.semilla, args.division)
            with Image.open(img_path) as im:
                img = ImageOps.exif_transpose(im).convert("RGB")
            ancho, alto = img.size
            cajas = leer_cajas(ruta_etiqueta(img_path), nombres, mapa, clases, ancho, alto, avisos)
            base = ("ext_" if externa else "") + re.sub(r"[^\w\-]+", "_", img_path.stem)[:120]
            conteo[div]["fotos"] += 1
            if cajas:
                conteo[div]["fotos_con_plaga"] += 1
            if div == "test" and not externa:
                img.save(salida / "prueba_completa" / "images" / f"{base}.jpg", quality=args.calidad)
                escribir_yolo(salida / "prueba_completa" / "labels" / f"{base}.txt", cajas, ancho, alto)
            for (x0, y0, x1, y1) in tiles(ancho, alto, args.tile, args.overlap):
                dentro = cajas_en_recorte(cajas, x0, y0, x1, y1)
                nombre = f"{base}__t{x0}_{y0}"
                if not dentro:
                    vacios[div].append((img_path, x0, y0, x1, y1, nombre))
                    continue
                img.crop((x0, y0, x1, y1)).save(salida / "images" / div / f"{nombre}.jpg", quality=args.calidad)
                escribir_yolo(salida / "labels" / div / f"{nombre}.txt", dentro, x1 - x0, y1 - y0)
                conteo[div]["recortes_con_plaga"] += 1
                for c, *_ in dentro:
                    conteo[div][f"cajas_{clases[c]}"] += 1

    # Negativos: recortes vacíos al azar hasta llegar a la fracción pedida en cada división.
    for div, lista in vacios.items():
        pos = conteo[div]["recortes_con_plaga"]
        meta = len(lista) if pos == 0 else int(round(pos * args.negativos / max(1e-9, 1 - args.negativos)))
        elegidos = rnd.sample(lista, min(meta, len(lista)))
        abiertas = {}
        for img_path, x0, y0, x1, y1, nombre in elegidos:
            if img_path not in abiertas:
                abiertas.clear()  # una imagen abierta a la vez (fotos de 12 MP)
                with Image.open(img_path) as im:
                    abiertas[img_path] = ImageOps.exif_transpose(im).convert("RGB")
            abiertas[img_path].crop((x0, y0, x1, y1)).save(salida / "images" / div / f"{nombre}.jpg",
                                                          quality=args.calidad)
            (salida / "labels" / div / f"{nombre}.txt").write_text("", encoding="utf-8")
        conteo[div]["recortes_vacios"] = len(elegidos)

    yaml_txt = (f"# Generado por tools/ia/cortar_mosaicos.py (tile={args.tile}, overlap={args.overlap})\n"
                f"path: {salida.resolve().as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
                "names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(clases)))
    (salida / "data.yaml").write_text(yaml_txt, encoding="utf-8")
    resumen = {"clases": clases, "tile": args.tile, "overlap": args.overlap, "divisiones": conteo,
               "avisos": dict(avisos)}
    (salida / "resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    for div in ("val", "test"):
        if conteo[div]["recortes_con_plaga"] == 0:
            print(f"AVISO: «{div}» no tiene recortes con plaga. Faltan fotos propias etiquetadas "
                  "(las externas solo van a train).")
    print(f"Listo: {salida / 'data.yaml'}")


if __name__ == "__main__":
    main()
