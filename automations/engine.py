"""Motor das regras de automação (CAD-172).

Fluxo: um evento chama ``emit`` (só ids) → a fila roda ``execute`` → monta o contexto → confere as condições → planeja as ações
(textos renderizados, destinatário resolvido, consentimento conferido) → executa as internas; as externas esperam aprovação
(se a regra pede) → ``approve``/``reject``. ``simulate`` faz o mesmo planejamento sem efeito nenhum.

Salvaguardas: regra só liga depois de simulada; limite diário de execuções por regra; um evento roda no máximo uma vez por regra
(``dedupe_key``); consentimento é conferido de novo na hora do envio; aprovação expira em 7 dias; ERP sempre com aprovação."""
from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from audit import service as audit
from automations import context as ctxmod
from automations.catalog import ACTIONS, EXTERNAL
from automations.models import Rule, RuleRun

logger = logging.getLogger(__name__)

DAILY_LIMIT = 200
APPROVAL_TTL_DAYS = 7
VAR = re.compile(r'\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}')
S = RuleRun.Status


# ----------------------------------------------------------------------------- variáveis e condições
def resolve(ctx: dict, path: str):
    cur = ctx
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def render(text: str, ctx: dict) -> str:
    def _sub(m):
        value = resolve(ctx, m.group(1))
        return '' if value is None or isinstance(value, (dict, list)) else str(value)
    return VAR.sub(_sub, text or '')


def _norm(v) -> str:
    return str(v if v is not None else '').strip().lower()


def condition_ok(cond: dict, ctx: dict) -> bool:
    value = resolve(ctx, cond['field'])
    filled = value not in (None, '', [], {})
    op, expected = cond['op'], cond.get('value')
    if op == 'exists':
        return filled
    if op == 'not_exists':
        return not filled
    if op == 'eq':
        return _norm(value) == _norm(expected)
    if op == 'neq':
        return _norm(value) != _norm(expected)
    if op == 'contains':
        return _norm(expected) in _norm(value)
    if op == 'in':
        return _norm(value) in {_norm(x) for x in expected or []}
    return False


def matches(conditions, ctx) -> bool:
    return all(condition_ok(c, ctx) for c in conditions or [])


# ----------------------------------------------------------------------------- planejamento (sem efeitos)
def _owner_id(org):
    m = org.members.filter(role='OWNER', is_active=True).order_by('pk').first()
    return str(m.user_id) if m else None


def _due(org, params, ctx):
    from forense.calendar import Calendar

    cal = Calendar(org)
    today = timezone.localdate()
    if params['quando'] == 'prazo':
        iso = resolve(ctx, 'prazo.iso')
        if not iso:
            return None, 'O evento não tem data de prazo.'
        day = datetime.strptime(iso, '%Y-%m-%d').date()
        due = cal.back(day, params.get('antecedencia', 0))
        return max(due, today), ''
    return cal.add(today, params.get('dias', 0)), ''


def _contact(org, ctx, dest):
    from contacts.models import Contact

    cid = resolve(ctx, f'{dest}.id')
    return Contact.objects.filter(organization=org, pk=cid).first() if cid else None


