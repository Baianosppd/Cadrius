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
        # Evolution v2 (a que o Cadrius hospeda) lê "text" na raiz; a v1 lia "textMessage.text". Mandamos os dois (CAD-225).
        body = {
            "number": number,
            "text": str(text),
            "delay": 1500,
            "options": {
                "delay": 1500,
                "presence": "composing",
            },
            "textMessage": {
                "text": str(text),
            },
        }

        response = requests.post(endpoint, json=body, headers=headers, timeout=10)
        if response.status_code >= 400:
            raise WhatsAppSendError(_friendly_error(response, number))
        return response.json()


class WhatsAppSendError(Exception):
    """Falha de envio com motivo legível (vai para a execução da regra, sem dados da mensagem)."""


def _friendly_error(response, number) -> str:
    """Traduz a resposta de erro da Evolution em algo que o escritório entende (CAD-229)."""
    try:
        detail = response.json()
    except ValueError:
        detail = {}
    raw = str(detail)[:300]
    code = response.status_code
    logger.warning("Evolution recusou o envio (%s)", code)   # sem o corpo: ele traz o número do cliente
    if "'exists': False" in raw or '"exists": false' in raw:
        return f"O número final {str(number)[-4:]} não tem WhatsApp. Confira o telefone do contato."
    if code in (401, 403):
        return "O servidor de WhatsApp recusou a chave de acesso (EVOLUTION_API_GLOBAL_KEY)."
    if code == 404:
        return "O WhatsApp do escritório não está conectado neste servidor. Conecte de novo em Integrações."
    if "Connection Closed" in raw or "not connected" in raw.lower() or "close" in raw.lower():
        return "O WhatsApp do escritório está desconectado. Reconecte em Integrações (QR code ou código)."
    return f"O servidor de WhatsApp recusou o envio ({code})."


def send_whatsapp_message(instance_name, number, message_text):
    """
    Atalho retrocompatível: monta o payload renderizado e delega ao executor.
    """
    return WhatsAppEvolutionExecutor().send(
        instance_name,
        {"number": number, "text": message_text},
    )
