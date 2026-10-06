"""Monta o contexto (as variáveis) de cada gatilho a partir de REFERÊNCIAS (ids), CAD-172.

A fila (Redis) só carrega ids; os dados pessoais são lidos no worker, direto do banco (cifrados em repouso)."""
from __future__ import annotations

from datetime import date

from django.utils import timezone
from django.utils.dateparse import parse_date

WEEKDAYS = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']


def br(d) -> str:
    if d is None:
        return ''
    if hasattr(d, 'tzinfo') and hasattr(d, 'hour'):
        d = timezone.localtime(d).date() if timezone.is_aware(d) else d.date()
    return d.strftime('%d/%m/%Y')


def _base(org) -> dict:
    today = timezone.localdate()
    return {'escritorio': {'nome': str(org)}, 'hoje': br(today), 'dia_semana': WEEKDAYS[today.weekday()]}


def _user(user) -> dict:
    if user is None:
        return {}
    return {'id': str(user.pk), 'nome': user.get_full_name() or user.email}


def _person(contact) -> dict:
    if contact is None:
        return {}
    name = (contact.name or '').strip()
    return {'id': contact.pk, 'nome': name, 'primeiro_nome': name.split(' ')[0] if name else '', 'tipo': contact.get_kind_display(),
            'tags': ', '.join(contact.tags or [])}


def _is_member(org, user) -> bool:
    return user is not None and user.memberships.filter(organization=org, is_active=True).exists()


def document_confirmed(org, refs):
    from django.contrib.auth import get_user_model

    from documents.models import DocumentExtraction

    ex = DocumentExtraction.objects.filter(pk=refs.get('extraction_id'), document__organization=org).select_related('document').first()
    if ex is None:
        return None
    fields = ex.fields or {}
    dated = sorted(((parse_date(str(p.get('data') or '')), p) for p in fields.get('prazos') or [] if isinstance(p, dict)),
                   key=lambda x: x[0] or date.max)
    dated = [(d, p) for d, p in dated if d]
    prazo = {}
    if dated:
        d, p = dated[0]
        prazo = {'data': br(d), 'iso': d.isoformat(), 'descricao': str(p.get('descricao') or 'prazo'), 'fatal': 'sim' if p.get('fatal') else 'não'}
    user = get_user_model().objects.filter(pk=refs.get('user_id')).first() if refs.get('user_id') else ex.reviewed_by
    ctx = {**_base(org), 'documento': {'id': ex.document_id, 'nome': ex.document.nome, 'tipo': str(fields.get('tipo_documento') or '')},
           'processo': {'cnj': str(fields.get('numero_processo') or '')}, 'prazo': prazo, 'prazos': {'quantidade': len(dated)},
           'resumo': str(fields.get('resumo') or '')[:500], 'responsavel': _user(user if _is_member(org, user) else None)}
    return ctx, f'Documento {ex.document.nome}'


def case_movement(org, refs):
    from research.models import CaseMovement, MonitoredCase

    case = MonitoredCase.objects.filter(pk=refs.get('case_id'), organization=org).select_related('responsavel', 'client').first()
    if case is None:
        return None
    moves = list(CaseMovement.objects.filter(case=case, digest__in=refs.get('digests') or []).order_by('-occurred_at', '-pk'))
    if not moves:
        return None
    m = moves[0]
    ctx = {**_base(org), 'processo': {'id': case.pk, 'cnj': case.cnj, 'tribunal': case.tribunal, 'apelido': case.label},
           'andamento': {'nome': m.name, 'data': br(m.occurred_at), 'complemento': m.complement},
           'andamentos': {'quantidade': len(moves)}, 'cliente': _person(case.client),
           'responsavel': _user(case.responsavel if _is_member(org, case.responsavel) else None)}
    return ctx, f'Processo {case.cnj}'


