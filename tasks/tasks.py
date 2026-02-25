import os
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import IntegrityError
from django_q.tasks import async_task
import imapclient 
from extraction.schemas import ProcessoJuridicoSchema, ServiceOrderSchema, SupportRequestSchema 

from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

# --- IMPORTS ATUALIZADOS ---
# Importa os modelos, incluindo o novo AutomationRule
from emails.models import MailBox, EmailMessage, EmailStatus, AutomationRule 
# Importa a lógica de processamento e os wrappers
from integrations.telegram import notify_telegram 
from extraction.ai_wrapper import extract_fields_from_text 
# Importa o modelo de perfil de Juliano
from extraction.models import ExtractionProfile 

logger = logging.getLogger(__name__)


# NOVO: Mapeamento para buscar a classe do schema pelo nome
SCHEMA_MAP = {
    'ProcessoJuridicoSchema': ProcessoJuridicoSchema,
    'ServiceOrderSchema': ServiceOrderSchema,
    'SupportRequestSchema': SupportRequestSchema,
    # Adicionar novos schemas aqui
}



# -------------------------------------------------------------------
# Wrapper: mantém o NOME notify_telegram, mas aceita assinaturas diferentes
# notify_telegram("texto")  | notify_telegram(message="texto")
# notify_telegram(chat_id, "texto") usando settings.TELEGRAM_CHAT_ID
# -------------------------------------------------------------------
_notify_orig = notify_telegram 
def notify_telegram(*args, **kwargs):
    """
    Wrapper compatível:
    - aceita notify_telegram("texto")
    - aceita notify_telegram(message="texto")
    - aceita notify_telegram(chat_id, "texto")
    - aceita notify_telegram(email_msg=..., message="texto")
    """
    # importa settings localmente para não mexer nos imports do topo
    try:
        from django.conf import settings as _settings
    except Exception:
        _settings = None

    # tenta chamar do jeito que receberam
    try:
        return _notify_orig(*args, **kwargs)
    except TypeError:
        pass

    # extrai uma mensagem de fallback
    msg = kwargs.get("message")
    if not msg:
        if len(args) == 1 and isinstance(args[0], str):
            msg = args[0]
        elif len(args) >= 2 and isinstance(args[1], str):
            msg = args[1]
        else:
            msg = "Notificação"

    # tenta assinaturas alternativas
    try:
        return _notify_orig(msg)  # notify_telegram("texto")
    except TypeError:
        pass
    try:
        return _notify_orig(message=msg)  # notify_telegram(message="texto")
    except TypeError:
        pass
    try:
        chat_id = getattr(_settings, "TELEGRAM_CHAT_ID", None) if _settings else None
        if chat_id:
            return _notify_orig(chat_id, msg)  # notify_telegram(chat_id, "texto")
    except Exception:
        pass

    logger.warning("Falha ao notificar no Telegram: %s", msg)
    return None


# ----------------- Helpers -----------------
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
    """Prefere text/plain; fallback para qualquer text/*."""
    try:
        if email_obj.is_multipart():
            for part in email_obj.walk():
                ctype = (part.get_content_type() or "").lower()
                disp = (part.get_content_disposition() or "").lower()
                if ctype == "text/plain" and "attachment" not in disp:
                    return (part.get_content() or "").strip()
            # fallback text/*
            for part in email_obj.walk():
                if (part.get_content_type() or "").lower().startswith("text/"):
                    return (part.get_content() or "").strip()
            return ""
        return (email_obj.get_content() or "").strip()
    except Exception:
        return ""

def _safe_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default

def _model_has_field(model_cls, field_name: str) -> bool:
    try:
        return any(getattr(f, "name", None) == field_name for f in model_cls._meta.get_fields())
    except Exception:
        return False


