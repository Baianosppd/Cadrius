"""Carteira de clientes a partir de pastas (CAD-234): cada pasta é um cliente; os arquivos dentro dela (inclusive em subpastas)
viram documentos do cliente no Cadrius.

Duas origens com o mesmo resultado:
- **Google Drive**: a pessoa cola o link da pasta-mãe; o Cadrius lista as subpastas com a leitura do Drive (autorização pedida
  só nessa hora) e baixa os arquivos.
- **.zip**: no Drive, botão direito na pasta-mãe → "Fazer download". Funciona sem nenhuma autorização extra.

Etapas: listar (prévia, nada gravado) → a pessoa confere/desmarca → importar em segundo plano (contatos + documentos).
Reimportar é seguro: contato existente é reaproveitado (CPF/CNPJ ou mesmo nome) e documento com o mesmo nome no mesmo
contato não é duplicado. A leitura dos documentos com IA é opcional (usa créditos).
"""
from __future__ import annotations

import logging
import posixpath
import re
import unicodedata
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from imports.models import FolderImport

logger = logging.getLogger(__name__)

ALLOWED_EXT = {'pdf', 'doc', 'docx', 'odt', 'rtf', 'txt', 'xls', 'xlsx', 'ods', 'csv', 'ppt', 'pptx', 'png', 'jpg', 'jpeg',
               'heic', 'tif', 'tiff', 'eml', 'msg', 'xml', 'html', 'mp3', 'ogg', 'opus', 'm4a', 'mp4'}
JUNK = {'.ds_store', 'thumbs.db', 'desktop.ini', 'icon\r'}
MAX_CLIENTS = 2000
MAX_FILES = 20000
MAX_DEPTH = 6
MAX_ZIP_TOTAL = 4 * 1024 ** 3                  # descompactado (proteção contra "zip bomb")
FOLDER_MIME = 'application/vnd.google-apps.folder'
# Google Docs/Planilhas/Apresentações não têm arquivo: exporta para um formato comum
GOOGLE_EXPORT = {
    'application/vnd.google-apps.document': ('application/pdf', 'pdf'),
    'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx'),
    'application/vnd.google-apps.presentation': ('application/pdf', 'pdf'),
}
DOC_RE = re.compile(r'(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{3}\.?\d{3}\.?\d{3}-?\d{2})')
DRIVE_URL_RE = re.compile(r'(?:/folders/|[?&]id=)([A-Za-z0-9_-]{10,})')


class FolderImportError(Exception):
    """Mensagem pronta para a tela."""


def max_file_bytes() -> int:
    return int(getattr(settings, 'DOCUMENT_MAX_BYTES', 25 * 1024 * 1024))


# ----------------------------------------------------------------------------- nomes
def norm_name(name: str) -> str:
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def parse_folder_name(raw: str) -> tuple[str, str]:
    """"João da Silva - 123.456.789-09" → ("João da Silva", "12345678909"). Só aceita CPF/CNPJ válido."""
    from accounts.validators import is_valid_cnpj, is_valid_cpf
    name, doc = raw.strip(), ''
    m = DOC_RE.search(name)
    if m:
        digits = re.sub(r'\D', '', m.group(1))
        if (len(digits) == 11 and is_valid_cpf(digits)) or (len(digits) == 14 and is_valid_cnpj(digits)):
            doc = digits
            name = (name[:m.start()] + name[m.end():])
    name = re.sub(r'^\s*\d{1,4}\s*[-._)]\s+', '', name)                # "01 - Fulano" (numeração da pasta)
    name = re.sub(r'\s*[-–|_()\[\]]+\s*$', '', re.sub(r'^\s*[-–|_()\[\]]+\s*', '', name))
    name = re.sub(r'\s+', ' ', name).strip(' -–_|')
    return (name or raw.strip())[:200], doc


def guess_kind(filename: str) -> str:
    n = norm_name(filename)
    if 'procuracao' in n:
        return 'procuracao'
    if 'contrato' in n or 'honorario' in n:
        return 'contrato'
    if any(w in n for w in ('peticao', 'inicial', 'contestacao', 'recurso', 'replica', 'manifestacao')):
        return 'peticao'
    return 'outro'


def _ext(name: str) -> str:
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