def plan_step(org, rule, action, ctx) -> dict:
    kind, p = action['type'], action['params']
    step = {'tipo': kind, 'rotulo': ACTIONS[kind]['label'], 'externo': kind in EXTERNAL, 'status': 'planejado', 'detalhe': '', 'dados': {}}
    if kind == 'create_task':
        due, why = _due(org, p, ctx)
        if due is None:
            return {**step, 'status': 'bloqueado', 'detalhe': why}
        resp = resolve(ctx, 'responsavel.id') or _owner_id(org)
        title = render(p['titulo'], ctx)[:255] or 'Tarefa da automação'
        step['dados'] = {'titulo': title, 'descricao': render(p.get('descricao', ''), ctx)[:2000], 'prioridade': p['prioridade'],
                         'data': due.isoformat(), 'responsavel_id': resp}
        step['detalhe'] = f'Tarefa "{title}" para {ctxmod.br(due)} ({resolve(ctx, "responsavel.nome") or "dono do escritório"}).'
    elif kind == 'notify':
        step['dados'] = {'titulo': render(p['titulo'], ctx)[:120], 'mensagem': render(p['mensagem'], ctx)[:500],
                         'responsavel_id': resolve(ctx, 'responsavel.id')}
        step['detalhe'] = f'Aviso no sino: {step["dados"]["titulo"]}.'
    elif kind in ('send_whatsapp', 'send_email'):
        channel = 'whatsapp' if kind == 'send_whatsapp' else 'email'
        contact = _contact(org, ctx, p['destinatario'])
        if contact is None:
            name = resolve(ctx, f'{p["destinatario"]}.nome')
            why = (f'Simulação com contato de exemplo ({name}).' if name else
                   f'O evento não tem {p["destinatario"]} vinculado (vincule o cliente ao processo).')
            return {**step, 'status': 'bloqueado', 'detalhe': why,
                    'dados': {'mensagem': render(p['mensagem'], ctx)[:1000], 'assunto': render(p.get('assunto', ''), ctx)[:150]}}
        data = {'contato_id': contact.pk, 'nome': contact.name, 'mensagem': render(p['mensagem'], ctx)[:1000]}
        if channel == 'email':
            data['assunto'] = render(p['assunto'], ctx)[:150]
        if not contact.can_receive(channel):
            return {**step, 'status': 'bloqueado', 'dados': data,
                    'detalhe': f'{contact.name} não autorizou {"WhatsApp" if channel == "whatsapp" else "e-mail"} '
                               f'(ou saiu da lista, ou não tem {"telefone" if channel == "whatsapp" else "e-mail"}).'}
        step['dados'] = data
        step['detalhe'] = f'{"WhatsApp" if channel == "whatsapp" else "E-mail"} para {contact.name}.'
    elif kind == 'team_chat':
        conn = _team_connection(org, p['canal'])
        names = {'slack': 'Slack', 'teams': 'Teams', 'telegram': 'Telegram'}
        if conn is None:
            return {**step, 'status': 'bloqueado', 'detalhe': f'Nenhuma conexão de {names[p["canal"]]} ativa (Integrações).'}
        step['dados'] = {'conexao_id': conn.pk, 'mensagem': render(p['mensagem'], ctx)[:1000]}
        step['detalhe'] = f'Aviso no {names[p["canal"]]} ({conn.name}).'
    else:   # erp_call
        from erp.models import ErpConnector

        conn = ErpConnector.objects.filter(organization=org, pk=p['conector_id'], is_active=True).first()
        if conn is None:
            return {**step, 'status': 'bloqueado', 'detalhe': 'Conector de ERP não encontrado ou desativado.'}
        step['dados'] = {'conector_id': conn.pk, 'conector': conn.name, 'operacao': p['operacao'],
                         'campos': {k: render(v, ctx)[:500] for k, v in p['dados'].items()}}
        step['detalhe'] = f'ERP {conn.name}: {p["operacao"]}' + ('' if conn.live_enabled else ' (execução real desligada no conector).')
    return step


def plan(org, rule, ctx) -> list:
    return [plan_step(org, rule, a, ctx) for a in rule.actions]


# ----------------------------------------------------------------------------- execução de um passo
def _whatsapp_connection(org):
    from integrations.models import AppConnection

    return (AppConnection.objects.filter(app_name='WHATSAPP', is_active=True, user__memberships__organization=org,
                                         user__memberships__is_active=True).order_by('-pk').first())


def _team_connection(org, canal):
    from integrations.models import AppConnection

    return (AppConnection.objects.filter(app_name=canal.upper(), is_active=True, user__memberships__organization=org,
                                         user__memberships__is_active=True).order_by('-pk').first())


def _digits_phone(raw: str) -> str:
    digits = re.sub(r'\D', '', raw or '')
    return f'55{digits}' if len(digits) in (10, 11) else digits


