# simulador/fotos.py — Fotos de DEMOSTRACIÓN generadas en el servidor (solo modo simulado de desarrollo).
#
# Las capturas de `sembrar_demo` no tienen archivo: para evaluar el diseño sin Cloudinary se dibuja, de forma
# determinista por public_id, una escena de vid vertical (3:4, como las fotos de 3000×4000 de la app): hojas
# palmeadas, cordón, racimos y manchas algodonosas parecidas al chanchito blanco. Se cachean en media/.
# Las fotos REALES que suba la app al Cloudinary simulado se sirven tal cual (redimensionadas por variante).
import hashlib
import io
import math
import random
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageDraw, ImageFilter, ImageOps

BASE_W, BASE_H = 900, 1200  # 3:4
VARIANTES_DEMO = 16  # escenas distintas; el public_id elige una


def _cache_dir() -> Path:
    d = Path(settings.MEDIA_ROOT) / "demo_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _semilla(public_id: str) -> int:
    return int(hashlib.sha1(public_id.encode()).hexdigest()[:8], 16)


def _hoja(draw, cx, cy, r, ang, color, vena, rnd):
    """Hoja de vid: cinco lóbulos con borde dentado y nervaduras."""
    pts = []
    n = 90
    for i in range(n):
        t = 2 * math.pi * i / n
        lobulo = 0.72 + 0.28 * abs(math.cos(2.5 * t))
        diente = 1 + 0.045 * math.sin(t * 38 + rnd.random())
        rr = r * lobulo * diente * (0.85 if math.sin(t) > 0.6 else 1.0)  # seno peciolar
        pts.append((cx + rr * math.cos(t + ang), cy + rr * math.sin(t + ang) * 0.92))
    draw.polygon(pts, fill=color)
    for k in range(5):
        t = ang + math.pi / 2 + (k - 2) * 0.62
        draw.line([(cx, cy), (cx + r * 0.8 * math.cos(t), cy + r * 0.8 * math.sin(t))], fill=vena,
                  width=max(1, int(r / 28)))


