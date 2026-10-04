"""Leitura básica LOCAL (sem IA, sem custo): número do processo, tipo por palavras-chave e prazos explícitos no texto.

Serve de primeira passada e de plano B quando a IA não está disponível (sem crédito, política, provedor ou pausa por cobrança):
o advogado ainda recebe um rascunho para revisar. Confiança baixa de propósito.
"""
from __future__ import annotations

import re
from datetime import date

CNJ = re.compile(r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b')
DAYS = re.compile(r'prazo\s+(?:legal\s+)?de\s+(\d{1,3})\s*(?:\(\w+\)\s*)?dias?(?:\s+(úteis|uteis|corridos))?', re.I)
DATE_BR = re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')
TYPES = (  # (tipo, palavras) — o primeiro que casar vence; ordem do mais específico para o mais genérico
    ('SENTENCA', ('sentença', 'sentenca', 'julgo procedente', 'julgo improcedente', 'dispositivo')),
    ('INTIMACAO', ('intimação', 'intimacao', 'fica intimado', 'ficam intimados', 'intime-se')),
    ('DECISAO', ('decisão interlocutória', 'decisao interlocutoria', 'defiro', 'indefiro', 'despacho')),
    ('PROCURACAO', ('procuração', 'procuracao', 'outorgante', 'outorgado', 'poderes')),
    ('CONTRATO', ('contrato', 'contratante', 'contratada', 'cláusula', 'clausula')),
    ('CERTIDAO', ('certidão', 'certidao', 'certifico')),
    ('PETICAO', ('excelentíssimo', 'excelentissimo', 'requer', 'petição', 'peticao', 'vem, respeitosamente')),
)


def local_extract(text: str) -> dict:
    low = (text or '').lower()
    kind = next((t for t, words in TYPES if any(w in low for w in words)), 'OUTRO')
    cnj = CNJ.search(text or '')
    prazos = []
    for m in DAYS.finditer(text or ''):
        prazos.append({'descricao': 'Prazo indicado no texto' + (f' ({m.group(2).lower()})' if m.group(2) else ''),
                       'data': None, 'dias': int(m.group(1)), 'fatal': False})
    for m in DATE_BR.finditer(text or ''):
        context = low[max(0, m.start() - 40):m.start()]
        if any(w in context for w in ('prazo', 'até', 'ate ', 'audiência', 'audiencia', 'vencimento')):
            try:
                prazos.append({'descricao': 'Data indicada no texto', 'data': date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(),
                               'dias': None, 'fatal': False})
            except ValueError:
                continue
    snippet = re.sub(r'\s+', ' ', (text or '').strip())[:400]
    return {
        'document_type': 'DOCUMENTO_JURIDICO', 'confidence_score': 35, 'tipo_documento': kind,
        'numero_processo': cnj.group(0) if cnj else None, 'partes': [], 'resumo': snippet, 'prazos': prazos[:10],
        'valor': None, 'proximos_passos': [],
    }