# ----------------- Atualiza checkpoint -----------------
def _touch_mailbox_checkpoint(mailbox: MailBox, processed_uids):
    update_fields = []

    # marca o momento do último fetch
    if hasattr(mailbox, "last_checked"):
        mailbox.last_checked = timezone.now()
        update_fields.append("last_checked")
    elif hasattr(mailbox, "last_fetch_at"):
        mailbox.last_fetch_at = timezone.now()
        update_fields.append("last_fetch_at")

    # avança last_uid, se existir e houver UIDs processados
    if processed_uids and hasattr(mailbox, "last_uid"):
        try:
            mailbox.last_uid = max([x for x in processed_uids if x is not None])
            if "last_checked" not in update_fields and hasattr(mailbox, "last_checked"):
                update_fields.append("last_checked")
            if "last_fetch_at" not in update_fields and hasattr(mailbox, "last_fetch_at"):
                update_fields.append("last_fetch_at")
        except Exception:
            pass

    if update_fields:
        try:
            mailbox.save(update_fields=update_fields)
        except Exception as e:
            logger.warning("Falha ao atualizar checkpoint da MailBox %s: %s", mailbox.id, e)


# ----------------- FUNÇÃO PRINCIPAL -----------------
def fetch_emails(mailbox_id) -> int: 
    """
    Lê emails via IMAP e cria EmailMessage para cada mensagem nova.
    - Argumento (mailbox_id) vem como string do Django-Q Schedule.
    """
    # NOVO: Garante que o ID seja um inteiro, se o Django-Q passar como string
    try:
        mailbox_id = int(mailbox_id)
    except (ValueError, TypeError):
        msg = f"[fetch_emails] ID inválido recebido: {mailbox_id}"
        logger.error(msg)
        notify_telegram(msg)
        return 0
        
    server = None
    processed_uids = []
    total_created = 0

    try:
        mailbox = MailBox.objects.get(id=mailbox_id)

        # ---- Campos reais do seu modelo ----
        
        username = getattr(mailbox, "username", None) or getattr(mailbox, "imap_username", None)
        password = (
            getattr(mailbox, "password", None)
            or getattr(mailbox, "imap_password", None)
            or getattr(mailbox, "app_password", None)
        )
        host = getattr(mailbox, "imap_host", None) or getattr(mailbox, "host", None)
        port = getattr(mailbox, "imap_port", None) or getattr(mailbox, "port", None) or 993
        use_ssl = True if not hasattr(mailbox, "use_ssl") else bool(getattr(mailbox, "use_ssl", True))
        folder = getattr(mailbox, "folder", None) or "INBOX"
        last_uid = getattr(mailbox, "last_uid", None)

        # ---- OVERRIDE via variáveis de ambiente ----
        env_host = os.getenv("IMAP_HOST")
        env_port = os.getenv("IMAP_PORT")
        env_user = os.getenv("IMAP_USERNAME")
        env_pass = os.getenv("IMAP_PASSWORD")

        if env_host:
            host = env_host
        if env_port:
            try:
                port = int(env_port)
            except Exception:
                pass
        if env_user:
            username = env_user
        if env_pass:
            password = env_pass.replace(" ", "")  # remove espaços da app password do Gmail

        # validação
        if not host or not username or not password:
            msg = f"[fetch_emails] MailBox {mailbox_id} incompleta: host/username/password ausentes."
            logger.error(msg)
            notify_telegram(msg)
            return 0

        # ---- Conexão IMAP ----
        server = imapclient.IMAPClient(host, ssl=use_ssl, port=port, timeout=30)
        server.login(username, password)
        server.select_folder(folder, readonly=True)

        # ---- Estratégia de busca ----
        uids = []
        if last_uid is not None:
            try:
                uids = server.search(['UID', f'{int(last_uid) + 1}:*'])
            except Exception as e:
                logger.warning("[fetch_emails] Falha search por UID em MailBox %s: %s", mailbox_id, e)

        if not uids:
            try:
                uids = server.search(['UNSEEN'])
            except Exception as e:
                logger.warning("[fetch_emails] Falha search UNSEEN em MailBox %s: %s", mailbox_id, e)

        if not uids:
            try:
                all_uids = server.search(['ALL'])
                all_uids.sort()
                uids = all_uids[-50:]  # fallback seguro
            except Exception as e:
                logger.error("[fetch_emails] Falha search ALL em MailBox %s: %s", mailbox_id, e)
                uids = []

        if not uids:
            _touch_mailbox_checkpoint(mailbox, processed_uids=False)
            return 0

        # ---- Busca em lotes ----
        BATCH_SIZE = 200
        for i in range(0, len(uids), BATCH_SIZE):
            batch = uids[i:i+BATCH_SIZE]
            fetched = server.fetch(batch, ['RFC822', 'UID', 'FLAGS', 'ENVELOPE'])

            for uid in batch:
                try:
                    data = fetched.get(uid)
                    if not data:
                        continue

                    raw_bytes = data.get(b'RFC822') or data.get('RFC822') \
                                or data.get(b'BODY[]') or data.get('BODY[]')
                    if not raw_bytes:
                        logger.warning("UID %s sem corpo (RFC822/BODY[] ausentes) na MailBox %s", uid, mailbox_id)
                        continue

                    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

                    message_id = (msg.get('Message-Id') or msg.get('Message-ID') or "").strip() or None
                    subject = _decode_str(msg.get('Subject'))
                    from_addr = _decode_str(msg.get('From'))
                    to_addr = _decode_str(msg.get('To'))
                    date_hdr = msg.get('Date')

                    try:
                        dt = parsedate_to_datetime(date_hdr) if date_hdr else None
                    except Exception:
                        dt = None
                    date_aware = _to_aware(dt)

                    body_text = _extract_body(msg)

                    # Deduplicação por Message-ID (se o modelo tiver)
                    if message_id and _model_has_field(EmailMessage, "message_id"):
                        try:
                            qs = EmailMessage.objects.filter(message_id=message_id)
                            if _model_has_field(EmailMessage, "mailbox"):
                                qs = qs.filter(mailbox=mailbox)
                            if qs.exists():
                                processed_uids.append(_safe_int(uid))
                                continue
                        except Exception:
                            pass

                    # Monta payload respeitando campos existentes
                    # --- garante message_id não-nulo (alguns emails vêm sem) ---
                    if not message_id:
                        message_id = f"<uid-{int(uid)}@{host}>"

                    # --- Monta payload respeitando os campos do seu modelo ---
                    payload = {}

                    # FK para a mailbox
                    if _model_has_field(EmailMessage, "mailbox"):
                        payload["mailbox"] = mailbox

                    # IDs / cabeçalhos
                    if _model_has_field(EmailMessage, "message_id"):
                        payload["message_id"] = message_id

                    if _model_has_field(EmailMessage, "subject"):
                        payload["subject"] = subject or "(sem assunto)"

                    # REMAPEIA 'From' para o campo obrigatório 'sender'
                    if _model_has_field(EmailMessage, "sender"):
                        payload["sender"] = from_addr
                    elif _model_has_field(EmailMessage, "from_addr"):
                        payload["from_addr"] = from_addr  # caso exista também

                    # REMAPEIA a data para o campo obrigatório 'received_at'
                    if _model_has_field(EmailMessage, "received_at"):
                        payload["received_at"] = date_aware
                    elif _model_has_field(EmailMessage, "date"):
                        payload["date"] = date_aware

                    # Corpo
                    if _model_has_field(EmailMessage, "body_text"):
                        payload["body_text"] = body_text or ""

                    # UID (se existir no modelo)
                    if _model_has_field(EmailMessage, "uid"):
                        payload["uid"] = _safe_int(uid)

                    # Status (se existir e houver enum)
                    if _model_has_field(EmailMessage, "status"):
                        try:
                            status_value = getattr(EmailStatus, "RECEIVED", None) or getattr(EmailStatus, "received", None)
                            if status_value is not None:
                                payload["status"] = status_value
                        except Exception:
                            pass

                    # timestamps obrigatórios (se o modelo não usar auto_now/auto_now_add)
                    now = timezone.now()
                    if _model_has_field(EmailMessage, "created_at"):
                        payload["created_at"] = now
                    if _model_has_field(EmailMessage, "updated_at"):
                        payload["updated_at"] = now

                    try:
                        email_msg = EmailMessage.objects.create(**payload)
                        total_created += 1
                        processed_uids.append(_safe_int(uid))
                        # Enfileira o processamento para a próxima etapa (Juliano/Thales)
                        async_task('tasks.tasks.process_email', email_msg.id)
                    except IntegrityError:
                        logger.info("Email duplicado (uid=%s, mailbox=%s) - ignorando.", uid, mailbox_id)
                        processed_uids.append(_safe_int(uid))
                        continue
                    except Exception as e:
                        logger.exception("Falha ao criar EmailMessage (UID %s MailBox %s): %s", uid, mailbox_id, e)
                        notify_telegram(f"[fetch_emails] Falha ao salvar email UID {uid} MailBox {mailbox_id}: {e}")
                        continue

                except Exception as e:
                    logger.exception("Erro ao processar UID %s na MailBox %s: %s", uid, mailbox_id, e)
                    notify_telegram(f"[fetch_emails] Erro UID {uid} MailBox {mailbox_id}: {e}")

        _touch_mailbox_checkpoint(mailbox, processed_uids=processed_uids)
        return total_created

    except MailBox.DoesNotExist:
        msg = f"[fetch_emails] MailBox {mailbox_id} não encontrada."
        logger.error(msg)
        notify_telegram(msg)
        return 0
    except imapclient.exceptions.IMAPClientError as e:
        msg = f"[fetch_emails] IMAPClientError MailBox {mailbox_id}: {e}"
        logger.error(msg)
        notify_telegram(msg)
        return 0
    except Exception as e:
        msg = f"[fetch_emails] Erro inesperado MailBox {mailbox_id}: {e}"
        logger.exception(msg)
        notify_telegram(msg)
        return 0
    finally:
        try:
            if server is not None:
                server.logout()
        except Exception:
            pass


