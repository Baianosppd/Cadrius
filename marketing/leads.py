"""Captação e satisfação (CAD-223).

- Formulário público de captação: o visitante deixa nome, contato e assunto; vira contato (origem "formulário") + oportunidade
  no funil (etapa "Novo contato") e dispara o gatilho ``lead_captured``. Consentimento LGPD obrigatório e registrado; WhatsApp e
  e-mail só ficam autorizados se a pessoa marcar. Texto do formulário passa pelo verificador OAB ao salvar.
- Pesquisa de satisfação (NPS 0–10): link único por cliente, criado pela automação "Pedir avaliação"; a resposta dispara
  ``survey_answered`` (ex.: detrator → tarefa para ligar).
"""
from __future__ import annotations

import re
import secrets
from datetime import timedelta

from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from audit import service as audit
from marketing import compliance
from marketing.models import CaptureForm, SatisfactionSurvey

CONSENT_TEXT = ('Concordo que o escritório use estes dados para responder ao meu contato, conforme a Lei Geral de Proteção de '
                'Dados (LGPD). Posso pedir a exclusão a qualquer momento.')
SURVEY_DAYS = 30


class LeadError(Exception):
    pass


def form_json(f: CaptureForm, with_counts=True) -> dict:
    data = {'id': f.pk, 'titulo': f.title, 'apresentacao': f.intro, 'assuntos': f.areas, 'agradecimento': f.thank_you,
            'ativo': f.active, 'campanha_id': f.campaign_id, 'token': f.token, 'link': f'/captacao/{f.token}',
            'alertas': f.compliance, 'criado_em': f.created_at}
    if with_counts:
        data['envios'] = f.submissions
    return data


def save_form(org, user, data: dict, form: CaptureForm | None = None) -> CaptureForm:
    title = str(data.get('titulo', form.title if form else '') or '').strip()[:120]
    if not title:
        raise LeadError('Dê um título ao formulário.')
    intro = str(data.get('apresentacao', form.intro if form else '') or '').strip()[:500]
    areas = data.get('assuntos', form.areas if form else [])
    if not isinstance(areas, list) or len(areas) > 12:
        raise LeadError('Assuntos: lista com até 12 opções.')
    areas = [str(a).strip()[:60] for a in areas if str(a).strip()]
    alerts = compliance.check(f'{title}\n{intro}', 'escritorio')
    if compliance.blocking(alerts) and not data.get('revisado'):
        raise LeadError('O texto tem alerta "alto" da checagem OAB: ' + '; '.join(a['regra'] for a in alerts if a['nivel'] == 'alto')
                        + '. Ajuste o texto ou confirme que revisou.')
    campaign = None
    if data.get('campanha_id'):
        from marketing.models import Campaign
        campaign = Campaign.objects.filter(organization=org, pk=data['campanha_id']).first()
        if campaign is None:
            raise LeadError('Campanha não encontrada.')
    fields = {'title': title, 'intro': intro, 'areas': areas, 'compliance': alerts, 'campaign': campaign,
              'thank_you': str(data.get('agradecimento', form.thank_you if form else '') or '').strip()[:300]
              or 'Recebemos sua mensagem. Retornaremos em breve.',
              'active': bool(data.get('ativo', form.active if form else True))}
    if form is None:
        form = CaptureForm.objects.create(organization=org, created_by=user, token=secrets.token_urlsafe(18), **fields)
    else:
        for k, v in fields.items():
            setattr(form, k, v)
        form.save()
    audit.log('marketing.form_saved', actor=user, organization=org, target=form, changes={'titulo': title, 'ativo': form.active})
    return form


def public_json(f: CaptureForm) -> dict:
    return {'escritorio': f.organization.name, 'titulo': f.title, 'apresentacao': f.intro, 'assuntos': f.areas,
            'consentimento': CONSENT_TEXT}


def _digits(v) -> str:
    return re.sub(r'\D', '', str(v or ''))


def submit(form: CaptureForm, data: dict) -> str:
    """Recebe o envio público. Devolve a mensagem de agradecimento. Campo ``site`` é armadilha para robôs."""
    if str(data.get('site') or '').strip():
        return form.thank_you                                    # robô: finge sucesso e não grava nada
    name = str(data.get('nome') or '').strip()[:120]
    email = str(data.get('email') or '').strip().lower()[:200]
    phone = _digits(data.get('telefone'))[:13]
    if len(name) < 2:
        raise LeadError('Informe seu nome.')
    if not email and len(phone) < 10:
        raise LeadError('Informe um e-mail ou telefone para o retorno.')
    if email:
        try:
            validate_email(email)
        except Exception as exc:  # noqa: BLE001
            raise LeadError('E-mail inválido.') from exc
    if data.get('consentimento') is not True:
        raise LeadError('É preciso concordar com o uso dos dados para o escritório responder.')
    area = str(data.get('assunto') or '').strip()[:60]
    if form.areas and area and area not in form.areas:
        area = ''
    message = str(data.get('mensagem') or '').strip()[:1000]
    from carteira.models import Opportunity
    from contacts.models import Contact
    org = form.organization
    now = timezone.now()
    with transaction.atomic():
        contact = Contact.objects.create(
            organization=org, name=name, email=email, phone=phone, source=Contact.Source.FORM, kind=Contact.Kind.CLIENT,
            email_consent=bool(email and data.get('aceita_email')), whatsapp_consent=bool(phone and data.get('aceita_whatsapp')),
            consent_updated_at=now, consent_source=f'Formulário de captação "{form.title}"'[:120])
        opp = Opportunity.objects.create(organization=org, contact=contact, title=f'{area or "Contato"} — {name}'[:160], area=area,
                                         source=Opportunity.Source.SITE, campaign=form.campaign, notes=message,
                                         next_action='Responder o contato do formulário', next_action_at=timezone.localdate())
        CaptureForm.objects.filter(pk=form.pk).update(submissions=form.submissions + 1)
    audit.log('marketing.lead_captured', organization=org, target=contact, actor_type='anonymous', actor_label='visitante (formulário)',
              changes={'formulario': form.pk, 'oportunidade': opp.pk}, data_categories=['identificacao', 'contato'], legal_basis='consentimento')
    from automations.engine import emit
    emit(org, 'lead_captured', {'opportunity_id': opp.pk, 'form_id': form.pk}, f'lead-{opp.pk}')
    return form.thank_you