def deadline_soon(org, refs):
    from tasks.models import UserTask

    task = UserTask.objects.filter(pk=refs.get('task_id'), completed=False).select_related('responsavel').first()
    if task is None or not _is_member(org, task.responsavel):
        return None
    day = timezone.localtime(task.scheduled_at).date()
    ctx = {**_base(org), 'tarefa': {'id': task.pk, 'titulo': task.titulo}, 'prazo': {'data': br(day), 'iso': day.isoformat()},
           'dias_uteis_restantes': str(refs.get('dias', '')), 'responsavel': _user(task.responsavel)}
    return ctx, task.titulo


def contact_created(org, refs):
    from django.contrib.auth import get_user_model

    from contacts.models import Contact

    contact = Contact.objects.filter(pk=refs.get('contact_id'), organization=org).first()
    if contact is None:
        return None
    user = get_user_model().objects.filter(pk=refs.get('user_id')).first() if refs.get('user_id') else None
    ctx = {**_base(org), 'contato': _person(contact), 'responsavel': _user(user if _is_member(org, user) else None)}
    return ctx, f'Contato {contact.name}'


def publication_new(org, refs):
    from publications.models import Publication

    pub = Publication.objects.filter(pk=refs.get('publication_id'), organization=org).select_related(
        'case__client', 'case__responsavel', 'watch__responsavel').first()
    if pub is None:
        return None
    t = pub.triage or {}
    resp = pub.watch.responsavel if pub.watch_id and pub.watch.responsavel_id else (pub.case.responsavel if pub.case_id else None)
    prazo = {'dias': str(t.get('prazo_dias') or ''), 'fatal': 'sim' if t.get('fatal') else 'não'}
    if pub.vencimento:
        prazo.update(data=br(pub.vencimento), iso=pub.vencimento.isoformat())
    ctx = {**_base(org), 'publicacao': {'id': pub.pk, 'ato': t.get('ato', ''), 'tipo': pub.tipo, 'tribunal': pub.tribunal,
                                        'orgao': pub.orgao, 'providencia': t.get('providencia', '')},
           'processo': {'cnj': pub.cnj}, 'prazo': prazo, 'resumo': t.get('resumo', ''),
           'cliente': _person(pub.case.client if pub.case_id else None),
           'responsavel': _user(resp if _is_member(org, resp) else None)}
    return ctx, f'Publicação {pub.tribunal} {pub.cnj}'.strip()


def receivable_due(org, refs):
    from carteira.models import Receivable
    from carteira.services import brl, overdue_days

    rec = Receivable.objects.filter(pk=refs.get('receivable_id'), organization=org).select_related('contact').first()
    if rec is None:
        return None
    ctx = {**_base(org), 'honorario': {'id': rec.pk, 'descricao': rec.description, 'valor': brl(rec.amount_cents),
                                       'vencimento': br(rec.due_date), 'link_pagamento': rec.payment_url,
                                       'dias_atraso': str(overdue_days(rec))},
           'cliente': _person(rec.contact), 'responsavel': {}}
    return ctx, f'Honorário {rec.description}'


def schedule(org, refs):
    return {**_base(org), 'responsavel': {}}, f'Agenda de {br(timezone.localdate())}'


def email_received(org, refs):
    from emails.models import EmailTriage
    tri = EmailTriage.objects.filter(email_id=refs.get('email_id'), organization=org).select_related('email', 'contact').first()
    if tri is None:
        return None
    em = tri.email
    prazo = {'data': br(tri.due_date), 'iso': tri.due_date.isoformat()} if tri.due_date else {}
    ctx = {**_base(org), 'email': {'id': em.pk, 'assunto': em.subject, 'remetente': em.sender, 'categoria': tri.category,
                                   'urgencia': tri.urgency, 'resumo': tri.summary[:500], 'acao_sugerida': tri.suggested_action},
           'prazo': prazo, 'contato': _person(tri.contact), 'responsavel': _user(em.mailbox.user if _is_member(org, em.mailbox.user) else None)}
    return ctx, f'E-mail: {em.subject}'[:200]


