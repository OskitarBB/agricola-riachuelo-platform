"""WhatsApp Cloud API clients.

The console client is the default for development so the worker can be tested
without sending real messages.
"""
import logging

import requests
from django.conf import settings


log = logging.getLogger(__name__)


class WhatsAppError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class ConsoleClient:
    """Development client: log the payload and pretend it was accepted."""

    def send_template(self, payload):
        log.info("WhatsApp console payload: %s", payload)
        return {"messages": [{"id": "console-message"}]}


class CloudApiClient:
    """Small wrapper around Meta Graph API for template messages."""

    def __init__(self, token=None, phone_id=None, graph_version=None):
        self.token = token or settings.WHATSAPP_TOKEN
        self.phone_id = phone_id or settings.WHATSAPP_PHONE_ID
        self.graph_version = graph_version or settings.WHATSAPP_GRAPH_VERSION

    def send_template(self, payload):
        if not self.token or not self.phone_id:
            raise WhatsAppError("WhatsApp credentials are missing", retryable=False)
        url = f"https://graph.facebook.com/{self.graph_version}/{self.phone_id}/messages"
        response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
        if response.status_code >= 400:
            raise WhatsAppError(f"HTTP {response.status_code}: {response.text}", retryable=response.status_code >= 500)
        return response.json()


def get_client():
    dotted = settings.WHATSAPP_CLIENT
    if dotted.endswith("ConsoleClient"):
        return ConsoleClient()
    return CloudApiClient()
