import requests
import os
import json
import logging
from .models import IntegrationLog
from emails.models import EmailMessage # Apenas para typing/FK
from integrations.models import IntegrationLog, IntegrationStatus 

logger = logging.getLogger(__name__)

# Configurações lidas do .env
TRELLO_BASE_URL = "https://api.trello.com/1"
TRELLO_AUTH = {
    'key': os.environ.get('TRELLO_API_KEY'),
    'token': os.environ.get('TRELLO_API_TOKEN'),
}
TRELLO_LIST_ID = os.environ.get('TRELLO_LIST_ID')


TRELLO_BASE_URL = "https://api.trello.com/1"
# TRELLO_AUTH e TRELLO_LIST_ID são removidos, pois serão lidos por chamada


def create_trello_card(email_msg: EmailMessage, extracted_data: dict) -> dict:
    """
    Cria um novo card no Trello usando dados extraídos e registra o log.
    (Agora lê as credenciais do DB via MailBox.integration_config)
    """
    # NOVO: Busca a configuração de integração da MailBox
    config = email_msg.mailbox.integration_config
    if not config:
        logger.error(f"MailBox {email_msg.mailbox.id} não possui IntegrationConfig.")
        raise ValueError("Configuração de Integração Externa não encontrada.")

    # --- LEIA AS CREDENCIAIS DO DB ---
    trello_auth = {
        'key': config.trello_api_key,
        'token': config.trello_api_token,
    }
    list_id = config.trello_list_id
    
    if not trello_auth['key'] or not trello_auth['token'] or not list_id:
        logger.error(f"Credenciais Trello incompletas para config: {config.name}")
        raise ValueError("Credenciais Trello não configuradas.")

    log = IntegrationLog.objects.create(
        email_message=email_msg,
        service='TRELLO',
        status=IntegrationStatus.PENDING,
        request_data=extracted_data
    )
    
    # ... (Mapeamento do JSON da IA para o Trello é mantido)
    
    payload = {
        'idList': list_id, # Usa o ID do DB
        'name': card_name,
        'desc': card_desc,
        'pos': 'top',
        **trello_auth # Usa a autenticação do DB
    }
    log.request_data['trello_payload'] = payload # Atualiza o log com o payload exato
    
    try:
        response = requests.post(
            f"{TRELLO_BASE_URL}/cards",
            params=payload,
            timeout=10
        )
        response.raise_for_status()
        
        # Sucesso
        response_json = response.json()
        log.status = IntegrationStatus.SUCCESS
        log.response_code = response.status_code
        log.response_body = response_json
        log.save()
        
        logger.info(f"Card Trello criado: {response_json.get('url')}")
        return response_json
        
    except requests.exceptions.RequestException as e:
        # Falha (Timeout, HTTP Error, etc.)
        status_code = getattr(e.response, 'status_code', 500)
        error_details = str(e)
        
        log.status = IntegrationStatus.FAILED
        log.response_code = status_code
        log.response_body = {"error": error_details, "payload": payload}
        log.save()
        
        logger.error(f"Falha ao criar card Trello (Status {status_code}): {error_details}")
        # Thales: Aqui você pode disparar um retry da tarefa Celery/Django-Q.
        raise # Re-lança para que o worker saiba que a tarefa falhou

# Thales: Implementar função de mock/teste para CI/local sem chave real.