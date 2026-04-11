import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_whatsapp_message(instance_name, number, message_text):
    """
    Dispara uma mensagem de WhatsApp usando a Evolution API local.
    """
    # Ex: http://localhost:8080/message/sendText/InstanciaEscritorio
    endpoint = f"{settings.EVOLUTION_API_BASE_URL}/message/sendText/{instance_name}"
    
    headers = {
        "Content-Type": "application/json",
        "apikey": settings.EVOLUTION_API_GLOBAL_KEY
    }
    
    payload = {
        "number": number,
        "options": {
            "delay": 1500, # Simula o tempo de digitação (1.5s)
            "presence": "composing" 
        },
        "textMessage": {
            "text": message_text
        }
    }
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar WhatsApp pela Evolution API: {e}")
        raise Exception(f"Falha na Evolution API: {str(e)}")