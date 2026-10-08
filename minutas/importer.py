"""Importar modelos de minuta (CAD-231): o escritório traz as peças que já usa (Word, PDF, texto) e reaproveita sempre.

1. **Texto:**
   - ``.docx``: lido direto do XML do Word, sem biblioteca extra e sem parser XML;
   - ``.pdf``: lido pelo pypdf;
   - ``.txt`` / ``.md``: lido como texto.
2. **Campos:** as marcações que o escritório já usa viram variáveis do Cadrius:
   - formatos aceitos: ``{{cliente.nome}}``, ``[NOME DO CLIENTE]``, ``«cliente»``, ``<<CLIENTE>>``, ``{CLIENTE}``;
   - o que bate com uma variável conhecida (cliente, processo, vara, OAB, data…) vira essa variável;
   - o resto vira um campo próprio do modelo (``{{campo.valor_da_causa}}``), que aparece como ``[COMPLETAR: Valor da causa]``
     ao gerar a minuta, e que a IA tenta preencher quando a pessoa pede "Melhorar com IA".
3. **Linhas de preenchimento:** "______" vira ``[COMPLETAR]``.

Nada é salvo aqui: a tela mostra a prévia (texto + campos) e a pessoa confirma.
"""
from __future__ import annotations

import html
import io
import re
import unicodedata
import zipfile

from minutas.builtin import VARS

MAX_FILE = 5 * 1024 * 1024
MAX_XML = 20 * 1024 * 1024
MAX_TEXT = 30_000
EXTS = ('.docx', '.pdf', '.txt', '.md')

# rótulo normalizado (sem acento, minúsculo) → variável do Cadrius
ALIASES = {
    'cliente': 'cliente.nome', 'nome do cliente': 'cliente.nome', 'autor': 'cliente.nome', 'requerente': 'cliente.nome',
    'contratante': 'cliente.nome', 'outorgante': 'cliente.nome',
    'parte contraria': 'parte_contraria.nome', 're': 'parte_contraria.nome', 'requerido': 'parte_contraria.nome',
    'requerida': 'parte_contraria.nome', 'reu': 'parte_contraria.nome',
    'processo': 'processo.cnj', 'numero do processo': 'processo.cnj', 'n do processo': 'processo.cnj', 'cnj': 'processo.cnj',
    'autos': 'processo.cnj',
    'vara': 'processo.orgao', 'juizo': 'processo.orgao', 'orgao': 'processo.orgao', 'comarca': 'processo.orgao',
    'tribunal': 'processo.tribunal', 'classe': 'processo.classe', 'acao': 'processo.classe',
    'advogado': 'advogado.nome', 'advogada': 'advogado.nome', 'nome do advogado': 'advogado.nome',
    'oab': 'advogado.oab', 'numero da oab': 'advogado.oab',
    'escritorio': 'escritorio.nome', 'cidade': 'cidade', 'local': 'cidade',
    'data': 'hoje', 'data de hoje': 'hoje', 'hoje': 'hoje',
    'prazo': 'prazo.data', 'vencimento': 'prazo.data', 'data do prazo': 'prazo.data', 'dias do prazo': 'prazo.dias',
    'ato': 'ato', 'decisao': 'ato', 'resumo': 'resumo', 'providencia': 'providencia', 'documento': 'documento.nome',
    'assinatura': 'assinatura',
}
MARKERS = [
    re.compile(r'\{\{\s*([^{}\n]{1,60}?)\s*\}\}'),     # {{campo}}
    re.compile(r'«\s*([^«»\n]{1,60}?)\s*»'),             # «campo»
    re.compile(r'<<\s*([^<>\n]{1,60}?)\s*>>'),           # <<CAMPO>>
    re.compile(r'\[\s*([^\[\]\n]{2,60}?)\s*\]'),         # [NOME DO CLIENTE]
    re.compile(r'(?<!\{)\{\s*([A-Za-zÀ-ú][^{}\n]{1,58}?)\s*\}(?!\})'),   # {CLIENTE}
]
BLANKS = re.compile(r'_{4,}|\.{6,}')


class ImportError_(ValueError):
    """Mensagem pronta para a tela."""


def _plain(text: str) -> str:
    t = unicodedata.normalize('NFKD', text or '')
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c))).strip().lower()


def _slug(label: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '_', _plain(label)).strip('_')
    return s[:40] or 'campo'


