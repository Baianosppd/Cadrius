import os
import logging
from django.utils import timezone
from django.db import IntegrityError
from django_q.tasks import async_task
import imapclient 

from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

# Importa apenas o que sobrou no app emails
from emails.models import MailBox, EmailMessage

logger = logging.getLogger(__name__)

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


# ----------------- FUNÇÃO PRINCIPAL DE LEITURA -----------------
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


def process_email(email_id):
    """
    [MOCK TEMPORÁRIO]
    A orquestração real será feita pelo novo app 'workflows' na Sprint 5.
    Esta função fica aqui vazia apenas para não quebrar filas antigas do Redis 
    que ainda possam tentar chamá-la.
    """
    logger.info(f"O email {email_id} foi recebido. Aguardando a nova engine de workflows assumir.")
    pass