def perform(org, rule, run, step, index) -> dict:
    """Executa um passo planejado. Nunca levanta: devolve o passo com status 'feito' ou 'erro'."""
    d = step['dados']
    try:
        if step['tipo'] == 'create_task':
            from django.contrib.auth import get_user_model

            from tasks.models import UserTask

            user = get_user_model().objects.filter(pk=d.get('responsavel_id')).first() if d.get('responsavel_id') else None
            if user is None or not user.memberships.filter(organization=org, is_active=True).exists():
                raise ValueError('Responsável não encontrado no escritório.')
            day = datetime.strptime(d['data'], '%Y-%m-%d').date()
            task = UserTask.objects.create(titulo=d['titulo'], descricao=d['descricao'], priority=d['prioridade'], responsavel=user,
                                           scheduled_at=timezone.make_aware(datetime.combine(day, time(9, 0))))
            return {**step, 'status': 'feito', 'resultado': {'tarefa_id': task.pk}}
        if step['tipo'] == 'notify':
            from notifications.models import Notification
            from notifications.services import AUTOMACOES_LINK, notify

            notify(type=Notification.Type.AUTOMACAO, title=d['titulo'], description=d['mensagem'], organization=org,
                   actor_id=d.get('responsavel_id'), origem='Regras de automação', documento=rule.name, acao='Regra executada',
                   link=AUTOMACOES_LINK, dedupe_key=f'regra-{run.pk}-{index}')
            return {**step, 'status': 'feito'}
        if step['tipo'] in ('send_whatsapp', 'send_email'):
            from contacts.models import Contact

            channel = 'whatsapp' if step['tipo'] == 'send_whatsapp' else 'email'
            contact = Contact.objects.filter(organization=org, pk=d.get('contato_id')).first()
            if contact is None or not contact.can_receive(channel):          # consentimento conferido de novo na hora do envio
                return {**step, 'status': 'bloqueado', 'detalhe': 'Consentimento retirado ou contato removido antes do envio.'}
            if channel == 'whatsapp':
                conn = _whatsapp_connection(org)
                if conn is None:
                    raise ValueError('Nenhuma conexão de WhatsApp ativa no escritório (Integrações → WhatsApp).')
                from integrations.evolution import WhatsAppEvolutionExecutor
                from workflows.tasks import _evolution_credentials_from_connection

                base_url, api_key, instance = _evolution_credentials_from_connection(conn, org)
                WhatsAppEvolutionExecutor(base_url=base_url, api_key=api_key).send(
                    instance, {'number': _digits_phone(contact.phone), 'text': d['mensagem']})
            else:
                footer = (f'\n\n—\nVocê recebe esta mensagem porque autorizou o contato de {org}. '
                          'Para não receber mais, responda a este e-mail pedindo a remoção.')
                from integrations.services import send_office_email
                if not send_office_email(org, d['assunto'], d['mensagem'] + footer, [contact.email]):   # SMTP do escritório (CAD-174)
                    send_mail(d['assunto'], d['mensagem'] + footer, settings.DEFAULT_FROM_EMAIL, [contact.email], fail_silently=False)
            audit.log('message.sent', actor_type='system', organization=org, target=contact,
                      changes={'canal': channel, 'regra': rule.pk, 'execucao': run.pk},
                      data_categories=['contato'], legal_basis='consentimento')
            return {**step, 'status': 'feito'}
        if step['tipo'] == 'team_chat':
            from integrations.models import AppConnection
            from integrations.services import post_team_message

            conn = AppConnection.objects.filter(pk=d.get('conexao_id'), is_active=True, user__memberships__organization=org).first()
            if conn is None:
                raise ValueError('Conexão do chat da equipe removida ou desativada.')
            post_team_message(conn, d['mensagem'])
            audit.log('integration.call', actor_type='system', organization=org, target=conn,
                      changes={'app': conn.app_name, 'regra': rule.pk, 'execucao': run.pk}, legal_basis='execucao_contrato')
            return {**step, 'status': 'feito'}
        if step['tipo'] == 'erp_call':
            from erp import engine as erp_engine
            from erp.models import ErpCallLog, ErpConnector

            conn = ErpConnector.objects.filter(organization=org, pk=d['conector_id'], is_active=True).first()
            if conn is None:
                raise ValueError('Conector de ERP não encontrado ou desativado.')
            log = ErpCallLog(connector=conn, operation=d['operacao'][:60], dry_run=False, actor_id=run.decided_by_id)
            try:
                result = erp_engine.run(conn, d['operacao'], d['campos'], dry_run=False, confirmed=True)
            except erp_engine.ErpError as exc:
                log.error = str(exc)[:300]
                log.save()
                raise ValueError(str(exc)) from exc
            log.ok, log.status_code = result.get('ok', True), result['status_code']
            log.save()
            audit.log('integration.call', actor_type='system', organization=org, target=conn,
                      changes={'erp': conn.preset, 'operation': d['operacao'], 'status': result['status_code'], 'regra': rule.pk},
                      data_categories=['dados_processuais'], legal_basis='execucao_contrato')
            if not result.get('ok', True):
                raise ValueError(f'O ERP respondeu {result["status_code"]}.')
            return {**step, 'status': 'feito', 'resultado': {'status_code': result['status_code']}}
        raise ValueError('Ação desconhecida.')
    except Exception as exc:  # noqa: BLE001 — um passo com erro não derruba os outros; fica registrado
        logger.warning('Regra %s, execução %s, passo %s: %s', rule.pk, run.pk, index, exc.__class__.__name__)
        return {**step, 'status': 'erro', 'detalhe': str(exc)[:300] or exc.__class__.__name__}