# ----------------------------------------------------------------------------- leitura dos arquivos
def _docx_text(raw: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        info = z.getinfo('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ImportError_('Arquivo do Word inválido (salve como .docx).') from exc
    if info.file_size > MAX_XML:
        raise ImportError_('Documento grande demais.')
    xml = z.read(info).decode('utf-8', errors='ignore')
    paragraphs = []
    for p in re.split(r'</w:p>', xml):
        p = re.sub(r'<w:tab\s*/>', '\t', p)
        p = re.sub(r'<w:br\s*/>', '\n', p)
        if '<w:p' not in p:
            continue
        pieces = re.findall(r'<w:t(?:\s[^>]*)?>([^<]*)</w:t>|(\t)|(\n)', p)
        paragraphs.append(html.unescape(''.join(a or b or c for a, b, c in pieces)))
    return '\n'.join(paragraphs)


def _pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if len(reader.pages) > 60:
            raise ImportError_('PDF com páginas demais para um modelo (máximo 60).')
        return '\n'.join((page.extract_text() or '') for page in reader.pages)
    except ImportError_:
        raise
    except Exception as exc:  # noqa: BLE001 — PDF corrompido/criptografado
        raise ImportError_('Não foi possível ler o PDF (protegido por senha ou só imagem).') from exc


def read_file(name: str, raw: bytes) -> str:
    if len(raw) > MAX_FILE:
        raise ImportError_('O arquivo pode ter até 5 MB.')
    low = (name or '').lower()
    if low.endswith('.docx'):
        text = _docx_text(raw)
    elif low.endswith('.pdf'):
        text = _pdf_text(raw)
    elif low.endswith(('.txt', '.md')):
        text = raw.decode('utf-8', errors='replace') if not raw.startswith(b'\xff\xfe') else raw.decode('utf-16', errors='replace')
    else:
        raise ImportError_('Use um arquivo .docx, .pdf, .txt ou .md (o .doc antigo: salve como .docx).')
    text = re.sub(r'[ \t]+\n', '\n', text.replace('\r\n', '\n')).strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    if len(text) < 10:
        raise ImportError_('Não encontrei texto no arquivo (PDF escaneado precisa de OCR antes).')
    return text[:MAX_TEXT]


# ----------------------------------------------------------------------------- campos
def detect_fields(text: str) -> tuple[str, list[dict]]:
    """Troca as marcações por variáveis do Cadrius. Devolve (corpo, campos)."""
    fields: dict[str, dict] = {}

    def to_var(label: str, original: str):
        label = label.strip()
        if sum(ch.isalpha() for ch in label) < 2 or label.lower() in ('sic', 'omissis'):
            return original                                  # "[...]", "[1]", "[sic]" ficam como estão
        if label in VARS:                                   # já é variável do Cadrius
            key = label
        else:
            norm = _plain(label).replace('nº', 'n').replace('n.', 'n')
            key = ALIASES.get(norm) or ALIASES.get(norm.replace('o ', '').replace('a ', ''))
            if key is None:
                key = f'campo.{_slug(label)}'
        if key not in fields:
            fields[key] = {'chave': key, 'rotulo': VARS.get(key) or label[:60].strip().capitalize(), 'conhecido': key in VARS,
                           'original': label[:60]}
        return '{{' + key + '}}'

    body = text
    for rx in MARKERS:
        body = rx.sub(lambda m: to_var(m.group(1), m.group(0)) if not m.group(1).startswith('COMPLETAR') else m.group(0), body)
    body = BLANKS.sub('[COMPLETAR]', body)
    return body, list(fields.values())


def guess_kind(name: str, text: str) -> str:
    hay = _plain(f'{name} {text[:600]}')
    for kind, words in (('procuracao', ('procuracao',)), ('contrato', ('contrato', 'honorarios')), ('notificacao', ('notificacao',)),
                        ('peticao', ('excelentissimo', 'vossa excelencia', 'peticao', 'recurso', 'contestacao')),
                        ('comunicado', ('prezado', 'caro cliente', 'informamos'))):
        if any(w in hay for w in words):
            return kind
    return 'outro'


def prepare(name: str, raw: bytes) -> dict:
    text = read_file(name, raw)
    body, fields = detect_fields(text)
    title = re.sub(r'\.(docx|pdf|txt|md)$', '', (name or 'Modelo importado').rsplit('/', 1)[-1], flags=re.I).replace('_', ' ')
    return {'nome': title.strip()[:120] or 'Modelo importado', 'tipo': guess_kind(title, text), 'corpo': body, 'campos': fields}
