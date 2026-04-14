import os
import logging
import json
import re
import requests
import imapclient 

from django.utils import timezone
from django.db import IntegrityError
from django_q.tasks import async_task

from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

# --- Importações das Nossas Apps ---
from emails.models import MailBox, EmailMessage
from billing.decorators import check_quota_limit
from workflows.models import Workflow, Action, ExecutionLog
from integrations.evolution import send_whatsapp_message  # <-- Importação adicionada para o WhatsApp

from extraction.ai_wrapper import extract_fields_from_text
from extraction.models import ExtractionProfile
from extraction import schemas as extraction_schemas

logger = logging.getLogger(__name__)

# =====================================================================
# 1. HELPERS E FUNÇÕES DE EMAIL (IMAP)
# =====================================================================

def _decode_str(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value

def _to_aware(dt):
    if dt is None:
        return timezone.now()
    try:
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except Exception:
        return timezone.now()

def _extract_body(email_obj):
    try:
        if email_obj.is_multipart():
            for part in email_obj.walk():
                ctype = (part.get_content_type() or "").lower()
                disp = (part.get_content_disposition() or "").lower()
                if ctype == "text/plain" and "attachment" not in disp:
                    return (part.get_content() or "").strip()
            for part in email_obj.walk():
                if (part.get_content_type() or "").lower().startswith("text/"):
                    return (part.get_content() or "").strip()
            return ""
        return (email_obj.get_content() or "").strip()
    except Exception:
        return ""

def fetch_emails(mailbox_id) -> int: 
    """
    Lê emails via IMAP e cria EmailMessage para cada mensagem nova.
    """
    try:
        mailbox_id = int(mailbox_id)
    except (ValueError, TypeError):
        logger.error(f"[fetch_emails] ID inválido recebido: {mailbox_id}")
        return 0
        
    server = None
    total_created = 0

    try:
        mailbox = MailBox.objects.get(id=mailbox_id)

        username = mailbox.username
        password = mailbox.password
        host = mailbox.imap_host
        port = mailbox.imap_port or 993
        folder = "INBOX"

        if not host or not username or not password:
            logger.error(f"[fetch_emails] MailBox {mailbox_id} incompleta.")
            return 0

        # ---- Conexão IMAP ----
        server = imapclient.IMAPClient(host, ssl=True, port=port, timeout=30)
        server.login(username, password)
        server.select_folder(folder, readonly=True)

        # Busca apenas os não lidos para simplificar
        uids = server.search(['UNSEEN'])

        if not uids:
            mailbox.last_fetch_at = timezone.now()
            mailbox.save(update_fields=["last_fetch_at"])
            return 0

        fetched = server.fetch(uids, ['RFC822', 'ENVELOPE'])

        for uid in uids:
            try:
                data = fetched.get(uid)
                if not data:
                    continue

                raw_bytes = data.get(b'RFC822') or data.get('RFC822')
                if not raw_bytes:
                    continue

                msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

                message_id = (msg.get('Message-Id') or msg.get('Message-ID') or f"<uid-{int(uid)}@{host}>").strip()
                subject = _decode_str(msg.get('Subject')) or "(sem assunto)"
                from_addr = _decode_str(msg.get('From'))
                date_hdr = msg.get('Date')

                try:
                    dt = parsedate_to_datetime(date_hdr) if date_hdr else None
                except Exception:
                    dt = None
                date_aware = _to_aware(dt)

                body_text = _extract_body(msg)

                # Salva o email no banco. is_dispatched começa como False por padrão.
                try:
                    EmailMessage.objects.create(
                        mailbox=mailbox,
                        message_id=message_id,
                        subject=subject,
                        sender=from_addr,
                        received_at=date_aware,
                        body_text=body_text
                    )
                    total_created += 1
                except IntegrityError:
                    logger.info(f"Email duplicado (uid={uid}) - ignorando.")
                    continue

            except Exception as e:
                logger.exception(f"Erro ao processar UID {uid}: {e}")

        mailbox.last_fetch_at = timezone.now()
        mailbox.save(update_fields=["last_fetch_at"])
        return total_created

    except Exception as e:
        logger.exception(f"[fetch_emails] Erro inesperado MailBox {mailbox_id}: {e}")
        return 0
    finally:
        try:
            if server is not None:
                server.logout()
        except Exception:
            pass

def process_email(email_id, profile_id, workflow_id):
    """
    O Coração da Hiperautomação: 
    1. Lê o e-mail bruto.
    2. Passa para a IA extrair e formatar (Pydantic).
    3. Envia o JSON estruturado para o motor de workflows (Trello/WhatsApp).
    """
    try:
        email_obj = EmailMessage.objects.get(id=email_id)
        profile = ExtractionProfile.objects.get(id=profile_id)
        workflow = Workflow.objects.get(id=workflow_id)
        
        logger.info(f"🧠 [Workflow {workflow.name}] A iniciar leitura IA para o E-mail ID {email_id}...")
        
        # 1. Busca dinamicamente qual a classe Pydantic que o utilizador escolheu no painel
        schema_class = getattr(extraction_schemas, profile.pydantic_schema_name, None)
        if not schema_class:
            raise ValueError(f"Schema {profile.pydantic_schema_name} não encontrado no sistema.")
            
        # 2. Chama o Motor Universal de IA (OpenAI / Groq / Gemini)
        extracted_json = extract_fields_from_text(
            text=email_obj.body_text,
            schema=schema_class,
            prompt_template=profile.system_prompt_template,
            provider=profile.ai_provider
        )
        
        if not extracted_json:
            logger.error(f"❌ [Workflow {workflow.name}] A IA falhou a extrair os dados (Erro de Schema/Timeout).")
            return
            
        logger.info(f"✅ [Workflow {workflow.name}] IA extraiu o JSON com sucesso! A enviar para a Ação...")
        
        # 3. Marca o e-mail como processado
        email_obj.is_dispatched = True
        email_obj.save(update_fields=['is_dispatched'])
        

        execute_workflow_pipeline(workflow_id=workflow.id, payload=extracted_json)

    except EmailMessage.DoesNotExist:
        logger.error(f"E-mail {email_id} não encontrado.")
    except Exception as e:
        logger.exception(f"Erro crítico no processamento de IA do e-mail {email_id}: {e}")


# =====================================================================
# 2. MOTOR DE WORKFLOWS (HIPERAUTOMAÇÃO)
# =====================================================================

def parse_dynamic_variables(template_str, payload):
    """
    Procura por padrões {{chave}} no template e substitui pelo valor do JSON original.
    Suporta aninhamento. Ex: {{cliente.nome}}
    """
    if not template_str:
        return ""
        
    def replacer(match):
        keys = match.group(1).strip().split('.')
        value = payload
        try:
            for key in keys:
                value = value[key]
            return str(value)
        except (KeyError, TypeError):
            # Se a variável não existir no webhook recebido, mantém a original
            return match.group(0) 

    return re.sub(r'\{\{(.*?)\}\}', replacer, template_str)


@check_quota_limit  # <-- Freio comercial B2B (verifica limites de IA e Uso)
def execute_workflow_pipeline(workflow_id, payload):
    """
    A task independente isolada pelo Django-Q.
    Recebe o ID e o payload, monta a requisição e atira para o mundo exterior.
    """
    workflow = Workflow.objects.get(id=workflow_id)
    
    # Criamos o registo inicial da execução (Pendente)
    exec_log = ExecutionLog.objects.create(
        workflow=workflow,
        status='PENDING_REVIEW', # Status válido na nossa model
        trigger_payload=payload  # <-- O NOME CORRETO DO CAMPO!
    )

    try:
        # Pega na ação vinculada a este workflow
        action = Action.objects.get(workflow=workflow)
        
        # 1. Carregar e substituir o payload template definido pelo utilizador
        final_payload_str = parse_dynamic_variables(action.payload_template, payload)
        
        # Converte de volta para dicionário se for um JSON válido
        try:
            final_data = json.loads(final_payload_str) if final_payload_str else payload
        except json.JSONDecodeError:
            final_data = final_payload_str  # Se for text/plain ou outro formato

        # ======================================================
        # 2. ROTEAMENTO DE AÇÕES (Webhook vs Nativo)
        # ======================================================
        
        if action.action_type == 'WHATSAPP_EVOLUTION':
            # Disparo via Evolution API
            if isinstance(final_data, dict) and 'number' in final_data and 'text' in final_data:
                instance_name = f"instancia_org_{workflow.organization.id}" 
                
                resp_data = send_whatsapp_message(
                    instance_name=instance_name,
                    number=final_data['number'],
                    message_text=final_data['text']
                )
                exec_log.response_data = json.dumps(resp_data)
            else:
                raise ValueError("Payload template para WhatsApp inválido. O JSON deve conter 'number' e 'text'.")

        elif action.action_type == 'WEBHOOK' or action.action_type == '':
            # Disparo genérico para CRMs (Astrea, Projuris, etc)
            headers = {}
            if action.headers:
                headers = json.loads(action.headers)
            
            response = requests.request(
                method=action.method.upper() if action.method else 'POST',
                url=action.endpoint_url,
                json=final_data if isinstance(final_data, dict) else None,
                data=final_data if not isinstance(final_data, dict) else None,
                headers=headers,
                timeout=15 
            )
            
            response.raise_for_status() # Lança erro se for 4xx ou 5xx
            exec_log.response_data = response.text
            
        else:
            raise ValueError(f"Tipo de Action '{action.action_type}' não suportada.")

        # 3. Marca como Sucesso
        exec_log.status = 'SUCCESS'
        exec_log.save()
        
    except requests.exceptions.RequestException as e:
        # Falha de rede ou de API externa
        exec_log.status = 'FAILED'
        exec_log.error_message = f"Erro na requisição externa: {str(e)}"
        exec_log.save()
        
    except Exception as e:
            
        exec_log.status = 'FAILED' 
        exec_log.error_message = f"Erro interno do Cadrius: {str(e)}"
        exec_log.save()