def resolve_responsavel(run):
    for s in run.steps or []:
        rid = (s.get('dados') or {}).get('responsavel_id')
        if rid:
            return rid
    return run.decided_by_id


def final_status(steps) -> str:
    states = [s['status'] for s in steps]
    if 'aguardando' in states:
        return S.PENDING
    done = states.count('feito')
    bad = len(states) - done
    if bad == 0:
        return S.SUCCESS
    return S.PARTIAL if done else S.FAILED


def _notify_outcome(org, rule, run):
    from notifications.models import Notification
    from notifications.services import AUTOMACOES_LINK, notify

    if run.status == S.PENDING:
        notify(type=Notification.Type.AUTOMACAO, title='Automação aguardando aprovação', organization=org,
               description=f'{rule.name}: confira o texto e aprove o envio.', origem='Regras de automação', documento=rule.name,
               acao='Aprovação pendente', action_label='Revisar', link=f'{AUTOMACOES_LINK}?aba=aprovacoes',
               actor_id=resolve_responsavel(run), dedupe_key=f'regra-aprovar-{run.pk}')
    elif run.status in (S.FAILED, S.PARTIAL):
        notify(type=Notification.Type.ERRO, title='Automação com falha', organization=org,
               description=f'{rule.name}: {"nenhum" if run.status == S.FAILED else "algum"} passo não foi concluído.',
               origem='Regras de automação', documento=rule.name, acao='Execução com falha', link=f'{AUTOMACOES_LINK}?aba=historico',
               actor_id=resolve_responsavel(run), dedupe_key=f'regra-falha-{run.pk}')


# ----------------------------------------------------------------------------- execução de uma regra
def execute(rule_id, refs, dedupe_key, now=None):
    """Ponto de entrada da fila. Idempotente por (regra, dedupe_key)."""
    rule = Rule.objects.filter(pk=rule_id, enabled=True).select_related('organization').first()
    if rule is None or not rule.organization.is_active:
        return None
    org = rule.organization
    built = ctxmod.build(rule.trigger, org, refs)
    if built is None:
        return None
    ctx, title = built
    try:
        with transaction.atomic():
            run = RuleRun.objects.create(rule=rule, organization=org, trigger=rule.trigger, dedupe_key=str(dedupe_key)[:120],
                                         title=title[:300])
    except IntegrityError:
        return None                                                  # esse evento já rodou nesta regra
    since = (now or timezone.now()) - timedelta(days=1)
    if RuleRun.objects.filter(rule=rule, created_at__gte=since).exclude(status=S.SKIPPED).count() > DAILY_LIMIT:
        run.status, run.steps = S.FAILED, [{'tipo': 'limite', 'rotulo': 'Limite diário', 'status': 'bloqueado', 'externo': False,
                                             'detalhe': f'A regra passou de {DAILY_LIMIT} execuções em 24 h e foi pausada.', 'dados': {}}]
        run.save(update_fields=['status', 'steps'])
        Rule.objects.filter(pk=rule.pk).update(enabled=False)
        audit.log('automation.rule_disabled', actor_type='system', organization=org, target=rule, reason='limite diário de execuções')
        _notify_outcome(org, rule, run)
        return run
    if not matches(rule.conditions, ctx):
        run.status = S.SKIPPED
        run.save(update_fields=['status'])
        return run
    steps = []
    for i, step in enumerate(plan(org, rule, ctx)):
        if step['status'] == 'planejado':
            if step['externo'] and (rule.require_approval or step['tipo'] == 'erp_call'):
                step = {**step, 'status': 'aguardando'}
            else:
                step = perform(org, rule, run, step, i)
        steps.append(step)
    run.steps, run.status = steps, final_status(steps)
    run.save(update_fields=['steps', 'status'])
    Rule.objects.filter(pk=rule.pk).update(last_run_at=timezone.now(), run_count=F('run_count') + 1)
    _notify_outcome(org, rule, run)
    return run


