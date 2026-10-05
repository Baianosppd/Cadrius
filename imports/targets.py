"""Destinos da importação (CAD-171): campos, sugestão de mapeamento das colunas e aplicação linha a linha.

Sugestão de colunas é por sinônimos (sem IA e sem custo de crédito); o usuário sempre confere antes de simular."""
from __future__ import annotations

import re
import unicodedata

from django.utils import timezone

from contacts.models import Contact
from contacts.validation import clean_contact
from core.pii import blind_index

TRUE = {'sim', 's', 'yes', 'y', 'x', 'true', '1', 'verdadeiro'}


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


FIELDS = {
    'contacts': [
        ('name', 'Nome', True, ['nome', 'name', 'cliente', 'nome completo', 'razao social', 'contato']),
        ('document', 'CPF/CNPJ', False, ['cpf', 'cnpj', 'cpf cnpj', 'documento', 'doc']),
        ('email', 'E-mail', False, ['email', 'e mail', 'correio eletronico']),
        ('phone', 'Telefone/WhatsApp', False, ['telefone', 'celular', 'whatsapp', 'fone', 'tel', 'phone']),
        ('kind', 'Tipo (cliente, parte contrária…)', False, ['tipo', 'categoria', 'papel']),
        ('tags', 'Etiquetas', False, ['etiquetas', 'tags', 'grupo', 'grupos']),
        ('notes', 'Observações', False, ['observacoes', 'observacao', 'obs', 'notas', 'anotacoes']),
        ('whatsapp_consent', 'Consentiu WhatsApp (sim/não)', False, ['consentimento whatsapp', 'aceita whatsapp', 'opt in whatsapp']),
        ('email_consent', 'Consentiu e-mail (sim/não)', False, ['consentimento email', 'aceita email', 'opt in email']),
    ],
    'cases': [
        ('cnj', 'Número do processo (CNJ)', True, ['processo', 'numero do processo', 'n processo', 'cnj', 'numero cnj', 'autos']),
        ('label', 'Apelido / cliente', False, ['cliente', 'apelido', 'descricao', 'parte', 'nome']),
    ],
}


def field_list(target):
    return [{'key': k, 'label': label, 'required': req} for k, label, req, _ in FIELDS[target]]


def suggest_mapping(target, columns) -> dict:
    """{índice_da_coluna: campo}. Cada campo é usado no máximo uma vez (a 1ª coluna que casar)."""
    out, used = {}, set()
    for idx, col in enumerate(columns):
        n = _norm(col)
        for key, _, _, synonyms in FIELDS[target]:
            if key in used:
                continue
            if n == _norm(key) or n in synonyms or any(n.startswith(s + ' ') or n.endswith(' ' + s) for s in synonyms if len(s) > 3):
                out[str(idx)] = key
                used.add(key)
                break
    return out


def validate_mapping(target, mapping) -> list[str]:
    valid = {k for k, *_ in FIELDS[target]}
    errors = []
    fields = [f for f in (mapping or {}).values() if f]
    if any(f not in valid for f in fields):
        errors.append('Campo de destino desconhecido no mapeamento.')
    if len(fields) != len(set(fields)):
        errors.append('Cada campo só pode receber uma coluna.')
    missing = [label for k, label, req, _ in FIELDS[target] if req and k not in fields]
    if missing:
        errors.append(f'Falta mapear: {", ".join(missing)}.')
    return errors


def row_values(mapping, row) -> dict:
    return {field: row[int(idx)] for idx, field in mapping.items() if field and int(idx) < len(row)}


# ----------------------------------------------------------------------------- contatos
def _contact_existing(org, values):
    if values.get('document'):
        found = Contact.objects.filter(organization=org, document_bidx=blind_index('contact.document', values['document'], 'digits')).first()
        if found:
            return found
    if values.get('email'):
        return Contact.objects.filter(organization=org, email_bidx=blind_index('contact.email', values['email'], 'text')).first()
    return None


def plan_contact(org, raw, seen):
    values, errors = clean_contact(raw)
    if errors:
        return None, errors, None
    key = values['document'] or values['email'] or None
    if key and key in seen:
        return None, ['Repetido na própria planilha (mesmo CPF/CNPJ ou e-mail).'], None
    if key:
        seen.add(key)
    existing = _contact_existing(org, values)
    return values, [], existing


def apply_contact(org, user, raw, values, existing, filename):
    consent = {f: str(raw.get(f, '')).strip().lower() in TRUE for f in ('whatsapp_consent', 'email_consent') if f in raw}
    if existing:
        for k, v in values.items():
            if k == 'tags':
                existing.tags = sorted(set(existing.tags or []) | set(v))
            elif v and k != 'person_type':
                setattr(existing, k, v)
        target, action = existing, 'updated'
    else:
        target, action = Contact(organization=org, created_by=user, source=Contact.Source.IMPORT, **values), 'created'
    if any(consent.values()):
        for f, v in consent.items():
            setattr(target, f, v or getattr(target, f))
        target.consent_updated_at = timezone.now()
        target.consent_source = f'importação da planilha {filename}'[:120]
    target.save()
    return action


# ----------------------------------------------------------------------------- processos (monitoramento)
def plan_case(org, raw, seen):
    from research import cnj
    from research.models import MonitoredCase
    parsed = cnj.parse(raw.get('cnj', ''))
    if not parsed:
        return None, ['Número CNJ inválido.'], None
    if not cnj.tribunal_alias(parsed):
        return None, ['Tribunal ainda não suportado pelo monitoramento.'], None
    if parsed['digits'] in seen:
        return None, ['Processo repetido na própria planilha.'], None
    seen.add(parsed['digits'])
    existing = MonitoredCase.objects.filter(organization=org, cnj_bidx=blind_index('case.cnj', parsed['digits'])).first()
    return {'cnj': parsed['formatted'], 'tribunal': cnj.tribunal_alias(parsed), 'label': str(raw.get('label', ''))[:120]}, [], existing


def apply_case(org, user, raw, values, existing, filename):
    from research.models import MonitoredCase
    if existing:
        if values['label'] and not existing.label:
            existing.label = values['label']
            existing.save(update_fields=['label'])
            return 'updated'
        return 'skipped'
    MonitoredCase.objects.create(organization=org, responsavel=user, **values)
    return 'created'


PLANNERS = {'contacts': (plan_contact, apply_contact), 'cases': (plan_case, apply_case)}
