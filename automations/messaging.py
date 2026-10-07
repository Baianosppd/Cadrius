"""Envio ao contato (CAD-222): um só caminho para automações, assistente e alertas da agenda.

Regras de cuidado com o cliente:
- só envia por canal que o contato AUTORIZOU (LGPD) e que tem dado (telefone/e-mail); "melhor" escolhe WhatsApp quando
  pode e cai para e-mail;
- horário comercial (8h às 20h, segunda a sábado, fora de feriado nacional): fora dele o envio é agendado para o próximo
  horário permitido — ninguém recebe aviso de prazo às 23h;
- todo envio fica na auditoria (sem o conteúdo).
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from django.utils import timezone

from audit import service as audit

START, END = 8, 20
CHANNEL_LABEL = {'whatsapp': 'WhatsApp', 'email': 'e-mail'}


class Blocked(Exception):
    """Envio não permitido (sem consentimento, sem canal, sem conexão) — mensagem segura para mostrar."""


def whatsapp_connection(org):
    """Conexão de WhatsApp do escritório. A do "WhatsApp do escritório" (hospedada pelo Cadrius) vem antes de qualquer
    conexão manual: uma conexão manual antiga ou de teste não pode desviar os envios para outra instância (CAD-229)."""
    from integrations.models import AppConnection
    conns = list(AppConnection.objects.filter(app_name='WHATSAPP', is_active=True, user__memberships__organization=org,
                                              user__memberships__is_active=True).order_by('-pk').distinct()[:20])
    return next((c for c in conns if (c.credentials or {}).get('hosted')), conns[0] if conns else None)


def digits_phone(raw: str) -> str:
    digits = re.sub(r'\D', '', raw or '')
    return f'55{digits}' if len(digits) in (10, 11) else digits


def pick_channel(org, contact, wanted: str) -> str:
    """'whatsapp' | 'email' | 'melhor' → canal efetivo; levanta Blocked com o motivo."""
    if contact is None:
        raise Blocked('O evento não tem cliente/contato vinculado.')
    if contact.opted_out:
        raise Blocked(f'{contact.name} pediu para não receber mensagens.')
    options = ['whatsapp', 'email'] if wanted == 'melhor' else [wanted]
    reasons = []
    for ch in options:
        if not contact.can_receive(ch):
            reasons.append(f'sem autorização ou sem {"telefone" if ch == "whatsapp" else "e-mail"} para {CHANNEL_LABEL[ch]}')
            continue
        if ch == 'whatsapp' and whatsapp_connection(org) is None:
            reasons.append('nenhuma conexão de WhatsApp ativa no escritório')
            continue
        return ch
    raise Blocked(f'{contact.name}: ' + '; '.join(reasons) + '.')


def business_hours(now=None) -> bool:
    from forense.calendar import national_closures
    local = timezone.localtime(now or timezone.now())
    if local.weekday() == 6 or not START <= local.hour < END:
        return False
    return local.date() not in national_closures(local.year)


def next_business_moment(now=None) -> datetime:
    """Próxima hora cheia dentro do horário comercial (ou agora, se já estiver dentro)."""
    local = timezone.localtime(now or timezone.now())
    if business_hours(local):
        return local
    candidate = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(24 * 10):
        if business_hours(candidate):
            return candidate
        candidate += timedelta(hours=1)
    return candidate


def deliver(org, contact, channel: str, message: str, subject: str = '', *, origin: dict | None = None, user=None,
            layout: str = '') -> str:
    """Envia agora pelo canal (já escolhido com ``pick_channel``). Devolve o canal usado."""
    channel = pick_channel(org, contact, channel)            # confere de novo na hora do envio (consentimento pode mudar)
    if channel == 'whatsapp':
        from integrations.evolution import WhatsAppEvolutionExecutor
        from workflows.tasks import _evolution_credentials_from_connection
        base_url, api_key, instance = _evolution_credentials_from_connection(whatsapp_connection(org), org)
        WhatsAppEvolutionExecutor(base_url=base_url, api_key=api_key).send(instance, {'number': digits_phone(contact.phone), 'text': message})
    else:
        footer = (f'Você recebe esta mensagem porque autorizou o contato de {org}. '
                  'Para não receber mais, responda a este e-mail pedindo a remoção.')
        from integrations import email_layout                # CAD-226: visual do escritório + assinatura de quem envia
        email_layout.send(org, subject or f'Aviso de {org}', message, [contact.email], user=user, layout=layout, footer=footer)
    audit.log('message.sent', actor_type='system', organization=org, target=contact, changes={'canal': channel, **(origin or {})},
              data_categories=['contato'], legal_basis='consentimento')
    return channel


def at(day, hour=START) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour, 0)))
