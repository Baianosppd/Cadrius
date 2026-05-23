import logging
import imapclient

from django.utils import timezone
from django.db import IntegrityError

from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

# --- Importações das Nossas Apps ---
from emails.models import MailBox, EmailMessage
from workflows.models import Workflow
from workflows.tasks import execute_workflow_pipeline

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