def _skip_reason(name: str, size: int) -> str:
    if name.lower() in JUNK or name.startswith('~$') or name.startswith('._'):
        return 'arquivo de sistema'
    if _ext(name) not in ALLOWED_EXT:
        return 'tipo não aceito'
    if size > max_file_bytes():
        return f'maior que {max_file_bytes() // (1024 * 1024)} MB'
    return ''


def _client(raw_name: str) -> dict:
    nome, doc = parse_folder_name(raw_name)
    return {'pasta': raw_name[:255], 'nome': nome, 'documento': doc, 'arquivos': [], 'ignorados': []}


# ----------------------------------------------------------------------------- .zip
def plan_from_zip(fileobj) -> tuple[list, list]:
    """Lê o índice do .zip (sem descompactar tudo). Devolve (clientes, arquivos soltos na raiz)."""
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise FolderImportError('Arquivo .zip inválido ou corrompido.') from exc
    entries = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if info.flag_bits & 0x800 == 0:                    # nomes sem UTF-8 (Windows antigo): tenta cp437 → utf-8
            try:
                name = name.encode('cp437').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        parts = [p for p in posixpath.normpath(name.replace('\\', '/')).split('/') if p not in ('', '.')]
        if not parts or '..' in parts or parts[0] == '__MACOSX':
            continue
        total += info.file_size
        if total > MAX_ZIP_TOTAL:
            raise FolderImportError('O .zip descompactado passa de 4 GB. Divida em partes (o Drive já divide pastas grandes).')
        entries.append((parts, info.filename, info.file_size))
    if not entries:
        raise FolderImportError('O .zip está vazio.')
    # Drive embrulha tudo numa pasta com o nome da pasta-mãe: se todos começam pela mesma pasta, desce um nível
    firsts = {p[0] for p, _, _ in entries}
    if len(firsts) == 1 and any(len(p) >= 3 for p, _, _ in entries):
        entries = [(p[1:], ref, size) for p, ref, size in entries if len(p) > 1]
    return _group(entries)


def _group(entries) -> tuple[list, list]:
    clients, loose = {}, []
    for parts, ref, size in entries:
        if len(parts) == 1:
            loose.append(parts[0])
            continue
        if len(parts) - 1 > MAX_DEPTH:
            continue
        c = clients.get(parts[0])
        if c is None:
            if len(clients) >= MAX_CLIENTS:
                raise FolderImportError(f'Mais de {MAX_CLIENTS} pastas de clientes: importe em partes.')
            c = clients[parts[0]] = _client(parts[0])
        shown = '/'.join(parts[1:])
        why = _skip_reason(parts[-1], size)
        if why:
            c['ignorados'].append({'nome': shown[:255], 'motivo': why})
        else:
            c['arquivos'].append({'nome': shown[:255], 'ref': ref, 'tamanho': size})
    out = sorted(clients.values(), key=lambda c: norm_name(c['nome']))
    if sum(len(c['arquivos']) for c in out) > MAX_FILES:
        raise FolderImportError(f'Mais de {MAX_FILES} arquivos: importe em partes.')
    return out, loose


def archive_dir() -> str:
    import os
    path = getattr(settings, 'FOLDER_IMPORT_TMP_DIR', '') or os.path.join(str(settings.MEDIA_ROOT), 'imports-tmp')
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def keep_archive(upload) -> str:
    """Guarda o .zip enviado numa pasta privada (só o servidor lê), com nome aleatório, até a importação terminar."""
    import os
    import secrets
    path = os.path.join(archive_dir(), f'{secrets.token_hex(16)}.zip')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return path


def discard_archive(job: FolderImport):
    import os
    if job.archive_path:
        try:
            os.remove(job.archive_path)
        except FileNotFoundError:
            pass
        job.archive_path = ''


def cleanup_stale(hours: int = 48) -> int:
    """Apaga .zip de prévias abandonadas (rotina diária)."""
    from datetime import timedelta
    old = FolderImport.objects.exclude(archive_path='').filter(created_at__lt=timezone.now() - timedelta(hours=hours))\
        .exclude(status=FolderImport.Status.RUNNING)
    n = 0
    for job in old:
        discard_archive(job)
        if job.status == FolderImport.Status.LISTED:
            job.status = FolderImport.Status.CANCELED
        job.plan = []
        job.save(update_fields=['archive_path', 'status', 'plan'])
        n += 1
    return n