# --- FUNÇÃO PRINCIPAL DO PIPELINE (THALES) ---

def process_email(email_id):
    """
    Worker principal: coordena a extração de IA e as integrações externas.
    Agora usa o modelo AutomationRule para definir o fluxo dinamicamente.
    """
    try:
        email = EmailMessage.objects.get(pk=email_id)
        
        # 1. ATUALIZA STATUS INICIAL
        email.status = EmailStatus.PROCESSING
        email.processing_attempts += 1
        email.save()
        
        # 2. BUSCA E AVALIA AS REGRAS DE AUTOMAÇÃO
        
        # Busca todas as regras ativas para a MailBox, ordenadas por prioridade
        rules = AutomationRule.objects.filter(
            mailbox=email.mailbox, 
            is_active=True
        ).order_by('priority')

        matched_rule = None
        for rule in rules:
            # Lógica de correspondência de assunto
            subject_match = True
            if rule.subject_contains and rule.subject_contains.strip():
                if rule.subject_contains.lower() not in email.subject.lower():
                    subject_match = False
            
            # Lógica de correspondência de remetente
            sender_match = True
            if rule.sender_contains and rule.sender_contains.strip():
                if rule.sender_contains.lower() not in email.sender.lower():
                    sender_match = False
                    
            if subject_match and sender_match:
                matched_rule = rule
                logger.info(f"Regra de Automação correspondente encontrada: {rule.name}")
                break
        
        if not matched_rule:
            # Não encontrou regra, ignora e marca como pendente (ou adiciona status 'IGNORED')
            email.status = EmailStatus.PENDING 
            email.save()
            logger.info(f"Nenhuma regra de automação correspondente encontrada para o email ID: {email.id}")
            return
            
        # 3. EXTRAÇÃO DE DADOS (Juliano) usando o perfil da regra
        profile = matched_rule.extraction_profile
        if not profile:
            msg = f"Regra '{matched_rule.name}' não possui Perfil de Extração. Requer Revisão."
            logger.error(msg)
            email.status = EmailStatus.REQUIRES_REVIEW
            email.save()
            notify_telegram(email_msg=email, message=msg)
            return

        schema_cls = SCHEMA_MAP.get(profile.pydantic_schema_name)
        if not schema_cls:
            msg = f"Schema '{profile.pydantic_schema_name}' não encontrado no mapeamento. Falha Crítica."
            logger.error(msg)
            email.status = EmailStatus.FAILED
            email.save()
            notify_telegram(email_msg=email, message=msg)
            return
            
        # Usa o prompt template do DB
        dynamic_prompt = profile.system_prompt_template.format(
            data_atual=timezone.now().strftime('%d/%m/%Y')
        )

        logger.info(f"Iniciando extração IA para email ID: {email.id} usando perfil: {profile.name}")
        
        extracted_data = extract_fields_from_text(
            text=email.body_text,
            schema=schema_cls, 
            prompt_template=dynamic_prompt, 
            examples=[]
        )
        
        if extracted_data is None:
            email.status = EmailStatus.REQUIRES_REVIEW
            email.save()
            notify_telegram(email_msg=email, message=f"Revisão necessária para email ID: {email.id}. Extração IA falhou para perfil '{profile.name}'.")
            return

        email.extracted_data = extracted_data
        email.status = EmailStatus.EXTRACTED
        email.save()
        
        # 4. INTEGRAÇÕES (Thales) - Chamada de Integrações
        
        logger.info(f"Iniciando notificação Telegram para email ID: {email.id}")
        
        # Formatação de Mensagem (Adaptação para o Processo Jurídico ou Genérico)
        
        if profile.pydantic_schema_name == 'ProcessoJuridicoSchema':
            proc_numero = extracted_data.get('numero_processo', 'N/A')
            movimento = extracted_data.get('resumo_movimentacao', 'Sem resumo.')
            sugestao = extracted_data.get('sugestao_proximo_passo', 'Revisão manual necessária.')
            prazo = extracted_data.get('prazo_fatal', None)

            prazo_formatado = f"*{prazo}*" if prazo else "_Não identificado_"

            message = (
                f"⚖️ **Nova Movimentação Processual (Regra: {matched_rule.name})**\n\n"
                f"**Processo:** `{proc_numero}`\n"
                f"**Assunto do E-mail:** {email.subject}\n\n"
                f"**Resumo da IA:**\n_{movimento}_\n\n"
                f"**Prazo Fatal:** {prazo_formatado}\n\n"
                f"**➡️ Próximo Passo Sugerido:**\n`{sugestao}`"
            )
        else:
            document_type = extracted_data.get('document_type', 'Dados Extraídos')
            confidence = extracted_data.get('confidence_score', 'N/A')
            
            message = (
                f"✅ **Extração Concluída ({document_type}) - Regra: {matched_rule.name}**\n\n"
                f"**Assunto:** {email.subject}\n"
                f"**Confiança da IA:** {confidence}%\n\n"
                f"Dados extraídos salvos para processamento adicional."
            )
            
        notify_telegram(email_msg=email, message=message)   
             
        # 5. FINALIZAÇÃO
        email.status = EmailStatus.INTEGRATED 
        email.last_processed_at = timezone.now()
        email.save()
        
    except EmailMessage.DoesNotExist:
        logger.error(f"EmailMessage {email_id} não encontrado.")
    except Exception as e:
        # Lógica de erro: marcar como FAILED e logar
        try:
            email.status = EmailStatus.FAILED
            email.save()
            logger.exception(f"Erro crítico no processamento do email {email_id}: {e}")
            notify_telegram(email_msg=email, message=f"⚠️ Erro Crítico no pipeline para email ID: {email.id}. Detalhes: {e}")
        except Exception:
            logger.exception(f"Erro duplo no processamento e no logging do email {email_id}")