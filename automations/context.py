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


def schedule(org, refs):
    return {**_base(org), 'responsavel': {}}, f'Agenda de {br(timezone.localdate())}'


BUILDERS = {'document_confirmed': document_confirmed, 'case_movement': case_movement, 'deadline_soon': deadline_soon,
            'contact_created': contact_created, 'schedule': schedule}


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
    }[trigger], 'Exemplo fictício'