# ----------------------------------------------------------------------------- Google Drive
def drive_folder_id(link: str) -> str:
    link = (link or '').strip()
    m = DRIVE_URL_RE.search(link)
    if m:
        return m.group(1)
    if re.fullmatch(r'[A-Za-z0-9_-]{10,}', link):
        return link
    raise FolderImportError('Cole o link da pasta do Google Drive (drive.google.com/drive/folders/…).')


def drive_link(user):
    from gcal.models import GoogleCalendarLink
    from gcal.platform import DRIVE_READONLY
    link = GoogleCalendarLink.objects.select_related('app', 'user').filter(user=user).first()
    if link is None or link.status != GoogleCalendarLink.Status.ACTIVE or not link.has_scope(DRIVE_READONLY):
        return None
    return link


def _drive(link, path, **params):
    from gcal import google_api as g
    from gcal.workspace import WorkspaceError, _call
    try:
        return _call(link, 'GET', f'{g.DRIVE_BASE}{path}', params=params)
    except WorkspaceError as exc:
        raise FolderImportError(str(exc).replace('Planilhas/Documentos', 'o Drive')) from exc


def _children(link, folder_id):
    q = f"'{folder_id}' in parents and trashed = false"
    token = None
    while True:
        params = {'q': q, 'fields': 'nextPageToken, files(id, name, mimeType, size)', 'pageSize': 1000,
                  'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'}
        if token:
            params['pageToken'] = token
        data = _drive(link, '/files', **params)
        yield from data.get('files') or []
        token = data.get('nextPageToken')
        if not token:
            return


def plan_from_drive(link, folder_id) -> tuple[str, list, list]:
    """(nome da pasta-mãe, clientes, arquivos soltos). Só lê: lista nomes, não baixa nada."""
    root = _drive(link, f'/files/{folder_id}', fields='id, name, mimeType', supportsAllDrives='true')
    if root.get('mimeType') != FOLDER_MIME:
        raise FolderImportError('O link não é de uma pasta. Abra a pasta-mãe dos clientes no Drive e copie o link dela.')
    entries, count = [], 0

    def walk(fid, parts, depth):
        nonlocal count
        for f in _children(link, fid):
            name = (f.get('name') or '').replace('/', '-')
            if f.get('mimeType') == FOLDER_MIME:
                if depth < MAX_DEPTH:
                    walk(f['id'], parts + [name], depth + 1)
                continue
            mime = f.get('mimeType') or ''
            if mime.startswith('application/vnd.google-apps.'):
                if mime not in GOOGLE_EXPORT:
                    continue                                             # formulários, atalhos, mapas…
                name = f'{name}.{GOOGLE_EXPORT[mime][1]}'
                size = 0
            else:
                size = int(f.get('size') or 0)
            count += 1
            if count > MAX_FILES:
                raise FolderImportError(f'Mais de {MAX_FILES} arquivos: importe por partes (uma pasta-mãe menor).')
            entries.append((parts + [name], f'{f["id"]}|{mime}', size))
    walk(folder_id, [], 0)
    if not entries:
        raise FolderImportError('A pasta está vazia ou você não tem acesso a ela.')
    clients, loose = _group(entries)
    return (root.get('name') or 'Google Drive')[:255], clients, loose


# ----------------------------------------------------------------------------- prévia
def preview(job: FolderImport) -> dict:
    """Prévia para a tela: cada pasta com o contato que será usado (existente ou novo)."""
    index = _contact_index(job.organization)
    clientes = []
    for i, c in enumerate(job.plan):
        existing = _match(job.organization, index, c)
        clientes.append({'indice': i, 'pasta': c['pasta'], 'nome': c['nome'], 'documento': _fmt_doc(c['documento']),
                         'arquivos': len(c['arquivos']), 'tamanho': sum(a.get('tamanho') or 0 for a in c['arquivos']),
                         'ignorados': len(c['ignorados']), 'exemplos': [a['nome'] for a in c['arquivos'][:4]],
                         'contato_existente': {'id': existing.pk, 'nome': existing.name} if existing else None})
    return {'clientes': clientes, 'total_arquivos': sum(x['arquivos'] for x in clientes),
            'total_ignorados': sum(x['ignorados'] for x in clientes),
            'novos': sum(1 for x in clientes if not x['contato_existente'] and x['arquivos'] >= 0)}