class DecisionError(ValueError):
    pass


def _claim(run) -> bool:
    """Trava a execução pendente (dois cliques ao mesmo tempo não enviam duas vezes)."""
    return RuleRun.objects.filter(pk=run.pk, status=S.PENDING).update(status=S.RUNNING) == 1


def approve(run, user):
    if run.created_at < timezone.now() - timedelta(days=APPROVAL_TTL_DAYS):
        raise DecisionError('Esta aprovação expirou (mais de 7 dias). O evento não será enviado.')
    if not _claim(run):
        raise DecisionError('Esta execução não está mais aguardando aprovação.')
    run.refresh_from_db()
    run.decided_by, run.decided_at = user, timezone.now()
    org, rule = run.organization, run.rule
    steps = [perform(org, rule, run, s, i) if s['status'] == 'aguardando' else s for i, s in enumerate(run.steps)]
    run.steps, run.status = steps, final_status(steps)
    run.save(update_fields=['steps', 'status', 'decided_by', 'decided_at'])
    audit.log('automation.run_approved', actor=user, organization=org, target=rule,
              changes={'execucao': run.pk, 'status': run.status})
    return run


def reject(run, user, note=''):
    if not _claim(run):
        raise DecisionError('Esta execução não está mais aguardando aprovação.')
    run.refresh_from_db()
    run.steps = [{**s, 'status': 'recusado'} if s['status'] == 'aguardando' else s for s in run.steps]
    run.status, run.decided_by, run.decided_at, run.decision_note = S.REJECTED, user, timezone.now(), (note or '')[:255]
    run.save(update_fields=['steps', 'status', 'decided_by', 'decided_at', 'decision_note'])
    audit.log('automation.run_rejected', actor=user, organization=run.organization, target=run.rule,
              changes={'execucao': run.pk}, reason=(note or '')[:255])
    return run


# ----------------------------------------------------------------------------- simulação
def simulate(rule) -> dict:
    """Mostra o que a regra faria com o evento real mais recente (ou um exemplo). Sem efeito; libera a regra para ser ligada."""
    org = rule.organization
    refs = ctxmod.sample_refs(rule.trigger, org)
    built = ctxmod.build(rule.trigger, org, refs) if refs is not None else None
    origem = 'real'
    if built is None:
        built, origem = ctxmod.example(rule.trigger, org), 'exemplo'
    ctx, title = built
    ok = matches(rule.conditions, ctx)
    steps = plan(org, rule, ctx) if ok else []
    for s in steps:
        if s['status'] == 'planejado' and s['externo'] and (rule.require_approval or s['tipo'] == 'erp_call'):
            s['detalhe'] += ' Vai esperar aprovação de alguém da equipe.'
    rule.simulated_hash = rule.config_hash()
    rule.save(update_fields=['simulated_hash', 'updated_at'])
    return {'origem': origem, 'evento': title, 'condicoes_atendidas': ok,
            'condicoes': [{**c, 'atendida': condition_ok(c, ctx)} for c in rule.conditions], 'passos': steps,
            'variaveis': _flatten(ctx)}


