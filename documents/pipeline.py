"""Pipeline de leitura de documentos (CAD-163).

    upload → confere o tipo pelo CONTEÚDO → antivírus (opcional) → texto (PDF/DOCX/TXT; OCR opcional p/ digitalizado)
           → mascara CPF/CNPJ/e-mail/telefone → IA (governada, com crédito) → fica em "aguardando revisão"
           → um advogado confirma/corrige → só então vira tarefa/prazo.

Falhas nunca derrubam o upload: o documento já está salvo; a extração mostra o motivo (falhou / não processado) e pode ser reprocessada.
Assíncrono (Django-Q). Cada etapa degrada com mensagem clara quando a ferramenta não existe no ambiente (antivírus, OCR).
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import zipfile

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit import service as audit
from core.pii import mask_text

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000          # o que cabe no contexto/custo: o restante é ignorado (o aviso fica na mensagem)
MAX_OCR_PAGES = 30
PROVIDER_ORDER = ('GROQ', 'GEMINI', 'OPENAI')   # barato primeiro (docs/ANALISE_PRECOS_PLANOS.md §5)
KEY_ENV = {'GROQ': 'GROQ_API_KEY', 'GEMINI': 'GEMINI_API_KEY', 'OPENAI': 'OPENAI_API_KEY'}


class Skip(Exception):
    """Etapa impediu o processamento por uma razão esperada (não é erro de sistema)."""


class Blocked(Exception):
    """Antivírus encontrou ameaça."""


# ----------------------------------------------------------------------------- tipo pelo conteúdo
def detect_kind(data: bytes) -> str:
    if data[:5] == b'%PDF-':
        return 'pdf'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if 'word/document.xml' in z.namelist():
                    return 'docx'
        except zipfile.BadZipFile:
            return ''
        return ''
    try:
        sample = data[:4096].decode('utf-8')
        if sample and sum(c.isprintable() or c in '\n\r\t' for c in sample) / len(sample) > 0.97:
            return 'txt'
    except UnicodeDecodeError:
        pass
    return ''


# ----------------------------------------------------------------------------- antivírus (ClamAV via TCP, opcional)
def scan(data: bytes) -> str:
    """'clean' | 'skipped'. Levanta Blocked se infectado. Sem CLAMAV_HOST configurado: 'skipped' (a etapa é registrada)."""
    host = getattr(settings, 'CLAMAV_HOST', '')
    if not host:
        return 'skipped'
    try:
        with socket.create_connection((host, int(getattr(settings, 'CLAMAV_PORT', 3310))), timeout=20) as s:
            s.sendall(b'zINSTREAM\0')
            for i in range(0, len(data), 8192):
                chunk = data[i:i + 8192]
                s.sendall(struct.pack('!L', len(chunk)) + chunk)
            s.sendall(struct.pack('!L', 0))
            reply = s.recv(4096).decode(errors='replace')
    except OSError as exc:
        # antivírus configurado e fora do ar: NÃO processa às cegas (falha fechada)
        raise Skip('Antivírus indisponível no momento; tente reprocessar mais tarde.') from exc
    if 'FOUND' in reply:
        raise Blocked(reply.strip(' \0\n').split(':', 1)[-1].strip())
    return 'clean'


# ----------------------------------------------------------------------------- texto
def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise Skip('PDF protegido por senha: não foi possível ler.')
    return '\n'.join((page.extract_text() or '') for page in reader.pages)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read('word/document.xml').decode('utf-8', errors='replace')
    xml = re.sub(r'</w:p>', '\n', xml)
    return re.sub(r'<[^>]+>', '', xml)


def ocr_available() -> bool:
    return bool(shutil.which('tesseract'))


def _ocr_image_bytes(data: bytes, suffix: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, f'img{suffix}')
        with open(path, 'wb') as fh:
            fh.write(data)
        out = subprocess.run(['tesseract', path, 'stdout', '-l', getattr(settings, 'OCR_LANGS', 'por+eng')],  # nosec B603 B607
                             capture_output=True, timeout=120, check=False)
        return out.stdout.decode('utf-8', errors='replace')


def _ocr_pdf(data: bytes) -> str:
    if not shutil.which('pdftoppm'):
        raise Skip('OCR de PDF digitalizado indisponível (falta o poppler-utils).')
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, 'in.pdf')
        with open(pdf, 'wb') as fh:
            fh.write(data)
        subprocess.run(['pdftoppm', '-r', '200', '-l', str(MAX_OCR_PAGES), '-png', pdf, os.path.join(d, 'p')],  # nosec B603 B607
                       capture_output=True, timeout=300, check=False)
        pages = sorted(f for f in os.listdir(d) if f.startswith('p') and f.endswith('.png'))
        texts = []
        for name in pages:
            with open(os.path.join(d, name), 'rb') as fh:
                texts.append(_ocr_image_bytes(fh.read(), '.png'))
        return '\n'.join(texts)


def extract_text(data: bytes, kind: str) -> tuple[str, bool]:
    """(texto, usou_ocr). Levanta Skip com mensagem clara quando não dá para ler."""
    if kind == 'pdf':
        text = _pdf_text(data)
        if len(text.strip()) >= 40:
            return text, False
        if not ocr_available():
            raise Skip('PDF digitalizado (sem texto) e o OCR não está habilitado neste ambiente.')
        return _ocr_pdf(data), True
    if kind == 'docx':
        return _docx_text(data), False
    if kind == 'txt':
        return data.decode('utf-8', errors='replace'), False
    if kind in ('png', 'jpeg'):
        if not ocr_available():
            raise Skip('Imagem digitalizada e o OCR não está habilitado neste ambiente.')
        return _ocr_image_bytes(data, '.png' if kind == 'png' else '.jpg'), True
    raise Skip('Tipo de arquivo não suportado (use PDF, DOCX, TXT, PNG ou JPG).')


# ----------------------------------------------------------------------------- IA
def pick_provider(policy) -> str:
    allowed = [p for p in PROVIDER_ORDER if p in (policy.allowed_providers or [])]
    configured = [p for p in allowed if os.environ.get(KEY_ENV[p], '').strip()]
    if not configured:
        raise Skip('Nenhum provedor de IA permitido e configurado para este escritório.')
    return configured[0]


def run_ai(organization, user, text: str, provider: str) -> dict | None:
    from aigov.guard import run_guarded
    from extraction.ai_wrapper import extract_fields_from_text
    from extraction.schemas import DocumentoJuridicoSchema

    masked = mask_text(text)[:MAX_TEXT_CHARS]
    prompt = ('Leia o documento jurídico e preencha o schema. document_type deve ser "DOCUMENTO_JURIDICO". '
              'Não invente dados: use null/lista vazia quando o texto não trouxer a informação.')
    return run_guarded(
        organization=organization, user=user, kind='extraction', provider=provider,
        categories=['dados_processuais', 'identificacao'], input_text=masked,
        fn=lambda: extract_fields_from_text(masked, DocumentoJuridicoSchema, prompt, provider=provider),
    )


# ----------------------------------------------------------------------------- orquestração
def _finish(extraction, status, stage, message='', **fields):
    extraction.status, extraction.stage, extraction.message = status, stage, message[:255]
    for k, v in fields.items():
        setattr(extraction, k, v)
    extraction.save()


def process_document(doc_pk, user_id=None):
    """Roda o pipeline para um documento. Idempotente: pode ser chamado de novo (reprocessar)."""
    from aigov.guard import AIBlocked
    from billing.credit_weights import credits_for
    from billing.credits import check_credit_available, consume_credit
    from django.contrib.auth import get_user_model
    from documents.models import Document, DocumentExtraction

    doc = Document.objects.select_related('organization').filter(pk=doc_pk).first()
    if doc is None or not doc.arquivo:
        return 'gone'
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else doc.uploaded_by
    extraction, _ = DocumentExtraction.objects.get_or_create(document=doc)
    if extraction.status == DocumentExtraction.Status.CONFIRMED:
        return 'confirmed'                      # não sobrescreve o que uma pessoa já confirmou
    _finish(extraction, DocumentExtraction.Status.PROCESSING, 'scan', fields={}, confidence=None, ocr_used=False)

    try:
        from core.storage import read_all
        data = read_all(doc.arquivo)
        kind = detect_kind(data)
        extraction.detected_kind = kind
        if not kind:
            raise Skip('Tipo de arquivo não suportado (use PDF, DOCX, TXT, PNG ou JPG).')

        if scan(data) == 'skipped':
            logger.info('Antivírus não configurado: etapa pulada (doc %s)', doc_pk)

        extraction.stage = 'text'
        text, used_ocr = extract_text(data, kind)
        text = text.strip()
        if len(text) < 20:
            raise Skip('Não foi possível extrair texto legível do documento.')
        extraction.text_chars, extraction.ocr_used = len(text), used_ocr

        org = doc.organization
        from aigov.guard import get_policy
        provider = pick_provider(get_policy(org))
        weight = credits_for('extraction')
        if weight:                                   # confere o saldo ANTES; só cobra se a IA devolver algo utilizável
            ok, msg = check_credit_available(org, user_id=getattr(user, 'pk', None))
            if not ok:
                raise Skip(msg)
        extraction.stage, extraction.provider = 'ai', provider
        result = run_ai(org, user, text, provider)
        if result and weight:
            consume_credit(org, user_id=getattr(user, 'pk', None), amount=weight)
        if not result:
            _finish(extraction, DocumentExtraction.Status.FAILED, 'ai', 'A IA não conseguiu estruturar este documento. Tente reprocessar ou preencha manualmente.')
            return 'failed'
        note = ' (texto muito longo: só o início foi analisado)' if len(text) > MAX_TEXT_CHARS else ''
        _finish(extraction, DocumentExtraction.Status.REVIEW, 'review', f'Leitura pronta: revise antes de confirmar.{note}',
                fields=result, confidence=result.get('confidence_score'))
        audit.log('document.extracted', actor=user, organization=org, target=doc,
                  changes={'provider': provider, 'ocr': used_ocr, 'chars': len(text), 'kind': kind},
                  data_categories=['dados_processuais'], legal_basis='contrato')
        _mark_ready(doc)
        return 'review'
    except Blocked as exc:
        _finish(extraction, DocumentExtraction.Status.FAILED, 'scan', f'Arquivo bloqueado pelo antivírus ({str(exc)[:60]}).')
        audit.log('document.blocked', actor=user, organization=doc.organization, target=doc, outcome='denied', reason='antivírus')
        return 'blocked'
    except AIBlocked as exc:
        _finish(extraction, DocumentExtraction.Status.SKIPPED, 'ai', f'IA bloqueada pela política do escritório: {exc.message}')
        return 'ai_blocked'
    except Skip as exc:
        _finish(extraction, DocumentExtraction.Status.SKIPPED, extraction.stage or 'text', str(exc))
        _mark_ready(doc)
        return 'skipped'
    except Exception:  # noqa: BLE001 — o documento já está salvo; registra e mostra "falhou" em vez de derrubar a fila
        logger.exception('Falha no pipeline do documento %s', doc_pk)
        _finish(extraction, DocumentExtraction.Status.FAILED, extraction.stage or 'text', 'Erro inesperado ao ler o documento. Tente reprocessar.')
        return 'error'


def _mark_ready(doc):
    from documents.models import Document
    if doc.status == Document.Status.PROCESSANDO:
        Document.objects.filter(pk=doc.pk).update(status=Document.Status.PRONTO)


def enqueue_processing(doc_pk, user_id=None):
    """Chamado após o upload, DEPOIS do commit. Fila indisponível não derruba o upload (dá para reprocessar)."""
    if not getattr(settings, 'DOCUMENT_PIPELINE_ENABLED', True):
        return

    def _go():
        try:
            from core.queue import QueueUnavailable, enqueue
            try:
                enqueue('documents.pipeline.process_document', doc_pk, user_id)
            except QueueUnavailable:
                logger.warning('Fila indisponível: leitura do documento %s adiada (reprocessar depois)', doc_pk)
        except Exception:  # noqa: BLE001
            logger.exception('Falha ao enfileirar a leitura do documento %s', doc_pk)

    transaction.on_commit(_go)


# ----------------------------------------------------------------------------- confirmação humana → tarefas
def confirm(extraction, user, edited_fields: dict) -> list:
    """Grava a versão revisada e cria as tarefas dos prazos com data. Devolve as tarefas criadas."""
    from datetime import datetime, time

    from django.utils.dateparse import parse_date

    from documents.models import DocumentExtraction
    from tasks.models import UserTask

    fields = {**(extraction.fields or {}), **(edited_fields or {})}
    created = []
    for prazo in fields.get('prazos') or []:
        day = parse_date(str(prazo.get('data') or '')) if prazo.get('data') else None
        if not day:
            continue
        when = timezone.make_aware(datetime.combine(day, time(9, 0)))
        title = f"Prazo: {prazo.get('descricao') or 'documento'}"[:255]
        has_cal = hasattr(user, 'gcal_link') and user.gcal_link.status == 'active'
        task = UserTask.objects.create(
            titulo=title, descricao=f"Documento: {extraction.document.nome}. {fields.get('resumo', '')}"[:2000],
            scheduled_at=when, priority='alta' if prazo.get('fatal') else 'media', responsavel=user, sincronizar=has_cal)
        created.append(task)
    extraction.fields = fields
    extraction.status = DocumentExtraction.Status.CONFIRMED
    extraction.stage, extraction.message = 'review', 'Confirmado por uma pessoa.'
    extraction.reviewed_by, extraction.reviewed_at = user, timezone.now()
    extraction.save()
    audit.log('document.extraction_confirmed', actor=user, organization=extraction.document.organization, target=extraction.document,
              changes={'tasks_created': len(created)}, data_categories=['dados_processuais'], legal_basis='contrato')
    return created
