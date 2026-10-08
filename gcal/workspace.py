"""Google Planilhas e Documentos pela mesma conexão do Google (CAD-230).

Escopo ``drive.file``: o Cadrius cria e edita **só os arquivos que ele mesmo criou** no Drive da pessoa — não lê nem lista
o resto do Drive (é o escopo que o Google recomenda e não é "sensível"). Por isso:
- "exportar para planilha" cria uma planilha nova (ou reaproveita a do mesmo nome que o Cadrius já criou);
- "registrar na planilha" (automação) acrescenta linhas sempre na mesma planilha do Cadrius;
- "criar documento" gera um Google Docs com o texto (minuta, plano do caso, ata…).

Valores vão como ``RAW``: um texto que começa com "=" fica como texto, não vira fórmula (evita injeção de fórmula).
"""
from __future__ import annotations

import re

from django.core.cache import cache

from gcal import google_api as g
from gcal.models import GoogleCalendarLink, GoogleFile
from gcal.platform import DRIVE_FILE

MAX_ROWS = 2000
MAX_COLS = 40
MAX_CELL = 5000
MAX_DOC = 200_000
NUMBER_RE = re.compile(r'^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$|^-?\d+\.\d+$')


class WorkspaceError(Exception):
    """Mensagem pronta para a tela / para a IA."""


def _link(user) -> GoogleCalendarLink:
    link = GoogleCalendarLink.objects.select_related('app', 'user').filter(user=user).first()
    if link is None:
        raise WorkspaceError('Conecte o Google em Integrações → Google para usar Planilhas e Documentos.')
    if link.status != GoogleCalendarLink.Status.ACTIVE:
        raise WorkspaceError('A conexão com o Google precisa ser refeita (Integrações → Google → Reconectar).')
    if not link.has_scope(DRIVE_FILE):
        raise WorkspaceError('Sua conexão com o Google ainda não autorizou Planilhas e Documentos. '
                             'Clique em "Reconectar" em Integrações → Google e aceite o acesso.')
    return link


def _call(link, method, url, **kw):
    from gcal.sync import _access_token
    for attempt in (1, 2):
        try:
            return g.api_call(_access_token(link), method, url, **kw)
        except g.GoogleAuthError as exc:
            if attempt == 1 and 'access token recusado' in str(exc):
                cache.delete(f'gcal:at:{link.pk}')                    # token vencido: renova uma vez
                continue
            # 403 aqui é falta de escopo/API (não derruba a agenda, que tem o próprio escopo)
            raise WorkspaceError('O Google recusou o acesso a Planilhas/Documentos. Reconecte em Integrações → Google.') from exc
        except g.GoogleRetryable as exc:
            raise WorkspaceError('O Google não respondeu agora. Tente de novo em instantes.') from exc
        except g.GoogleNotFound as exc:
            raise WorkspaceError('O arquivo não existe mais no seu Google Drive.') from exc
    raise WorkspaceError('Não foi possível falar com o Google.')


def _cell(value) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Sim' if value else 'Não'
    if isinstance(value, (int, float)):
        return value
    text = str(value)[:MAX_CELL]
    raw = text.strip()
    digits = sum(ch.isdigit() for ch in raw)
    # "1.234,56" / "1234.5" → número (dá para somar). CPF, CNJ, telefone e códigos com zero à esquerda continuam texto.
    if NUMBER_RE.match(raw) and digits <= 12 and not (raw.lstrip('-').startswith('0') and raw.lstrip('-')[1:2].isdigit()):
        raw = raw.replace('.', '').replace(',', '.') if ',' in raw else raw
        try:
            return float(raw) if '.' in raw else int(raw)
        except ValueError:
            return text
    return text


def _rows(linhas) -> list[list]:
    rows = []
    for row in (linhas or [])[:MAX_ROWS]:
        if isinstance(row, dict):
            row = list(row.values())
        if not isinstance(row, (list, tuple)):
            row = [row]
        rows.append([_cell(v) for v in list(row)[:MAX_COLS]])
    return rows


def _register(link, kind, name, file_id, url) -> GoogleFile:
    obj, _ = GoogleFile.objects.update_or_create(link=link, kind=kind, name=name[:200],
                                                 defaults={'file_id': file_id, 'url': url})
    return obj


def create_sheet(user, titulo: str, colunas=None, linhas=None) -> GoogleFile:
    link = _link(user)
    titulo = (titulo or 'Cadrius').strip()[:200]
    data = _call(link, 'POST', f'{g.SHEETS_BASE}/spreadsheets',
                 json={'properties': {'title': titulo, 'locale': 'pt_BR'}, 'sheets': [{'properties': {'title': 'Dados'}}]})
    sid, url = data['spreadsheetId'], data.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{data["spreadsheetId"]}/edit'
    values = ([_rows([colunas])[0]] if colunas else []) + _rows(linhas)
    if values:
        _call(link, 'POST', f'{g.SHEETS_BASE}/spreadsheets/{sid}/values/Dados!A1:append',
              params={'valueInputOption': 'RAW', 'insertDataOption': 'INSERT_ROWS'}, json={'values': values})
    _audit(user, 'planilha_criada', linhas=len(values))
    return _register(link, GoogleFile.Kind.SHEET, titulo, sid, url)


def append_rows(user, titulo: str, linhas, colunas=None) -> GoogleFile:
    """Acrescenta linhas na planilha do Cadrius com esse nome (cria na primeira vez, já com o cabeçalho)."""
    link = _link(user)
    titulo = (titulo or 'Cadrius').strip()[:200]
    existing = GoogleFile.objects.filter(link=link, kind=GoogleFile.Kind.SHEET, name=titulo).first()
    if existing is None:
        return create_sheet(user, titulo, colunas, linhas)
    try:
        _call(link, 'POST', f'{g.SHEETS_BASE}/spreadsheets/{existing.file_id}/values/A1:append',
              params={'valueInputOption': 'RAW', 'insertDataOption': 'INSERT_ROWS'}, json={'values': _rows(linhas)})
    except WorkspaceError as exc:
        if 'não existe mais' in str(exc):                    # a pessoa apagou a planilha: recria
            existing.delete()
            return create_sheet(user, titulo, colunas, linhas)
        raise
    existing.save(update_fields=['used_at'])
    _audit(user, 'planilha_linhas', linhas=len(linhas or []))
    return existing


def create_doc(user, titulo: str, conteudo: str) -> GoogleFile:
    link = _link(user)
    titulo = (titulo or 'Documento do Cadrius').strip()[:200]
    doc = _call(link, 'POST', f'{g.DOCS_BASE}/documents', json={'title': titulo})
    did = doc['documentId']
    text = (conteudo or '').replace('\r\n', '\n')[:MAX_DOC]
    if text:
        _call(link, 'POST', f'{g.DOCS_BASE}/documents/{did}:batchUpdate',
              json={'requests': [{'insertText': {'location': {'index': 1}, 'text': text}}]})
    _audit(user, 'documento_criado', caracteres=len(text))
    return _register(link, GoogleFile.Kind.DOC, f'{titulo} · {did[-6:]}', did, f'https://docs.google.com/document/d/{did}/edit')


def _audit(user, what, **extra):
    from accounts.team_roles import get_active_membership
    from audit import service as audit
    m = get_active_membership(user)
    audit.log('integration.call', actor=user, organization=m.organization if m else None,
              changes={'provider': 'google_workspace', 'acao': what, **extra})
