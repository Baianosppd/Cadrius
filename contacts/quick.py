"""Contato "na hora" (CAD-234): quando a pessoa pede uma automação ou uma mensagem para alguém que ainda não está nos contatos,
o assistente cadastra o contato no mesmo pedido de confirmação. Se já existir (mesmo e-mail, CPF/CNPJ ou telefone), reaproveita.

Autorização de envio (LGPD): só é registrada quando a pessoa diz que o contato autorizou WhatsApp/e-mail; fica gravado
quem informou e quando (``consent_source``). Sem isso, o contato é cadastrado e o envio fica bloqueado até registrar.
"""
from __future__ import annotations

from django.utils import timezone

from contacts.models import Contact
from contacts.validation import clean_contact
from core.pii import blind_index


class QuickContactError(Exception):
    """Mensagem pronta para o cartão de confirmação."""


def clean(novo) -> tuple[dict, bool, bool]:
    """``novo_contato`` do assistente → (valores, autoriza_whatsapp, autoriza_email). Não toca no banco."""
    if not isinstance(novo, dict):
        raise QuickContactError('novo_contato deve ter nome e, de preferência, e-mail e/ou telefone.')
    novo = _from_cnpj(novo)
    values, errors = clean_contact({'name': novo.get('nome', ''), 'kind': novo.get('tipo') or 'cliente', 'email': novo.get('email', ''),
                                    'phone': novo.get('telefone', ''), 'document': novo.get('documento', '')})
    if errors:
        raise QuickContactError(' '.join(errors))
    return values, novo.get('autoriza_whatsapp') is True, novo.get('autoriza_email') is True


def _from_cnpj(novo: dict) -> dict:
    """Empresa com CNPJ e sem nome/e-mail/telefone: completa com os dados públicos da Receita (BrasilAPI). Falha não impede."""
    import re

    digits = re.sub(r'\D', '', str(novo.get('documento') or ''))
    if len(digits) != 14 or (novo.get('nome') and novo.get('email') and novo.get('telefone')):
        return novo
    from integrations import public_data
    try:
        d = public_data.cnpj(digits)
    except public_data.PublicDataError:
        return novo
    return {**novo, 'nome': novo.get('nome') or d.get('nome_fantasia') or d.get('razao_social') or '',
            'email': novo.get('email') or d.get('email') or '', 'telefone': novo.get('telefone') or d.get('telefone') or ''}


def find_existing(org, values: dict):
    """Mesmo e-mail, CPF/CNPJ ou telefone no escritório = o mesmo contato."""
    for field, (col, purpose, kind) in Contact.BLIND_INDEXES.items():
        value = values.get(field)
        if value:
            found = Contact.objects.filter(organization=org, **{col: blind_index(purpose, value, kind)}).first()
            if found:
                return found
    return None


def describe(org, novo) -> str:
    """Frase do cartão de confirmação."""
    values, wa, em = clean(novo)
    existing = find_existing(org, values)
    who = f'usa o contato já cadastrado "{existing.name}"' if existing else f'cadastra o contato "{values["name"]}"'
    data = ', '.join(x for x in (values.get('email'), values.get('phone')) if x)
    auth = [c for c, ok in (('WhatsApp', wa), ('e-mail', em)) if ok]
    consent = (f'; registra que ele(a) autorizou {" e ".join(auth)} (informado por você)' if auth
               else '; sem autorização de envio registrada: as mensagens ficam bloqueadas até registrar')
    return f'{who}{f" ({data})" if data and not existing else ""}{consent}'


def ensure(org, user, novo, origem='assistente') -> tuple[Contact, bool]:
    """Cria (ou reaproveita) o contato e registra a autorização informada. Devolve (contato, criado?)."""
    from audit import service as audit
    values, wa, em = clean(novo)
    contact = find_existing(org, values)
    created = contact is None
    if created:
        contact = Contact.objects.create(organization=org, created_by=user, **values)
        audit.log('contact.created', actor=user, organization=org, target=contact, changes={'kind': contact.kind, 'origem': origem},
                  data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
        from automations.engine import emit
        emit(org, 'contact_created', {'contact_id': contact.pk, 'user_id': str(user.pk)}, f'contact-{contact.pk}')
    changed = []
    for field, ok in (('whatsapp_consent', wa), ('email_consent', em)):
        if ok and not getattr(contact, field) and not contact.opted_out:
            setattr(contact, field, True)
            changed.append(field)
    if changed:
        contact.consent_updated_at = timezone.now()
        contact.consent_source = f'{origem}: autorização informada por {user.email}'[:120]
        contact.save(update_fields=[*changed, 'consent_updated_at', 'consent_source'])
        audit.log('contact.updated', actor=user, organization=org, target=contact, changes={'consent': changed, 'origem': origem},
                  data_categories=['contato'], legal_basis='consentimento')
    return contact, created