def _fmt_doc(d: str) -> str:
    from accounts.validators import format_cnpj, format_cpf
    return format_cpf(d) if len(d) == 11 else format_cnpj(d) if len(d) == 14 else ''


def _contact_index(org) -> dict:
    from contacts.models import Contact
    return {norm_name(c.name): c for c in Contact.objects.filter(organization=org).only('id', 'name')}


def _match(org, index: dict, c: dict):
    """Mesmo CPF/CNPJ (do nome da pasta) ou mesmo nome (sem acento/maiúsculas) = o mesmo contato."""
    from contacts.models import Contact
    from core.pii import blind_index
    if c.get('documento'):
        found = Contact.objects.filter(organization=org, document_bidx=blind_index('contact.document', c['documento'], 'digits')).first()
        if found:
            return found
    return index.get(norm_name(c['nome']))


# ----------------------------------------------------------------------------- importação (segundo plano)
def start(job: FolderImport, user, selecionadas, ler_com_ia: bool):
    from core.queue import enqueue
    chosen = sorted({int(i) for i in selecionadas if str(i).isdigit() and 0 <= int(i) < len(job.plan)}) if selecionadas is not None \
        else list(range(len(job.plan)))
    if not chosen:
        raise FolderImportError('Marque ao menos uma pasta.')
    total = sum(len(job.plan[i]['arquivos']) for i in chosen)
    job.options = {'selecionadas': chosen, 'ler_com_ia': bool(ler_com_ia), 'usuario': str(user.pk)}
    job.progress = {'feitas': 0, 'total': len(chosen), 'arquivos_total': total, 'contatos_novos': 0, 'contatos_existentes': 0,
                    'documentos': 0, 'repetidos': 0, 'erros': []}
    job.status = FolderImport.Status.RUNNING
    job.save(update_fields=['options', 'progress', 'status'])
    transaction.on_commit(lambda: enqueue('imports.folders.run', job.pk))


def _fetcher(job: FolderImport):
    """Função (ref) → bytes, conforme a origem."""
    if job.source == FolderImport.Source.ZIP:
        zf = zipfile.ZipFile(job.archive_path)

        def from_zip(ref):
            info = zf.getinfo(ref)
            if info.file_size > max_file_bytes():
                raise FolderImportError('arquivo grande demais')
            with zf.open(info) as fh:
                data = fh.read(max_file_bytes() + 1)
            if len(data) > max_file_bytes():
                raise FolderImportError('arquivo grande demais')
            return data
        return from_zip, zf.close
    from django.contrib.auth import get_user_model
    from gcal import google_api as g
    from gcal.sync import _access_token
    user = get_user_model().objects.filter(pk=job.options.get('usuario')).first()
    link = drive_link(user) if user else None
    if link is None:
        raise FolderImportError('A leitura do Google Drive não está mais autorizada. Autorize de novo e reimporte.')

    def from_drive(ref):
        fid, mime = ref.split('|', 1)
        if mime in GOOGLE_EXPORT:
            url, params = f'{g.DRIVE_BASE}/files/{fid}/export', {'mimeType': GOOGLE_EXPORT[mime][0]}
        else:
            url, params = f'{g.DRIVE_BASE}/files/{fid}', {'alt': 'media', 'supportsAllDrives': 'true'}
        try:
            return g.download(_access_token(link), url, params=params, max_bytes=max_file_bytes())
        except g.GoogleTooLarge as exc:
            raise FolderImportError('arquivo grande demais') from exc
        except (g.GoogleAuthError, g.GoogleNotFound, g.GoogleRetryable) as exc:
            raise FolderImportError('o Google não entregou o arquivo') from exc
    return from_drive, (lambda: None)


STEP_SECONDS = 40      # cada etapa termina antes do limite de 60 s da fila e agenda a próxima (carteiras grandes)


