"""Áreas da equipe Cadrius (CAD-168). Acesso = conta ativa + ``is_staff`` + (superusuário OU grupo da área).

Grupos: "Cadrius TI" (saúde do sistema, usuários, segurança, contas da equipe), "Cadrius Financeiro" (preços, promoções, créditos,
assinaturas) e "Cadrius Fiscal" (recebimentos e notas fiscais, CAD-170).
Atribuir: ``manage.py cadrius_staff email@... --areas ti,financeiro``.

CAD-223: cada área tem dois níveis — "total" (grupo da área) e "consulta" (grupo "<área> (consulta)": só leitura; qualquer
POST/PATCH/DELETE recebe 403). Nova área "juridico" (calendário forense: suspensões de prazo e dados dos tribunais).
O catálogo ``AREA_CATALOG`` descreve o que cada área concede (tela "Equipe Cadrius" e docs/ACESSOS_E_GRUPOS.md).
"""
from rest_framework import permissions

from accounts import mfa

AREA_GROUPS = {'ti': 'Cadrius TI', 'financeiro': 'Cadrius Financeiro', 'fiscal': 'Cadrius Fiscal', 'suporte': 'Cadrius Suporte',
               'marketing': 'Cadrius Marketing', 'juridico': 'Cadrius Jurídico'}
READ_SUFFIX = ' (consulta)'
READ_GROUPS = {a: g + READ_SUFFIX for a, g in AREA_GROUPS.items()}

AREA_CATALOG = {
    'ti': {'label': 'TI', 'total': 'Saúde do sistema, Cibersegurança (bloqueio de IP, alertas), contas de usuários (senha temporária, '
                                     'bloqueio), equipe Cadrius (criar contas e definir áreas) e chave geral da IA.',
           'consulta': 'Ver painéis de saúde, Cibersegurança, usuários e equipe, sem executar ações.'},
    'financeiro': {'label': 'Financeiro', 'total': 'Planos e preços, promoções, créditos, assinaturas dos escritórios e indicadores '
                                                   '(receita recorrente, cancelamentos, inadimplência).',
                   'consulta': 'Ver planos, assinaturas e indicadores sem alterar preços, promoções ou créditos.'},
    'fiscal': {'label': 'Fiscal', 'total': 'Recebimentos da Cadrius, emissão/cancelamento de NFS-e, obrigações do mês e pacote do contador.',
               'consulta': 'Ver recebimentos, notas e obrigações; baixar o pacote do contador.'},
    'suporte': {'label': 'Suporte', 'total': 'Fila de chamados e pedidos de parametrização: responder, mudar status, orçar e entregar. '
                                             'Dados do escritório só com acesso assistido concedido pelo cliente.',
                'consulta': 'Ler a fila de chamados e parametrizações sem responder.'},
    'marketing': {'label': 'Marketing', 'total': 'Conteúdo e campanhas da Cadrius, crescimento (cadastros, conversão) e checagem OAB.',
                  'consulta': 'Ver conteúdos, campanhas e indicadores de crescimento.'},
    'juridico': {'label': 'Jurídico', 'total': 'Calendário forense nacional: suspensões de prazo e indisponibilidades por tribunal '
                                               '(avisam os escritórios e entram na contagem de prazos) e dados dos tribunais '
                                               '(Balcão Virtual, links de serviços).',
                 'consulta': 'Ver o calendário forense e os dados dos tribunais.'},
}


def user_area_levels(user) -> dict[str, str]:
    """{'ti': 'total', 'fiscal': 'consulta', ...} — só áreas com algum acesso."""
    if not (user and user.is_authenticated and user.is_active and user.is_staff):
        return {}
    if user.is_superuser:
        return {a: 'total' for a in AREA_GROUPS}
    names = set(user.groups.values_list('name', flat=True))
    out = {}
    for a in AREA_GROUPS:
        if AREA_GROUPS[a] in names:
            out[a] = 'total'
        elif READ_GROUPS[a] in names:
            out[a] = 'consulta'
    return out


def user_areas(user) -> list[str]:
    return sorted(user_area_levels(user))


class HasArea(permissions.BasePermission):
    """Use ``HasArea.of('ti')``. Sem área → 403 (e o middleware de auditoria registra o acesso negado)."""

    @classmethod
    def of(cls, *areas):
        return type(f'HasArea_{"_".join(areas)}', (cls,), {'areas': areas})

    areas: tuple = ()

    def has_permission(self, request, view):
        levels = user_area_levels(request.user)
        relevant = [levels[a] for a in (self.areas or levels) if a in levels]
        allowed = bool(relevant)
        if allowed and not mfa.staff_session_ok(request):
            self.message = mfa.MFA_DENIED          # 403 com code=mfa_required: o front abre o cadastro do MFA
            return False
        if allowed and request.method not in permissions.SAFE_METHODS and 'total' not in relevant:
            self.message = 'Seu acesso a esta área da Gestão é só de consulta.'
            return False
        return allowed


IsBackoffice = HasArea.of()            # qualquer área
IsTI = HasArea.of('ti')
IsFinanceiro = HasArea.of('financeiro')
IsFiscal = HasArea.of('fiscal')
IsJuridico = HasArea.of('juridico')