def calendar_event(org, refs):
    from gcal.models import ExternalEvent
    ev = ExternalEvent.objects.filter(pk=refs.get('event_id'), organization=org, cancelled=False).select_related(
        'case', 'contact', 'link__user').first()
    if ev is None:
        return None
    local = timezone.localtime(ev.start)
    client = ev.contact or (ev.case.client if ev.case_id else None)
    ctx = {**_base(org), 'evento': {'id': ev.pk, 'titulo': ev.title, 'tipo': ev.kind, 'data': br(local), 'iso': local.date().isoformat(),
                                    'hora': '' if ev.all_day else local.strftime('%H:%M'), 'local': ev.location},
           'prazo': {'data': br(local), 'iso': local.date().isoformat()},
           'dias_restantes': str(refs.get('dias', '')), 'processo': {'cnj': ev.case.cnj if ev.case_id else ''},
           'cliente': _person(client), 'responsavel': _user(ev.link.user if _is_member(org, ev.link.user) else None)}
    return ctx, f'Agenda: {ev.title}'[:200]


def task_overdue(org, refs):
    from tasks.models import UserTask
    task = UserTask.objects.filter(pk=refs.get('task_id'), completed=False).select_related('responsavel').first()
    if task is None or not _is_member(org, task.responsavel):
        return None
    day = timezone.localtime(task.scheduled_at).date()
    ctx = {**_base(org), 'tarefa': {'id': task.pk, 'titulo': task.titulo, 'prioridade': task.get_priority_display(), 'data': br(day)},
           'prazo': {'data': br(day), 'iso': day.isoformat()},
           'dias_atraso': str((timezone.localdate() - day).days), 'responsavel': _user(task.responsavel)}
    return ctx, f'Atrasada: {task.titulo}'[:200]


def receivable_paid(org, refs):
    from carteira.models import Receivable
    from carteira.services import brl
    rec = Receivable.objects.filter(pk=refs.get('receivable_id'), organization=org, status=Receivable.Status.PAID).select_related('contact').first()
    if rec is None:
        return None
    ctx = {**_base(org), 'honorario': {'id': rec.pk, 'descricao': rec.description, 'valor': brl(rec.paid_cents or rec.amount_cents),
                                       'data_pagamento': br(rec.paid_at)},
           'cliente': _person(rec.contact), 'responsavel': {}}
    return ctx, f'Pago: {rec.description}'[:200]


def opportunity_stage(org, refs):
    from carteira.models import Opportunity
    opp = Opportunity.objects.filter(pk=refs.get('opportunity_id'), organization=org).select_related('contact', 'owner').first()
    if opp is None:
        return None
    ctx = {**_base(org), 'oportunidade': {'id': opp.pk, 'titulo': opp.title, 'etapa': opp.stage, 'etapa_anterior': refs.get('de', ''),
                                          'area': opp.area, 'proxima_acao': opp.next_action},
           'cliente': _person(opp.contact), 'responsavel': _user(opp.owner if _is_member(org, opp.owner) else None)}
    return ctx, f'Funil: {opp.title} → {opp.get_stage_display()}'[:200]


def agreement_created(org, refs):
    from carteira.models import FeeAgreement
    from carteira.services import brl
    ag = FeeAgreement.objects.filter(pk=refs.get('agreement_id'), organization=org).select_related('contact', 'created_by').first()
    if ag is None:
        return None
    ctx = {**_base(org), 'contrato': {'id': ag.pk, 'titulo': ag.title, 'tipo': ag.get_kind_display(), 'valor': brl(ag.total_cents),
                                      'parcelas': str(ag.installments)},
           'cliente': _person(ag.contact), 'responsavel': _user(ag.created_by if _is_member(org, ag.created_by) else None)}
    return ctx, f'Contrato: {ag.title}'[:200]


def document_uploaded(org, refs):
    from django.contrib.auth import get_user_model

    from documents.models import Document
    doc = Document.objects.filter(pk=refs.get('document_id'), organization=org).first()
    if doc is None:
        return None
    user = get_user_model().objects.filter(pk=refs.get('user_id')).first() if refs.get('user_id') else None
    ctx = {**_base(org), 'documento': {'id': doc.pk, 'nome': doc.nome, 'tipo': doc.tipo, 'cliente': refs.get('cliente', '')},
           'responsavel': _user(user if _is_member(org, user) else None)}
    return ctx, f'Documento enviado: {doc.nome}'[:200]


