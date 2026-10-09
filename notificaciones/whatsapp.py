# notificaciones/whatsapp.py — Clientes de WhatsApp. En desarrollo se usa ConsoleClient (no envía nada: escribe en la
# consola del worker cómo quedaría el mensaje). En piloto: WHATSAPP_CLIENT=notificaciones.whatsapp.CloudApiClient.
import logging
import uuid

from django.conf import settings
from django.utils.module_loading import import_string

log = logging.getLogger("riachuelo.whatsapp")

# Texto de la plantilla propuesta (sección 15.3 del Maestro Web); la versión oficial la aprueba Meta (Q-W08).
PLANTILLA = ("Riachuelo · Caso fitosanitario confirmado por el especialista.\n"
             "Lote {1}, hilera {2}, {3} ({4}).\n"
             "Foto tomada el {5}.\n"
             "Ver el caso (requiere iniciar sesión): {6}\n"
             "Mensaje automático: no responder a este número.")
# v1.3 (ADR-W-007): alerta de alta confianza de la IA, sin esperar al especialista (plantilla WHATSAPP_TEMPLATE_IA).
PLANTILLA_IA = ("Riachuelo · ALERTA de plaga detectada por la IA con alta confianza (pendiente de revisión del "
                "especialista).\n"
                "Lote {1}, hilera {2}, {3} ({4}).\n"
                "Foto tomada el {5}.\n"
                "Ver el caso y cómo llegar: {6}\n"
                "Mensaje automático: no responder a este número.")


class WhatsAppError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def render_preview(payload):
    params = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
    texto = PLANTILLA_IA if payload.get("_tipo") == "CASO_CONFIRMADO_IA" else PLANTILLA
    for i, p in enumerate(params, 1):
        texto = texto.replace("{%d}" % i, p)
    return texto


class ConsoleClient:
    def send(self, payload):
        cuerpo = render_preview(payload).replace("\n", "\n      │ ")
        log.info("WhatsApp (SIMULADO, no se envía) a +%s:\n      │ %s", payload["to"], cuerpo)
        return f"console-{uuid.uuid4()}"


class CloudApiClient:
    """WhatsApp Cloud API: POST https://graph.facebook.com/<versión>/<phone-number-id>/messages."""

    def __init__(self, token=None, phone_id=None, version=None, timeout=15):
        self.token = token or settings.WHATSAPP_TOKEN
        self.phone_id = phone_id or settings.WHATSAPP_PHONE_ID
        self.version = version or settings.WHATSAPP_GRAPH_VERSION
        self.timeout = timeout
        if not (self.token and self.phone_id and self.version):
            raise WhatsAppError("Faltan WHATSAPP_TOKEN, WHATSAPP_PHONE_ID o WHATSAPP_GRAPH_VERSION", retryable=False)

    def send(self, payload):
        import requests

        payload = {k: v for k, v in payload.items() if not k.startswith("_")}  # «_tipo» es solo para la consola
        url = f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages"
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout,
                                 headers={"Authorization": f"Bearer {self.token}"})
        except requests.RequestException as exc:
            raise WhatsAppError(f"Red: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise WhatsAppError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:  # número inválido, plantilla no aprobada, token vencido…: no se reintenta solo
            raise WhatsAppError(f"HTTP {resp.status_code}: {resp.text[:300]}", retryable=False)
        return resp.json()["messages"][0]["id"]


def get_client():
    return import_string(settings.WHATSAPP_CLIENT)()
