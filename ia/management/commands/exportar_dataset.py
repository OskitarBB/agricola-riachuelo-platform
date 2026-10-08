# ia/management/commands/exportar_dataset.py — QUÉ HACE: baja fotos del piloto (Cloudinary) para entrenar o
# reentrenar el modelo YOLO, en el formato que leen Roboflow, CVAT y tools/ia/cortar_mosaicos.py.
#
#   --modo fotos      Fotos aceptadas por calidad (filtros por lote, hilera, sesión y fechas), SIN etiquetas:
#                     para etiquetarlas a mano (primer dataset).
#   --modo revisados  Fotos con decisión vigente del especialista:
#                       CONFIRMADO_POR_ESPECIALISTA → cajas de la IA menos las que el especialista marcó
#                                                     incorrectas (pre-etiquetas: revisarlas en el etiquetador,
#                                                     el especialista no dibuja las cajas que faltan);
#                       confirmado sin cajas (caso manual: la IA no vio la plaga) → foto SIN archivo de
#                                                     etiqueta, para dibujar las cajas a mano;
#                       DESCARTADO                  → foto negativa difícil (etiqueta vacía);
#                       EVIDENCIA_INSUFICIENTE      → no se exporta.
#
# Salida: images/*.jpg (orientación ya aplicada, sin EXIF), labels/*.txt (YOLO normalizado; solo en modo
# revisados), metadatos.csv y data.yaml. Nombre de cada foto: LOTE-HILERA__SECUENCIA__CAPTURA.jpg (cortar_mosaicos
# agrupa por secuencia para que las dos cámaras de la misma orden queden en la misma división).
#
# Solo lee: no cambia la base ni Cloudinary. En el VPS el contenedor es de solo lectura; usar un volumen:
#   mkdir -p /srv/riachuelo/datasets && chown 10001:10001 /srv/riachuelo/datasets
#   cd /srv/riachuelo/deploy && docker compose run --rm -v /srv/riachuelo/datasets:/salida web \
#       python manage.py exportar_dataset --modo revisados --salida /salida/revisados_2026-11
import csv
import io
from datetime import datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from evidencias.models import ANALYZABLE_QUALITY, Capture
from ia.models import ModelConfig
from revision.models import HumanReview, ReviewStatus

CLASES_V1 = ["chanchito_blanco", "melaza_fumagina"]


def _fecha(texto, fin=False):
    try:
        d = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"Fecha inválida «{texto}» (usa AAAA-MM-DD)") from exc
    return timezone.make_aware(datetime.combine(d, time.max if fin else time.min))


def nombre_archivo(capture) -> str:
    row = capture.monitoring_pass.row_id if capture.monitoring_pass_id else "SIN-HILERA"
    return f"{row}__{str(capture.sequence_id)[:8]}__{str(capture.capture_id)[:8]}"