def portal_viewed(org, refs):
    from portal.models import PortalLink
    link = PortalLink.objects.filter(pk=refs.get('link_id'), organization=org).select_related('contact').first()
    if link is None:
        return None
    ctx = {**_base(org), 'cliente': _person(link.contact), 'portal': {'acessos': str(link.access_count)}, 'responsavel': {}}
    return ctx, f'Portal aberto: {link.contact.name}'[:200]


# ----------------------------------------------------------------------------- CAD-223
def _yes(v) -> str:
    return 'sim' if v else 'não'


def lead_captured(org, refs):
    from carteira.models import Opportunity
    from marketing.models import CaptureForm
    opp = Opportunity.objects.filter(pk=refs.get('opportunity_id'), organization=org).select_related('contact', 'campaign', 'owner').first()
    if opp is None:
        return None
    form = CaptureForm.objects.filter(pk=refs.get('form_id'), organization=org).first()
    c = opp.contact
    ctx = {**_base(org), 'oportunidade': {'id': opp.pk, 'titulo': opp.title, 'area': opp.area},
           'formulario': {'titulo': form.title if form else ''}, 'campanha': {'nome': opp.campaign.name if opp.campaign_id else ''},
           'consentimento': {'whatsapp': _yes(c.whatsapp_consent), 'email': _yes(c.email_consent)},
           'cliente': _person(c), 'responsavel': _user(opp.owner if _is_member(org, opp.owner) else None)}
    return ctx, f'Novo contato pelo formulário: {c.name}'[:200]


def survey_answered(org, refs):
    from marketing.models import SatisfactionSurvey
    sv = SatisfactionSurvey.objects.filter(pk=refs.get('survey_id'), organization=org, score__isnull=False).select_related('contact').first()
    if sv is None:
        return None
    ctx = {**_base(org), 'pesquisa': {'nota': str(sv.score), 'classificacao': sv.category, 'motivo': sv.reason,
                                      'tem_comentario': _yes(sv.comment)},
           'cliente': _person(sv.contact), 'responsavel': {}}
    return ctx, f'Avaliação {sv.score}/10 — {sv.contact.name}'[:200]


def nfse_issued(org, refs):
    from carteira.models import Receivable
    from carteira.services import brl
    rec = Receivable.objects.filter(pk=refs.get('receivable_id'), organization=org).select_related('contact').first()
    if rec is None:
        return None
    ctx = {**_base(org), 'honorario': {'id': rec.pk, 'descricao': rec.description, 'valor': brl(rec.paid_cents or rec.amount_cents)},
           'nota': {'link': rec.nfse_url, 'status': rec.nfse_status}, 'cliente': _person(rec.contact), 'responsavel': {}}
    return ctx, f'NFS-e emitida: {rec.description}'[:200]


def expense_created(org, refs):
    from carteira.models import Expense
    from carteira.services import brl
    e = Expense.objects.filter(pk=refs.get('expense_id'), organization=org).select_related('contact', 'created_by').first()
    if e is None:
        return None
    ctx = {**_base(org), 'despesa': {'id': e.pk, 'descricao': e.description, 'categoria': e.category, 'valor': brl(e.amount_cents),
                                     'valor_centavos': str(e.amount_cents), 'reembolsavel': _yes(e.reimbursable)},
           'cliente': _person(e.contact), 'responsavel': _user(e.created_by if _is_member(org, e.created_by) else None)}
    return ctx, f'Despesa: {e.description}'[:200]


def court_suspension(org, refs):
    from forense.models import CourtSuspension
    from research.models import MonitoredCase
    sp = CourtSuspension.objects.filter(pk=refs.get('suspension_id')).first()
    if sp is None:
        return None
    cases = MonitoredCase.objects.filter(organization=org, is_active=True)
    if sp.tribunal:
        cases = cases.filter(tribunal__iexact=sp.tribunal)
    ctx = {**_base(org), 'suspensao': {'tribunal': sp.tribunal.upper() or 'Nacional', 'tipo': sp.get_kind_display(), 'inicio': br(sp.start),
                                       'fim': br(sp.end), 'motivo': sp.reason, 'fonte': sp.source_url, 'comarca': sp.comarca},
           'processos': {'quantidade': str(cases.count())}, 'responsavel': {}}
    return ctx, f'Suspensão {sp.tribunal.upper() or "nacional"}: {br(sp.start)} a {br(sp.end)}'[:200]