# ----------------------------------------------------------------------------- pesquisa de satisfação
def create_survey(org, contact, reason='') -> SatisfactionSurvey:
    open_ = SatisfactionSurvey.objects.filter(organization=org, contact=contact, answered_at__isnull=True,
                                              expires_at__gt=timezone.now()).first()
    if open_:
        return open_
    return SatisfactionSurvey.objects.create(organization=org, contact=contact, token=secrets.token_urlsafe(18), reason=reason[:120],
                                             expires_at=timezone.now() + timedelta(days=SURVEY_DAYS))


def survey_link(s: SatisfactionSurvey) -> str:
    from django.conf import settings
    base = (getattr(settings, 'FRONTEND_URL', '') or '').rstrip('/')
    return f'{base}/pesquisa/{s.token}'


def answer(s: SatisfactionSurvey, score, comment='') -> SatisfactionSurvey:
    if s.answered_at:
        raise LeadError('Esta pesquisa já foi respondida. Obrigado!')
    if s.expires_at <= timezone.now():
        raise LeadError('Este link expirou.')
    try:
        score = int(score)
    except (TypeError, ValueError) as exc:
        raise LeadError('Escolha uma nota de 0 a 10.') from exc
    if not 0 <= score <= 10:
        raise LeadError('Escolha uma nota de 0 a 10.')
    s.score, s.comment, s.answered_at = score, str(comment or '').strip()[:1000], timezone.now()
    s.save(update_fields=['score', 'comment', 'answered_at'])
    audit.log('marketing.survey_answered', organization=s.organization, target=s.contact, actor_type='anonymous',
              actor_label='cliente (pesquisa)', changes={'nota': score}, data_categories=['contato'], legal_basis='legitimo_interesse')
    from automations.engine import emit
    emit(s.organization, 'survey_answered', {'survey_id': s.pk}, f'survey-{s.pk}')
    return s


def nps(org, days=180) -> dict:
    since = timezone.now() - timedelta(days=days)
    rows = list(SatisfactionSurvey.objects.filter(organization=org, answered_at__gte=since).values_list('score', flat=True))
    sent = SatisfactionSurvey.objects.filter(organization=org, created_at__gte=since).count()
    if not rows:
        return {'respostas': 0, 'enviadas': sent, 'nps': None, 'promotores': 0, 'neutros': 0, 'detratores': 0}
    pro = sum(1 for r in rows if r >= 9)
    det = sum(1 for r in rows if r <= 6)
    return {'respostas': len(rows), 'enviadas': sent, 'nps': round(100 * (pro - det) / len(rows)), 'promotores': pro,
            'neutros': len(rows) - pro - det, 'detratores': det}


def channel_results(org, days=180) -> dict:
    """Origem dos clientes: oportunidades por canal e por campanha, conversão e honorários fechados."""
    from carteira.models import Opportunity
    since = timezone.now() - timedelta(days=days)
    qs = Opportunity.objects.filter(organization=org, created_at__gte=since).select_related('campaign')
    by_source, by_campaign = {}, {}
    labels = dict(Opportunity.Source.choices)
    for o in qs:
        for bucket, key, label in ((by_source, o.source, labels.get(o.source, o.source)),
                                   (by_campaign, o.campaign_id, o.campaign.name if o.campaign_id else None)):
            if key is None:
                continue
            row = bucket.setdefault(key, {'chave': key, 'rotulo': label, 'oportunidades': 0, 'ganhas': 0, 'perdidas': 0,
                                          'valor_ganho_centavos': 0})
            row['oportunidades'] += 1
            if o.stage == Opportunity.Stage.WON:
                row['ganhas'] += 1
                row['valor_ganho_centavos'] += o.value_cents
            elif o.stage == Opportunity.Stage.LOST:
                row['perdidas'] += 1
    for bucket in (by_source, by_campaign):
        for row in bucket.values():
            closed = row['ganhas'] + row['perdidas']
            row['conversao_pct'] = round(100 * row['ganhas'] / closed) if closed else None
    forms = CaptureForm.objects.filter(organization=org)
    return {'dias': days, 'por_origem': sorted(by_source.values(), key=lambda r: -r['oportunidades']),
            'por_campanha': sorted(by_campaign.values(), key=lambda r: -r['oportunidades']),
            'formularios': [{'id': f.pk, 'titulo': f.title, 'envios': f.submissions} for f in forms], 'satisfacao': nps(org, days)}
