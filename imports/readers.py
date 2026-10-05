"""Leitura de CSV e XLSX sem dependências externas (CAD-171). Limites para não aceitar arquivo gigante/zip-bomb."""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET  # nosec B405 — XLSX enviado pelo usuário: DOCTYPE/ENTITY recusados antes do parse

MAX_BYTES = 2_000_000
MAX_ROWS = 5000
MAX_COLS = 40
MAX_UNZIPPED = 25_000_000
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


class ReadError(Exception):
    pass


def _safe_xml(data: bytes):
    head = data[:5000].upper()
    if b'<!DOCTYPE' in head or b'<!ENTITY' in head:
        raise ReadError('Planilha com conteúdo XML não permitido.')
    return ET.fromstring(data)  # nosec B314


def _trim(header, rows):
    header = [str(h or '').strip() for h in header][:MAX_COLS]
    if not any(header):
        raise ReadError('A primeira linha precisa ter os nomes das colunas.')
    width = len(header)
    out = []
    for r in rows:
        r = [str(v if v is not None else '').strip() for v in r][:width]
        r += [''] * (width - len(r))
        if any(r):
            out.append(r)
        if len(out) > MAX_ROWS:
            raise ReadError(f'Máximo de {MAX_ROWS} linhas por importação. Divida a planilha.')
    if not out:
        raise ReadError('A planilha não tem linhas de dados.')
    return header, out


def read_csv(data: bytes):
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ReadError('Codificação do arquivo não reconhecida (salve como CSV UTF-8).')
    sample = text[:4096]
    delimiter = ';' if sample.count(';') > sample.count(',') else ','
    if sample.count('\t') > max(sample.count(';'), sample.count(',')):
        delimiter = '\t'
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise ReadError('Arquivo vazio.')
    return _trim(rows[0], rows[1:])


def _col_index(ref: str) -> int:
    letters = re.match(r'[A-Z]+', ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data: bytes):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ReadError('Arquivo XLSX inválido.') from exc
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise ReadError('Planilha grande demais depois de descompactada.')
    names = zf.namelist()
    shared = []
    if 'xl/sharedStrings.xml' in names:
        for si in _safe_xml(zf.read('xl/sharedStrings.xml')).iter(f'{NS}si'):
            shared.append(''.join(t.text or '' for t in si.iter(f'{NS}t')))
    sheets = sorted(n for n in names if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n))
    if not sheets:
        raise ReadError('A planilha não tem abas.')
    root = _safe_xml(zf.read(sheets[0]))                       # 1ª aba
    table = []
    for row in root.iter(f'{NS}row'):
        values = {}
        for c in row.iter(f'{NS}c'):
            ref, kind = c.get('r', ''), c.get('t')
            v = c.find(f'{NS}v')
            if kind == 's' and v is not None:
                val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ''
            elif kind == 'inlineStr':
                val = ''.join(t.text or '' for t in c.iter(f'{NS}t'))
            else:
                val = v.text if v is not None and v.text else ''
                if re.fullmatch(r'-?\d+\.0', val or ''):
                    val = val[:-2]                               # 12345.0 → 12345 (CPF/telefone digitados como número)
            if ref:
                values[_col_index(ref)] = val
        if values:
            width = max(values) + 1
            table.append([values.get(i, '') for i in range(min(width, MAX_COLS))])
    if not table:
        raise ReadError('A planilha está vazia.')
    return _trim(table[0], table[1:])


def read_file(filename: str, data: bytes):
    if len(data) > MAX_BYTES:
        raise ReadError('Arquivo maior que 2 MB.')
    name = (filename or '').lower()
    if name.endswith('.csv') or name.endswith('.txt'):
        return read_csv(data)
    if name.endswith('.xlsx'):
        return read_xlsx(data)
    raise ReadError('Formato não suportado. Envie CSV ou XLSX (Excel).')