def contact_birthday(org, refs):
    from contacts.models import Contact
    c = Contact.objects.filter(pk=refs.get('contact_id'), organization=org).first()
    if c is None:
        return None
    return {**_base(org), 'cliente': _person(c), 'responsavel': {}}, f'Aniversário: {c.name}'[:200]


def opportunity_stale(org, refs):
    from carteira.models import Opportunity
    opp = Opportunity.objects.filter(pk=refs.get('opportunity_id'), organization=org).select_related('contact', 'owner').first()
    if opp is None:
        return None
    days = (timezone.now() - opp.stage_changed_at).days
    ctx = {**_base(org), 'oportunidade': {'id': opp.pk, 'titulo': opp.title, 'etapa': opp.get_stage_display(), 'dias_parada': str(days),
                                          'proxima_acao': opp.next_action},
           'cliente': _person(opp.contact), 'responsavel': _user(opp.owner if _is_member(org, opp.owner) else None)}
    return ctx, f'Parada há {days} dias: {opp.title}'[:200]


def case_stale(org, refs):
    from research.models import MonitoredCase
    case = MonitoredCase.objects.filter(pk=refs.get('case_id'), organization=org).select_related('client', 'responsavel').first()
    if case is None:
        return None
    last = case.last_movement_at or case.created_at
    days = (timezone.now() - last).days
    ctx = {**_base(org), 'processo': {'id': case.pk, 'cnj': case.cnj, 'tribunal': case.tribunal, 'apelido': case.label or '',
                                      'ultimo_andamento': br(last), 'dias_parado': str(days)},
           'cliente': _person(case.client), 'responsavel': _user(case.responsavel if _is_member(org, case.responsavel) else None)}
    return ctx, f'Sem andamento: {case.label or case.cnj}'[:200]


def contract_ending(org, refs):
    from carteira.models import FeeAgreement
    ag = FeeAgreement.objects.filter(pk=refs.get('agreement_id'), organization=org).select_related('contact', 'created_by').first()
    if ag is None:
        return None
    last = ag.receivables.filter(status='aberto').order_by('-due_date').first()
    ctx = {**_base(org), 'contrato': {'id': ag.pk, 'titulo': ag.title, 'tipo': ag.get_kind_display(),
                                      'ultima_parcela': br(last.due_date) if last else ''},
           'cliente': _person(ag.contact), 'responsavel': _user(ag.created_by if _is_member(org, ag.created_by) else None)}
    return ctx, f'Contrato terminando: {ag.title}'[:200]


def monthly_goal(org, refs):
    from carteira.reports import goal
    from carteira.services import brl
    g = goal(org)
    if not g['meta_centavos']:
        return None
    ctx = {**_base(org), 'meta': {'valor': brl(g['meta_centavos']), 'recebido': brl(g['recebido_centavos']), 'pct': str(g['pct']),
                                  'previsto': brl(g['previsto_restante_centavos']), 'atingida': _yes(g['pct'] >= 100)},
           'responsavel': {}}
    return ctx, f'Meta do mês: {g["pct"]}%'[:200]


BUILDERS = {'document_confirmed': document_confirmed, 'case_movement': case_movement, 'deadline_soon': deadline_soon,
            'contact_created': contact_created, 'schedule': schedule, 'publication_new': publication_new,
            'receivable_due': receivable_due, 'email_received': email_received, 'calendar_event': calendar_event,
            'task_overdue': task_overdue, 'receivable_paid': receivable_paid, 'opportunity_stage': opportunity_stage,
            'agreement_created': agreement_created, 'document_uploaded': document_uploaded, 'portal_viewed': portal_viewed,
            'lead_captured': lead_captured, 'survey_answered': survey_answered, 'nfse_issued': nfse_issued,
            'expense_created': expense_created, 'court_suspension': court_suspension, 'contact_birthday': contact_birthday,
            'opportunity_stale': opportunity_stale, 'case_stale': case_stale, 'contract_ending': contract_ending,
            'monthly_goal': monthly_goal}