def run(job_id: int):
    """Tarefa do Django-Q: cria/reaproveita os contatos e grava os documentos (cifrados) ligados a cada um.

    Trabalha em etapas de ~40 s: ao passar do tempo, salva onde parou (pasta e arquivo) e agenda a continuação."""
    import time

    from audit import service as audit
    from contacts.models import Contact
    from core.queue import enqueue
    from documents.models import ClientDocument, Document, DocumentExtraction
    from documents.pipeline import enqueue_processing

    job = FolderImport.objects.select_related('organization', 'created_by').filter(pk=job_id).first()
    if job is None or job.status != FolderImport.Status.RUNNING:
        return
    org, user, prog = job.organization, job.created_by, job.progress
    try:
        fetch, close = _fetcher(job)
    except FolderImportError as exc:
        job.status, prog['erros'] = FolderImport.Status.FAILED, [str(exc)]
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'progress', 'finished_at'])
        return
    began = time.monotonic()
    index = _contact_index(org)
    selected = job.options.get('selecionadas', [])
    paused = False
    try:
        for pos in range(prog.get('feitas', 0), len(selected)):
            c = job.plan[selected[pos]]
            cur = prog.get('atual') or {}
            contact = Contact.objects.filter(organization=org, pk=cur.get('contato')).first() if cur.get('pos') == pos else None
            if contact is None:
                cur = {'pos': pos, 'n': 0}
                contact = _match(org, index, c)
                if contact is None:
                    values = {'name': c['nome'], 'kind': 'cliente', 'person_type': 'PJ' if len(c['documento']) == 14 else 'PF',
                              'source': 'import', 'tags': ['drive']}
                    if c['documento']:
                        values['document'] = _fmt_doc(c['documento'])
                    contact = Contact.objects.create(organization=org, created_by=user, **values)
                    index[norm_name(contact.name)] = contact
                    prog['contatos_novos'] += 1
                    audit.log('contact.created', actor=user, organization=org, target=contact, changes={'origem': 'importacao_pastas'},
                              data_categories=['identificacao'], legal_basis='execucao_contrato')
                else:
                    prog['contatos_existentes'] += 1
                cur['contato'] = contact.pk
            prog['atual'] = cur
            already = set(Document.objects.filter(organization=org, contact=contact).values_list('nome', flat=True))
            for k in range(cur['n'], len(c['arquivos'])):
                if time.monotonic() - began > STEP_SECONDS:
                    paused = True
                    break
                a = c['arquivos'][k]
                cur['n'] = k + 1
                nome = a['nome'][:255]
                if nome in already:
                    prog['repetidos'] += 1
                    continue
                try:
                    data = fetch(a['ref'])
                except (FolderImportError, KeyError, OSError, zipfile.BadZipFile) as exc:
                    if len(prog['erros']) < 100:
                        prog['erros'].append(f'{c["nome"]} / {nome}: {exc}')
                    continue
                doc = Document(organization=org, uploaded_by=user, nome=nome, tipo=guess_kind(nome),
                               status=Document.Status.PRONTO, contact=contact)
                doc.arquivo.save(posixpath.basename(nome)[-120:] or 'arquivo', ContentFile(data), save=True)
                ClientDocument.objects.create(nome_cliente=contact.name, documento=doc)
                already.add(nome)
                prog['documentos'] += 1
                if job.options.get('ler_com_ia'):
                    DocumentExtraction.objects.get_or_create(document=doc)
                    enqueue_processing(doc.pk, getattr(user, 'pk', None))
            if paused:
                break
            prog['feitas'], prog['atual'] = pos + 1, None
            FolderImport.objects.filter(pk=job.pk).update(progress=prog)
    except Exception:  # noqa: BLE001 — registra e marca a falha; o que já foi gravado fica (reimportar não duplica)
        logger.exception('Importação de pastas %s falhou', job.pk)
        prog['erros'].append('Falha inesperada no meio da importação. O que já entrou ficou salvo; importe de novo para completar.')
        job.status = FolderImport.Status.FAILED
    else:
        if paused:                                                       # continua na próxima etapa
            FolderImport.objects.filter(pk=job.pk).update(progress=prog)
            close()
            enqueue('imports.folders.run', job.pk)
            return
        job.status = FolderImport.Status.DONE
    close()
    job.progress, job.finished_at = prog, timezone.now()
    discard_archive(job)                                                 # o .zip não fica guardado
    job.plan = []                                                        # minimização: os contatos/documentos já estão no sistema
    job.save(update_fields=['progress', 'status', 'finished_at', 'archive_path', 'plan'])
    audit.log('data.import', actor=user, organization=org,
              changes={'tipo': 'pastas', 'origem': job.source, 'contatos_novos': prog['contatos_novos'],
                       'contatos_existentes': prog['contatos_existentes'], 'documentos': prog['documentos']})
