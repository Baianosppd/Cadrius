"""Conformidade das automações e da gestão (CAD-223).

Uma "fotografia" que o dono/admin consulta em Automações → Conformidade e que a Gestão Cadrius vê em números (sem conteúdo):
- regras que falam com clientes sem aprovação humana, com texto que a checagem OAB/LGPD aponta, ou ligadas sem simulação válida;
- regras criadas por quem saiu da equipe;
- envios bloqueados por falta de consentimento nos últimos 30 dias (sinal de cadastro desatualizado);
- acessos: quem está sem grupo, grupos com financeiro e permissões extras.
Cada item diz o que fazer. Não muda nada sozinho.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from automations.catalog import EXTERNAL
from automations.models import Rule, RuleRun

LEVEL_ORDER = {'alto': 0, 'medio': 1, 'baixo': 2}


def _texts(rule):
    for a in rule.actions or []:
        if a.get('type') in ('send_message', 'send_whatsapp', 'send_email', 'send_survey'):
            p = a.get('params') or {}
            yield f"{p.get('assunto', '')}\n{p.get('mensagem', '')}"


def rule_findings(rule) -> list[dict]:
    from marketing import compliance
    out = []
    external = [a for a in rule.actions or [] if a.get('type') in EXTERNAL]
    to_client = [a for a in external if (a.get('params') or {}).get('destinatario') in ('cliente', 'contato')]
    if to_client and not rule.require_approval:
        out.append({'nivel': 'medio', 'regra': 'Mensagem ao cliente sem aprovação',
                    'o_que_fazer': 'Revise o texto com cuidado ou ligue "pedir aprovação" — a mensagem sai em nome do escritório.'})
    for text in _texts(rule):
        for alert in compliance.check(text, 'escritorio'):
            if alert['nivel'] in ('alto', 'medio'):
                out.append({'nivel': alert['nivel'], 'regra': f'Texto: {alert["regra"]}', 'o_que_fazer': alert['sugestao']})
    if rule.enabled:
        if rule.simulated_hash and rule.simulated_hash != rule.config_hash():
            out.append({'nivel': 'medio', 'regra': 'Ligada sem simular a versão atual',
                        'o_que_fazer': 'Simule de novo: a regra mudou depois da última simulação.'})
    if rule.created_by_id and not rule.created_by.memberships.filter(organization=rule.organization, is_active=True).exists():
        out.append({'nivel': 'baixo', 'regra': 'Criada por quem saiu da equipe',
                    'o_que_fazer': 'Confirme se a regra ainda faz sentido e quem responde por ela.'})
    return out


def report(org) -> dict:
    since = timezone.now() - timedelta(days=30)
    rules = []
    for rule in Rule.objects.filter(organization=org).select_related('created_by'):
        f = rule_findings(rule)
        if f:
            rules.append({'id': rule.pk, 'nome': rule.name, 'ligada': rule.enabled,
                          'achados': sorted(f, key=lambda x: LEVEL_ORDER[x['nivel']])})
    blocked = 0
    for run in RuleRun.objects.filter(rule__organization=org, created_at__gte=since).only('steps'):
        blocked += sum(1 for s in run.steps or [] if s.get('status') == 'bloqueado' and s.get('externo'))
    from accounts.models import OrganizationMembership
    members = OrganizationMembership.objects.filter(organization=org, is_active=True).select_related('access_group', 'user')
    no_group = [m.user.email for m in members if m.role in ('MEMBER', 'VIEWER') and not m.access_group_id]
    with_finance = sorted({m.access_group.name for m in members if m.access_group_id
                           and 'financeiro.ver' in (m.access_group.permissions or [])})
    extras = sorted({f'{m.access_group.name}: {p}' for m in members if m.access_group_id for p in (m.access_group.permissions or [])
                     if p in ('automacoes.gerir', 'marketing.aprovar', 'financeiro.cancelar', 'financeiro.nota')})
    items = [x for r in rules for x in r['achados']]
    score = max(0, 100 - 15 * sum(1 for x in items if x['nivel'] == 'alto') - 5 * sum(1 for x in items if x['nivel'] == 'medio')
                - (10 if blocked > 10 else 0))
    return {
        'nota': score,
        'regras': rules,
        'envios_bloqueados_30d': blocked,
        'dica_bloqueios': 'Envios bloqueados costumam ser contato sem consentimento registrado ou que pediu para não receber. '
                          'Atualize o consentimento no cadastro do contato (com a origem).' if blocked else '',
        'acessos': {'membros_sem_grupo': len(no_group), 'grupos_com_financeiro': with_finance, 'permissoes_extras': extras},
        'boas_praticas': [
            'Mensagens a clientes: tom informativo, sem promessa de resultado (Provimento OAB 205/2021).',
            'Só envie por canais que o cliente autorizou; o Cadrius confere de novo na hora do envio (LGPD).',
            'Envios fora do horário comercial esperam o próximo dia útil às 8h.',
            'Revise os grupos de acesso quando alguém muda de função ou sai do escritório.',
        ],
    }


def platform_overview() -> dict:
    """Para a Gestão Cadrius: só contagens, sem conteúdo dos escritórios."""
    rules = Rule.objects.filter(enabled=True)
    no_approval = sum(1 for r in rules.only('actions', 'require_approval') if not r.require_approval
                      and any((a.get('params') or {}).get('destinatario') in ('cliente', 'contato') for a in r.actions or []))
    return {'regras_ligadas': rules.count(), 'regras_cliente_sem_aprovacao': no_approval,
            'escritorios_com_regras': rules.values('organization').distinct().count()}