def build(trigger, org, refs):
    """(contexto, título) ou None se o objeto do evento sumiu / não é deste escritório."""
    return BUILDERS[trigger](org, refs or {})


def sample_refs(trigger, org) -> dict | None:
    """Referências do evento real mais recente do escritório, para a simulação usar dados de verdade quando houver."""
    if trigger == 'document_confirmed':
        from documents.models import DocumentExtraction
        ex = DocumentExtraction.objects.filter(document__organization=org, status=DocumentExtraction.Status.CONFIRMED).order_by('-reviewed_at').first()
        return {'extraction_id': ex.pk} if ex else None
    if trigger == 'case_movement':
        from research.models import CaseMovement
        m = CaseMovement.objects.filter(case__organization=org).order_by('-created_at').first()
        return {'case_id': m.case_id, 'digests': [m.digest]} if m else None
    if trigger == 'deadline_soon':
        from tasks.models import UserTask
        t = UserTask.objects.filter(responsavel__memberships__organization=org, responsavel__memberships__is_active=True,
                                    completed=False, scheduled_at__gte=timezone.now()).order_by('scheduled_at').first()
        return {'task_id': t.pk, 'dias': 3} if t else None
    if trigger == 'contact_created':
        from contacts.models import Contact
        c = Contact.objects.filter(organization=org).order_by('-created_at').first()
        return {'contact_id': c.pk} if c else None
    if trigger == 'publication_new':
        from publications.models import Publication
        p = Publication.objects.filter(organization=org).order_by('-created_at').first()
        return {'publication_id': p.pk} if p else None
    if trigger == 'receivable_due':
        from carteira.models import Receivable
        r = Receivable.objects.filter(organization=org, status='aberto').order_by('due_date').first()
        return {'receivable_id': r.pk} if r else None
    latest = {   # CAD-222: (modelo, filtro, refs)
        'email_received': ('emails.EmailTriage', 'organization', lambda o: {'email_id': o.email_id}),
        'calendar_event': ('gcal.ExternalEvent', 'organization', lambda o: {'event_id': o.pk, 'dias': 1}),
        'receivable_paid': ('carteira.Receivable', 'organization', lambda o: {'receivable_id': o.pk}),
        'opportunity_stage': ('carteira.Opportunity', 'organization', lambda o: {'opportunity_id': o.pk, 'de': ''}),
        'agreement_created': ('carteira.FeeAgreement', 'organization', lambda o: {'agreement_id': o.pk}),
        'document_uploaded': ('documents.Document', 'organization', lambda o: {'document_id': o.pk}),
        'portal_viewed': ('portal.PortalLink', 'organization', lambda o: {'link_id': o.pk}),
        'lead_captured': ('carteira.Opportunity', 'organization', lambda o: {'opportunity_id': o.pk}),
        'survey_answered': ('marketing.SatisfactionSurvey', 'organization', lambda o: {'survey_id': o.pk}),
        'nfse_issued': ('carteira.Receivable', 'organization', lambda o: {'receivable_id': o.pk}),
        'expense_created': ('carteira.Expense', 'organization', lambda o: {'expense_id': o.pk}),
        'contact_birthday': ('contacts.Contact', 'organization', lambda o: {'contact_id': o.pk}),
        'opportunity_stale': ('carteira.Opportunity', 'organization', lambda o: {'opportunity_id': o.pk}),
        'case_stale': ('research.MonitoredCase', 'organization', lambda o: {'case_id': o.pk}),
        'contract_ending': ('carteira.FeeAgreement', 'organization', lambda o: {'agreement_id': o.pk}),
    }
    if trigger in latest:
        from django.apps import apps
        label, field, refs = latest[trigger]
        qs = apps.get_model(label).objects.filter(**{field: org})
        if trigger == 'receivable_paid':
            qs = qs.filter(status='pago')
        if trigger == 'nfse_issued':
            qs = qs.exclude(nfse_id='')
        if trigger == 'survey_answered':
            qs = qs.filter(score__isnull=False)
        if trigger == 'lead_captured':
            qs = qs.filter(contact__source='form')
        obj = qs.order_by('-pk').first()
        return refs(obj) if obj else None
    if trigger == 'court_suspension':
        from forense.models import CourtSuspension
        sp = CourtSuspension.objects.order_by('-pk').first()
        return {'suspension_id': sp.pk} if sp else None
    if trigger == 'monthly_goal':
        from carteira.models import FinanceSettings
        return {} if FinanceSettings.objects.filter(organization=org, monthly_goal_cents__gt=0).exists() else None
    if trigger == 'task_overdue':
        from tasks.models import UserTask
        t = UserTask.objects.filter(responsavel__memberships__organization=org, completed=False,
                                    scheduled_at__lt=timezone.now()).order_by('-scheduled_at').first()
        return {'task_id': t.pk} if t else None
    return {}