def _escena(variante: int) -> Image.Image:
    rnd = random.Random(1000 + variante)
    img = Image.new("RGB", (BASE_W, BASE_H))
    d = ImageDraw.Draw(img)
    # fondo: follaje lejano oscuro con degradado
    for y in range(BASE_H):
        k = y / BASE_H
        d.line([(0, y), (BASE_W, y)], fill=(int(18 + 22 * k), int(52 + 30 * (1 - k)), int(24 + 10 * k)))
    fondo = Image.new("RGBA", (BASE_W, BASE_H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fondo)
    for _ in range(70):  # bokeh de hojas lejanas
        x, y, r = rnd.uniform(0, BASE_W), rnd.uniform(0, BASE_H * 0.85), rnd.uniform(40, 120)
        g = rnd.randint(60, 120)
        fd.ellipse([x - r, y - r, x + r, y + r], fill=(30, g, 40, rnd.randint(60, 140)))
    img.paste(fondo.filter(ImageFilter.GaussianBlur(18)), (0, 0), fondo.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    # suelo
    suelo_y = int(BASE_H * rnd.uniform(0.86, 0.92))
    for y in range(suelo_y, BASE_H):
        k = (y - suelo_y) / max(1, BASE_H - suelo_y)
        d.line([(0, y), (BASE_W, y)], fill=(int(120 - 30 * k), int(92 - 25 * k), int(62 - 20 * k)))
    # tronco y cordón
    tx = int(BASE_W * rnd.uniform(0.25, 0.75))
    cord_y = int(BASE_H * rnd.uniform(0.5, 0.62))
    madera = (92, 64, 40)
    d.line([(tx, BASE_H), (tx + rnd.randint(-30, 30), cord_y)], fill=madera, width=34)
    pts = [(x, cord_y + 14 * math.sin(x / 90 + variante)) for x in range(-20, BASE_W + 40, 20)]
    d.line(pts, fill=madera, width=22)
    d.line([(x, y - 6) for x, y in pts], fill=(120, 88, 58), width=5)
    # hojas en capas (atrás más oscuras y desenfocadas)
    for capa in range(3):
        hojas = Image.new("RGBA", (BASE_W, BASE_H), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hojas)
        for _ in range(9 + capa * 4):
            r = rnd.uniform(70, 150) * (1.2 - capa * 0.15)
            cx, cy = rnd.uniform(-40, BASE_W + 40), rnd.uniform(-40, BASE_H * 0.8)
            base = (rnd.randint(40, 70) + capa * 18, rnd.randint(110, 150) + capa * 20, rnd.randint(30, 55))
            vena = tuple(min(255, c + 40) for c in base)
            ang = rnd.uniform(0, math.pi * 2)
            if capa == 2:  # sombra suave de las hojas del frente
                _hoja(hd, cx + 10, cy + 14, r, ang, (8, 30, 14, 110), (8, 30, 14, 0), rnd)
            _hoja(hd, cx, cy, r, ang, base + (255,), vena + (255,), rnd)
        if capa < 2:
            hojas = hojas.filter(ImageFilter.GaussianBlur(4 - capa * 2))
        img.paste(hojas, (0, 0), hojas)
    d = ImageDraw.Draw(img)
    # racimos bajo el cordón
    for _ in range(rnd.randint(2, 4)):
        gx, gy = rnd.uniform(80, BASE_W - 80), cord_y + rnd.uniform(30, 160)
        morado = rnd.random() < 0.6
        for fila in range(7):
            for col in range(7 - fila):
                x = gx + (col - (6 - fila) / 2) * 22 + rnd.uniform(-3, 3)
                y = gy + fila * 20 + rnd.uniform(-3, 3)
                c = (rnd.randint(70, 95), rnd.randint(30, 45), rnd.randint(90, 115)) if morado else \
                    (rnd.randint(150, 175), rnd.randint(170, 195), rnd.randint(80, 100))
                d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=c, outline=tuple(int(v * 0.7) for v in c))
                d.ellipse([x - 6, y - 8, x - 1, y - 3], fill=tuple(min(255, v + 70) for v in c))
    # manchas algodonosas (parecidas al chanchito blanco) cerca del cordón y en los racimos
    algodon = Image.new("RGBA", (BASE_W, BASE_H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(algodon)
    for _ in range(rnd.randint(3, 8)):
        mx, my = rnd.uniform(40, BASE_W - 40), cord_y + rnd.uniform(-30, 200)
        for _ in range(rnd.randint(4, 9)):
            x, y = mx + rnd.uniform(-22, 22), my + rnd.uniform(-12, 12)
            w, h = rnd.uniform(6, 13), rnd.uniform(4, 8)
            ad.ellipse([x - w, y - h, x + w, y + h], fill=(240, 240, 232, rnd.randint(190, 245)))
    img.paste(algodon.filter(ImageFilter.GaussianBlur(1.6)), (0, 0), algodon.filter(ImageFilter.GaussianBlur(1.6)))
    # grano y viñeta ligeros
    ruido = Image.effect_noise((BASE_W, BASE_H), 10).convert("RGB")
    img = Image.blend(img, ruido, 0.035)
    vig = Image.new("L", (BASE_W, BASE_H), 0)
    ImageDraw.Draw(vig).ellipse([-BASE_W * 0.25, -BASE_H * 0.2, BASE_W * 1.25, BASE_H * 1.2], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    img = Image.composite(img, Image.new("RGB", img.size, (8, 20, 12)), vig)
    return img


def foto_demo_jpeg(public_id: str, width) -> bytes:
    """JPEG de demostración para ese public_id (width=None → tamaño base)."""
    variante = _semilla(public_id) % VARIANTES_DEMO
    w = int(width) if width else BASE_W
    path = _cache_dir() / f"escena{variante:02d}_{w}.jpg"
    if path.exists():
        return path.read_bytes()
    img = _escena(variante)
    if w != BASE_W:
        img = img.resize((w, round(w * BASE_H / BASE_W)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=84, optimize=True, progressive=True)
    path.write_bytes(buf.getvalue())
    return buf.getvalue()


def foto_real_jpeg(path: Path, width) -> bytes:
    """Foto subida al simulado, redimensionada como las transformaciones c_limit,w_<n>."""
    if not width:
        return path.read_bytes()
    cache = _cache_dir() / f"real_{hashlib.sha1(str(path).encode()).hexdigest()[:16]}_{width}.jpg"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache.read_bytes()
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    cache.write_bytes(buf.getvalue())
    return buf.getvalue()
