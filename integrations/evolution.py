import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppEvolutionExecutor:
    """
    Envia mensagem WhatsApp via Evolution API.

    Recebe o payload já renderizado (dict com ``number`` e ``text``), lê a URL base e a
    chave de API das settings, e faz o POST para ``/message/sendText/{instance}``.
    """

    def __init__(self, *, base_url=None, api_key=None):
        self.base_url = (base_url or settings.EVOLUTION_API_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.EVOLUTION_API_GLOBAL_KEY

    def send(self, instance_name: str, rendered_payload: dict) -> dict:
        if not isinstance(rendered_payload, dict):
            raise ValueError("Payload WhatsApp tem de ser um dicionário.")

        number = rendered_payload.get("number")
        text = rendered_payload.get("text")
        if number is None or text is None:
            raise ValueError(
                "O payload renderizado tem de incluir as chaves 'number' e 'text'."
            )

        endpoint = f"{self.base_url}/message/sendText/{instance_name}"
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key,
        }
        body = {
            "number": number,
            "options": {
                "delay": 1500,
                "presence": "composing",
            },
            "textMessage": {
                "text": str(text),
            },
        }

        response = requests.post(endpoint, json=body, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()


def send_whatsapp_message(instance_name, number, message_text):
    """
    Atalho retrocompatível: monta o payload renderizado e delega ao executor.
    """
    return WhatsAppEvolutionExecutor().send(
        instance_name,
        {"number": number, "text": message_text},
    )