def _flatten(ctx, prefix='') -> dict:
    out = {}
    for k, v in ctx.items():
        key = f'{prefix}{k}'
        if isinstance(v, dict):
            out.update(_flatten(v, key + '.'))
        elif k not in ('id', 'iso'):
            out[key] = v
    return out


# ----------------------------------------------------------------------------- eventos e agenda
def emit(organization, trigger, refs, dedupe_key) -> int:
    """Chamado pelos módulos (documentos, monitoramento, contatos). Nunca levanta: automação não pode quebrar o fluxo principal."""
    try:
        ids = list(Rule.objects.filter(organization=organization, trigger=trigger, enabled=True).values_list('pk', flat=True))
        if not ids:
            return 0

        def _go():
            from core.queue import enqueue
            for pk in ids:
                try:
                    enqueue('automations.engine.execute', pk, refs, dedupe_key)
                except Exception:  # noqa: BLE001
                    logger.exception('Não foi possível enfileirar a regra %s', pk)
        transaction.on_commit(_go)
        return len(ids)
    except Exception:  # noqa: BLE001
        logger.exception('Falha ao emitir evento de automação %s', trigger)
        return 0


def tick(now=None) -> dict:
    """A cada 15 min: prazos chegando, regras agendadas e aprovações vencidas."""
    from forense.calendar import Calendar
    from tasks.models import UserTask

    now = now or timezone.now()
    local = timezone.localtime(now)
    today = local.date()
    out = {'deadline': 0, 'schedule': 0, 'expired': 0, 'receivable': 0}
    rules = Rule.objects.filter(enabled=True, organization__is_active=True,
                                trigger__in=[Rule.Trigger.DEADLINE_SOON, Rule.Trigger.SCHEDULE, Rule.Trigger.RECEIVABLE_DUE]
                                ).select_related('organization')
    for rule in rules:
        org = rule.organization
        cal = Calendar(org)
        if rule.trigger == Rule.Trigger.DEADLINE_SOON:
            n = int(rule.trigger_config.get('dias_antes', 3))
            target = cal.add(today, n)
            tasks = (UserTask.objects.filter(responsavel__memberships__organization=org, responsavel__memberships__is_active=True,
                                             completed=False, titulo__istartswith='Prazo', scheduled_at__date=target).distinct())
            for t in tasks:
                if execute(rule.pk, {'task_id': t.pk, 'dias': n}, f'task-{t.pk}-d{n}', now=now):
                    out['deadline'] += 1
        elif rule.trigger == Rule.Trigger.RECEIVABLE_DUE:
            from carteira.models import Receivable
            cfg = rule.trigger_config
            when, n = cfg.get('quando', 'antes'), int(cfg.get('dias', 3))
            if local.hour < 8:                       # régua de cobrança só a partir das 8h
                continue
            target = today + timedelta(days=n) if when == 'antes' else today - timedelta(days=n)
            for rec in Receivable.objects.filter(organization=org, status=Receivable.Status.OPEN, due_date=target).only('pk'):
                if execute(rule.pk, {'receivable_id': rec.pk}, f'rec-{rec.pk}-{when}{n}', now=now):
                    out['receivable'] += 1
        else:
            cfg = rule.trigger_config
            if local.hour < int(cfg.get('hora', 8)):
                continue
            if cfg.get('frequencia') == 'semanal' and today.weekday() != int(cfg.get('dia_semana', 0)):
                continue
            if cfg.get('so_dias_uteis', True) and not cal.is_business_day(today):
                continue
            if execute(rule.pk, {'date': today.isoformat()}, f'agenda-{today.isoformat()}', now=now):
                out['schedule'] += 1
    expired = RuleRun.objects.filter(status=S.PENDING, created_at__lt=now - timedelta(days=APPROVAL_TTL_DAYS))
    for run in expired:
        run.steps = [{**s, 'status': 'expirado'} if s['status'] == 'aguardando' else s for s in run.steps]
        run.status = S.EXPIRED
        run.save(update_fields=['steps', 'status'])
        out['expired'] += 1
    return out
