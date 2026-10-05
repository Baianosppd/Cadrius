"""Normalização e validação de contato — usada pela API e pela importação de planilhas (mesmas regras nos dois caminhos)."""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts.validators import format_cnpj, format_cpf, is_valid_cnpj, is_valid_cpf
from contacts.models import Contact

KIND_ALIASES = {
    'cliente': 'cliente', 'clientes': 'cliente', 'client': 'cliente',
    'parte contraria': 'parte_contraria', 'parte contrária': 'parte_contraria', 'parte_contraria': 'parte_contraria', 'reu': 'parte_contraria', 'réu': 'parte_contraria',
    'testemunha': 'testemunha', 'perito': 'perito', 'correspondente': 'correspondente', 'fornecedor': 'fornecedor', 'outro': 'outro',
}
MAX_TAGS = 20


def clean_contact(data: dict) -> tuple[dict, list[str]]:
    """Devolve (valores limpos, erros). Não acessa o banco."""
    errors, out = [], {}
    name = re.sub(r'\s+', ' ', str(data.get('name') or '')).strip()
    if len(name) < 2:
        errors.append('Nome obrigatório.')
    out['name'] = name[:200]

    doc = re.sub(r'\D', '', str(data.get('document') or ''))
    if doc:
        if len(doc) == 11 and is_valid_cpf(doc):
            out['document'], out['person_type'] = format_cpf(doc), 'PF'
        elif len(doc) == 14 and is_valid_cnpj(doc):
            out['document'], out['person_type'] = format_cnpj(doc), 'PJ'
        else:
            errors.append('CPF/CNPJ inválido.')
    else:
        out['document'] = ''
        pt = str(data.get('person_type') or 'PF').upper()
        out['person_type'] = pt if pt in ('PF', 'PJ') else 'PF'

    email = str(data.get('email') or '').strip().lower()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors.append('E-mail inválido.')
    out['email'] = email[:200]

    phone = re.sub(r'\D', '', str(data.get('phone') or ''))
    if phone.startswith('55') and len(phone) in (12, 13):
        phone = phone[2:]
    if phone and len(phone) not in (10, 11):
        errors.append('Telefone deve ter DDD + número (10 ou 11 dígitos).')
    out['phone'] = phone

    kind = str(data.get('kind') or 'cliente').strip().lower()
    out['kind'] = KIND_ALIASES.get(kind, kind if kind in Contact.Kind.values else None)
    if out['kind'] is None:
        errors.append(f'Tipo desconhecido: {kind}.')
        out['kind'] = 'outro'

    tags = data.get('tags') or []
    if isinstance(tags, str):
        tags = [t for t in re.split(r'[;,]', tags)]
    out['tags'] = sorted({str(t).strip()[:40] for t in tags if str(t).strip()})[:MAX_TAGS]
    out['notes'] = str(data.get('notes') or '')[:2000]
    return out, errors
