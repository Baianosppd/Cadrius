"""Triagem de e-mails recebidos (CAD-222) → gatilho "E-mail recebido" das automações.

1) Regras (sem custo e sem IA): palavras do assunto/corpo, remetente de tribunal, remetente que é contato do escritório.
2) IA (se a política do escritório permitir e houver provedor seguro para dado de cliente): refina categoria, urgência,
   resumo, ação sugerida e data citada. Falhou? Fica a triagem por regras.
O corpo do e-mail vai para a IA marcado como NÃO CONFIÁVEL (pode conter instruções escondidas).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

COURT_DOMAINS = ('jus.br', 'tjsp.jus.br', 'trf', 'trt', 'stj.jus.br', 'stf.jus.br', 'cnj.jus.br', 'pje')
RULES = [  # (categoria, urgência, palavras)
    ('intimacao', 'alta', ('intimacao', 'intimado', 'citacao', 'publicacao', 'despacho', 'sentenca', 'decisao', 'acordao', 'mandado', 'pje')),
    ('agenda', 'alta', ('audiencia', 'pericia', 'sessao de julgamento', 'reuniao', 'agendamento', 'remarcad', 'convite:')),
    ('financeiro', 'media', ('boleto', 'fatura', 'pagamento', 'pix', 'nota fiscal', 'nfs-e', 'cobranca', 'vencimento', 'recibo')),
    ('comercial', 'media', ('orcamento', 'proposta', 'gostaria de contratar', 'consulta juridica', 'preciso de um advogado', 'honorarios')),
    ('documento', 'media', ('segue em anexo', 'seguem os documentos', 'documentos solicitados', 'anexo', 'procuracao', 'comprovante')),
    ('marketing', 'baixa', ('newsletter', 'descadastrar', 'unsubscribe', 'promocao', 'oferta', 'webinar', 'cupom')),
]
DATE_RE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')
URGENT_WORDS = ('urgente', 'prazo fatal', 'hoje', 'liminar', 'tutela de urgencia', 'imediato')


def _norm(text: str) -> str:
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def first_date(text: str):
    for d, m, y in DATE_RE.findall(text or ''):
        try:
            return date(int(y), int(m), int(d))
        except ValueError:
            continue
    return None


def by_rules(subject: str, body: str, sender: str, is_contact: bool) -> dict:
    hay = _norm(f'{subject}\n{body[:4000]}')
    sender_n = _norm(sender)
    out = {'category': 'outro', 'urgency': 'media', 'suggested_action': '', 'due_date': first_date(f'{subject} {body[:4000]}')}
    if any(d in sender_n for d in COURT_DOMAINS):
        out.update(category='intimacao', urgency='alta')
    else:
        for cat, urg, words in RULES:
            if is_contact and cat in ('intimacao', 'comercial', 'marketing'):
                continue                          # cliente citando "sentença" não é intimação do tribunal
            if any(w in hay for w in words):
                out.update(category=cat, urgency=urg)
                break
        if out['category'] in ('outro', 'documento') and is_contact:
            out['category'] = 'cliente' if out['category'] == 'outro' else 'documento'
    if any(w in hay for w in URGENT_WORDS) and out['category'] != 'marketing':
        out['urgency'] = 'alta'
    out['suggested_action'] = {
        'intimacao': 'Conferir a intimação e lançar o prazo.', 'agenda': 'Conferir data e hora e colocar na agenda.',
        'financeiro': 'Conferir o pagamento/cobrança no Financeiro.', 'comercial': 'Responder e registrar oportunidade na Carteira.',
        'documento': 'Salvar o documento e enviar para leitura.', 'cliente': 'Responder o cliente.', 'marketing': 'Nenhuma ação.',
    }.get(out['category'], '')
    return out


class TriageSchema(BaseModel):
    categoria: str = Field(description='intimacao | cliente | agenda | financeiro | comercial | documento | marketing | outro')
    urgencia: str = Field(description='alta | media | baixa')
    resumo: str = Field(default='', description='1 a 2 frases, sem dados sensíveis desnecessários')
    acao_sugerida: str = Field(default='', description='próxima ação prática em até 15 palavras')
    data_citada: str = Field(default='', description='data mais importante citada (AAAA-MM-DD) ou vazio')


PROMPT = ('Classifique o e-mail recebido por um escritório de advocacia brasileiro. Categorias: intimacao (tribunal, publicação, '
          'citação), cliente (cliente pedindo algo/informando), agenda (audiência, perícia, reunião), financeiro (boleto, pagamento), '
          'comercial (possível novo cliente/proposta), documento (envio de documentos), marketing (propaganda), outro.')


def by_ai(org, subject: str, body: str):
    from aigov.guard import AIBlocked, get_policy, run_guarded
    from aigov import llm
    from extraction.ai_wrapper import extract_fields_from_text
    providers = llm.candidates(get_policy(org).allowed_providers or [], sensitive=True, profile='triagem')
    if not providers:
        return None
    text = f'ASSUNTO: {subject}\n\n{body[:6000]}'
    try:
        return run_guarded(organization=org, user=None, kind='triage', provider=providers[0], categories=['contato'],
                           input_text=text, fn=lambda: extract_fields_from_text(text, TriageSchema, PROMPT, provider=providers[0],
                                                                                fallbacks=providers[1:]))
    except AIBlocked:
        return None
    except Exception:  # noqa: BLE001 — IA é refinamento: falhou, vale a regra
        logger.exception('Triagem de e-mail por IA falhou')
        return None


def _contact_for(org, sender: str):
    from contacts.models import Contact
    from core.pii import blind_index
    m = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', sender or '')
    if not m:
        return None
    return Contact.objects.filter(organization=org, email_bidx=blind_index('contact.email', m.group(0).lower(), 'text')).first()


def triage_email(email_id) -> str | None:
    """Fila: classifica o e-mail e dispara o gatilho. Idempotente (um e-mail = uma triagem)."""
    from accounts.team_roles import get_active_membership
    from emails.models import EmailMessage, EmailTriage

    em = EmailMessage.objects.filter(pk=email_id).select_related('mailbox__user').first()
    if em is None or hasattr(em, 'triage'):
        return None
    membership = get_active_membership(em.mailbox.user)
    if membership is None:
        return None
    org = membership.organization
    contact = _contact_for(org, em.sender)
    result = by_rules(em.subject, em.body_text or '', em.sender, contact is not None)
    method = 'regras'
    ai = by_ai(org, em.subject, em.body_text or '') if result['category'] != 'marketing' else None
    if ai:
        valid_cat = {c for c, _ in EmailTriage.Category.choices}
        if ai.get('categoria') in valid_cat:
            result['category'] = ai['categoria']
        if ai.get('urgencia') in ('alta', 'media', 'baixa'):
            result['urgency'] = ai['urgencia']
        result['suggested_action'] = (ai.get('acao_sugerida') or result['suggested_action'])[:200]
        try:
            result['due_date'] = date.fromisoformat(ai.get('data_citada') or '') or result['due_date']
        except ValueError:
            pass
        result['summary'] = (ai.get('resumo') or '')[:1000]
        method = 'ia'
        from billing.credits import charge
        charge(org, 'triage', user_id=em.mailbox.user_id)                     # CAD-225
    tri = EmailTriage.objects.create(email=em, organization=org, category=result['category'], urgency=result['urgency'],
                                     summary=result.get('summary', '') or em.subject[:300], suggested_action=result['suggested_action'],
                                     due_date=result['due_date'], contact=contact, method=method)
    from automations.engine import emit
    emit(org, 'email_received', {'email_id': em.pk}, f'email-{em.pk}')
    return tri.category