def example(trigger, org) -> tuple[dict, str]:
    """Contexto fictício (quando o escritório ainda não tem nenhum evento desse tipo)."""
    base = {**_base(org), 'responsavel': {'nome': 'Responsável (exemplo)'}}
    person = {'id': None, 'nome': 'Maria Exemplo', 'primeiro_nome': 'Maria', 'tipo': 'Cliente', 'tags': 'exemplo'}
    today = timezone.localdate()
    return {
        'document_confirmed': {**base, 'documento': {'nome': 'intimacao-exemplo.pdf', 'tipo': 'Intimação'},
                               'processo': {'cnj': '0000000-00.2026.8.26.0000'},
                               'prazo': {'data': br(today), 'iso': today.isoformat(), 'descricao': 'Contestação', 'fatal': 'sim'},
                               'prazos': {'quantidade': 1}, 'resumo': 'Resumo de exemplo.'},
        'case_movement': {**base, 'processo': {'cnj': '0000000-00.2026.8.26.0000', 'tribunal': 'tjsp', 'apelido': 'Exemplo'},
                          'andamento': {'nome': 'Juntada de petição', 'data': br(today), 'complemento': ''},
                          'andamentos': {'quantidade': 1}, 'cliente': person},
        'deadline_soon': {**base, 'tarefa': {'titulo': 'Prazo: Contestação'}, 'prazo': {'data': br(today), 'iso': today.isoformat()},
                          'dias_uteis_restantes': '3'},
        'contact_created': {**base, 'contato': person},
        'schedule': base,
        'publication_new': {**base, 'publicacao': {'ato': 'Sentença', 'tipo': 'Intimação', 'tribunal': 'TJSP', 'orgao': '1ª Vara Cível',
                                                   'providencia': 'Avaliar recurso.'},
                            'processo': {'cnj': '0000000-00.2026.8.26.0000'},
                            'prazo': {'data': br(today), 'iso': today.isoformat(), 'dias': '15', 'fatal': 'sim'},
                            'resumo': 'Sentença de procedência (exemplo).', 'cliente': person},
        'receivable_due': {**base, 'honorario': {'descricao': 'Parcela 2/5 — Honorários (exemplo)', 'valor': 'R$ 1.200,00',
                                                 'vencimento': br(today), 'link_pagamento': 'https://www.asaas.com/i/exemplo',
                                                 'dias_atraso': '3'}, 'cliente': person},
        'email_received': {**base, 'email': {'assunto': 'Dúvida sobre a audiência', 'remetente': 'maria@exemplo.com', 'categoria': 'cliente',
                                             'urgencia': 'media', 'resumo': 'Cliente pergunta o horário da audiência.',
                                             'acao_sugerida': 'Responder com data e local.'}, 'prazo': {}, 'contato': person},
        'calendar_event': {**base, 'evento': {'titulo': 'Audiência de conciliação — Maria Exemplo', 'tipo': 'audiencia', 'data': br(today),
                                              'iso': today.isoformat(), 'hora': '14:00', 'local': 'Fórum Central'},
                           'prazo': {'data': br(today), 'iso': today.isoformat()}, 'dias_restantes': '1',
                           'processo': {'cnj': '0000000-00.2026.8.26.0000'}, 'cliente': person},
        'task_overdue': {**base, 'tarefa': {'titulo': 'Protocolar petição (exemplo)', 'prioridade': 'Alta', 'data': br(today)},
                         'prazo': {'data': br(today), 'iso': today.isoformat()}, 'dias_atraso': '1'},
        'receivable_paid': {**base, 'honorario': {'descricao': 'Parcela 1/3 (exemplo)', 'valor': 'R$ 2.000,00', 'data_pagamento': br(today)},
                            'cliente': person},
        'opportunity_stage': {**base, 'oportunidade': {'titulo': 'Divórcio consensual (exemplo)', 'etapa': 'reuniao', 'etapa_anterior': 'novo',
                                                       'area': 'Família', 'proxima_acao': 'Reunião na terça'}, 'cliente': person},
        'agreement_created': {**base, 'contrato': {'titulo': 'Ação de alimentos (exemplo)', 'tipo': 'Parcelado', 'valor': 'R$ 6.000,00',
                                                   'parcelas': '3'}, 'cliente': person},
        'document_uploaded': {**base, 'documento': {'nome': 'procuracao-exemplo.pdf', 'tipo': 'Procuração', 'cliente': 'Maria Exemplo'}},
        'portal_viewed': {**base, 'cliente': person, 'portal': {'acessos': '3'}},
        'lead_captured': {**base, 'oportunidade': {'titulo': 'Previdenciário — Maria Exemplo', 'area': 'Previdenciário'},
                          'formulario': {'titulo': 'Fale com o escritório'}, 'campanha': {'nome': 'Aposentadoria 2026'},
                          'consentimento': {'whatsapp': 'sim', 'email': 'sim'}, 'cliente': person},
        'survey_answered': {**base, 'pesquisa': {'nota': '6', 'classificacao': 'detrator', 'motivo': 'Contrato concluído',
                                                 'tem_comentario': 'sim'}, 'cliente': person},
        'nfse_issued': {**base, 'honorario': {'descricao': 'Parcela 1/3 (exemplo)', 'valor': 'R$ 2.000,00'},
                        'nota': {'link': 'https://www.asaas.com/nfse/exemplo', 'status': 'AUTHORIZED'}, 'cliente': person},
        'expense_created': {**base, 'despesa': {'descricao': 'Custas iniciais (exemplo)', 'categoria': 'custas', 'valor': 'R$ 350,00',
                                                'valor_centavos': '35000', 'reembolsavel': 'sim'}, 'cliente': person},
        'court_suspension': {**base, 'suspensao': {'tribunal': 'TJSP', 'tipo': 'Suspensão de prazos', 'inicio': br(today), 'fim': br(today),
                                                   'motivo': 'Portaria de exemplo', 'fonte': 'https://www.tjsp.jus.br/', 'comarca': ''},
                             'processos': {'quantidade': '4'}},
        'contact_birthday': {**base, 'cliente': person},
        'opportunity_stale': {**base, 'oportunidade': {'titulo': 'Revisional de contrato (exemplo)', 'etapa': 'Proposta enviada',
                                                       'dias_parada': '10', 'proxima_acao': 'Ligar para a cliente'}, 'cliente': person},
        'case_stale': {**base, 'processo': {'cnj': '0000000-00.2026.8.26.0000', 'tribunal': 'tjsp', 'apelido': 'Exemplo',
                                            'ultimo_andamento': br(today), 'dias_parado': '90'}, 'cliente': person},
        'contract_ending': {**base, 'contrato': {'titulo': 'Assessoria mensal (exemplo)', 'tipo': 'Mensal', 'ultima_parcela': br(today)},
                            'cliente': person},
        'monthly_goal': {**base, 'meta': {'valor': 'R$ 30.000,00', 'recebido': 'R$ 21.000,00', 'pct': '70', 'previsto': 'R$ 6.000,00',
                                          'atingida': 'não'}},
    }[trigger], 'Exemplo fictício'