def yolo_lineas(detecciones, clases, ancho, alto):
    """Cajas en píxeles de la imagen analizada → líneas YOLO normalizadas. Una clase desconocida se omite.
    Cada caja conserva su propia clase (confirmed_class es del caso entero y va a metadatos.csv)."""
    lineas = []
    for det in detecciones:
        nombre = det.class_name
        if nombre not in clases or not ancho or not alto:
            continue
        cx = (det.x_min + det.x_max) / 2 / ancho
        cy = (det.y_min + det.y_max) / 2 / alto
        w = (det.x_max - det.x_min) / ancho
        h = (det.y_max - det.y_min) / alto
        lineas.append(f"{clases.index(nombre)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lineas


class Command(BaseCommand):
    help = "Exporta fotos del piloto (y, en modo revisados, sus etiquetas) para entrenar YOLO."

    def add_arguments(self, parser):
        parser.add_argument("--modo", choices=["fotos", "revisados"], required=True)
        parser.add_argument("--salida", required=True, help="Carpeta de salida (con permiso de escritura)")
        parser.add_argument("--lote", help="ID del lote, p. ej. SWG5")
        parser.add_argument("--hilera", help="ID de la hilera, p. ej. SWG5-H36")
        parser.add_argument("--sesion", help="UUID de la sesión de monitoreo")
        parser.add_argument("--desde", help="Fecha de captura inicial AAAA-MM-DD")
        parser.add_argument("--hasta", help="Fecha de captura final AAAA-MM-DD")
        parser.add_argument("--limite", type=int, default=500, help="Máximo de fotos (por defecto 500)")
        parser.add_argument("--clases", nargs="+", help="Orden de clases (por defecto, las del modelo activo)")
        parser.add_argument("--sin-imagenes", action="store_true", help="Solo etiquetas y metadatos (prueba)")

    def handle(self, *args, **o):
        from evidencias import nube
        from ia.inference import abrir_imagen

        salida = Path(o["salida"])
        (salida / "images").mkdir(parents=True, exist_ok=True)
        if o["modo"] == "revisados":
            (salida / "labels").mkdir(parents=True, exist_ok=True)
        clases = o["clases"]
        if not clases:
            activo = ModelConfig.objects.filter(active=True).first()
            clases = list(activo.classes) if activo and activo.classes else CLASES_V1

        qs = (Capture.objects.filter(quality_status__in=ANALYZABLE_QUALITY)
              .select_related("monitoring_pass__row", "monitoring_pass__lot", "sequence__segment")
              .order_by("captured_at"))
        if o["lote"]:
            qs = qs.filter(monitoring_pass__lot_id=o["lote"])
        if o["hilera"]:
            qs = qs.filter(monitoring_pass__row_id=o["hilera"])
        if o["sesion"]:
            qs = qs.filter(session_id=o["sesion"])
        if o["desde"]:
            qs = qs.filter(captured_at__gte=_fecha(o["desde"]))
        if o["hasta"]:
            qs = qs.filter(captured_at__lte=_fecha(o["hasta"], fin=True))

        revisiones = {}
        if o["modo"] == "revisados":
            vigentes = (HumanReview.objects.filter(is_current=True, decision__in=[
                ReviewStatus.CONFIRMADO_POR_ESPECIALISTA, ReviewStatus.DESCARTADO]).select_related("case", "ai_task"))
            revisiones = {r.case.capture_id: r for r in vigentes}
            qs = qs.filter(capture_id__in=list(revisiones))
        capturas = list(qs[: o["limite"]])
        if not capturas:
            self.stdout.write(self.style.WARNING("No hay fotos con esos filtros."))
            return

        filas, positivas, negativas, por_etiquetar, errores = [], 0, 0, 0, 0
        for cap in capturas:
            nombre = nombre_archivo(cap)
            decision, n_cajas = "", 0
            try:
                if not o["sin_imagenes"]:
                    img = abrir_imagen(nube.download_original(cap))  # misma orientación que vio el worker
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=95)
                    (salida / "images" / f"{nombre}.jpg").write_bytes(buf.getvalue())
            except Exception as exc:  # una foto que falla no detiene la exportación
                errores += 1
                self.stderr.write(f"{cap.capture_id}: no se pudo bajar ({exc})")
                continue
            rev = revisiones.get(cap.capture_id)
            if rev is not None:
                decision = rev.decision
                lineas = []
                if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA and rev.ai_task_id:
                    rechazadas = {str(i) for i in (rev.rejected_detection_ids or [])}
                    dets = [d for d in rev.ai_task.detections.all() if str(d.pk) not in rechazadas]
                    lineas = yolo_lineas(dets, clases, rev.ai_task.image_width, rev.ai_task.image_height)
                n_cajas = len(lineas)
                if decision == ReviewStatus.CONFIRMADO_POR_ESPECIALISTA and not lineas:
                    # Confirmado sin cajas útiles (caso manual = falso negativo de la IA): NO es una negativa.
                    # Se exporta la foto sin archivo de etiqueta para dibujar las cajas en el etiquetador.
                    por_etiquetar += 1
                else:
                    (salida / "labels" / f"{nombre}.txt").write_text(
                        "\n".join(lineas) + ("\n" if lineas else ""), encoding="utf-8")
                    if lineas:
                        positivas += 1
                    else:
                        negativas += 1
            mp = cap.monitoring_pass
            seg = cap.sequence.segment if cap.sequence_id else None
            filas.append({
                "archivo": f"{nombre}.jpg", "capture_id": cap.capture_id, "lote": mp.lot_id if mp else "",
                "hilera": mp.row_id if mp else "", "lateral": cap.lateral_code, "camara": cap.camera_role,
                "segmento": seg.id if seg else "", "plantas": f"{seg.start_plant}-{seg.end_plant}" if seg else "",
                "capturada": timezone.localtime(cap.captured_at).isoformat(timespec="seconds"),
                "calidad": cap.quality_status, "decision": decision, "cajas": n_cajas,
                "clase_confirmada": rev.confirmed_class if rev else "",
                "observacion": (rev.observation if rev else "").replace("\n", " ")[:300],
            })

        with open(salida / "metadatos.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else ["archivo"])
            w.writeheader()
            w.writerows(filas)
        (salida / "data.yaml").write_text(
            "# Generado por manage.py exportar_dataset\nnames:\n"
            + "".join(f"  {i}: {c}\n" for i, c in enumerate(clases)),
            encoding="utf-8")
        resumen = f"{len(filas)} foto(s) exportadas en {salida}"
        if o["modo"] == "revisados":
            resumen += f" ({positivas} con cajas confirmadas, {negativas} negativas"
            resumen += f", {por_etiquetar} confirmadas sin cajas: dibujarlas a mano)" if por_etiquetar else ")"
        if errores:
            resumen += f"; {errores} con error de descarga"
        self.stdout.write(self.style.SUCCESS(resumen))
