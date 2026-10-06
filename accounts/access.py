"""Grupos de acesso do escritório (CAD-223).

O dono/administrador cria grupos (ex.: "Financeiro", "Estagiários") marcando o que cada um pode ver e alterar, e coloca cada
pessoa da equipe num grupo. Regras:

- Dono e administrador têm sempre acesso total (são quem configura os grupos).
- Membro **sem grupo** segue o comportamento do cargo (como antes do CAD-223: tudo menos financeiro e configurações).
- Membro **com grupo** só acessa os módulos marcados ("ver" = consultar; "editar" = criar/alterar/apagar).
- Perfil "Somente leitura" nunca altera nada, mesmo que o grupo marque "editar".
- Permissões extras (aprovar, publicar, emitir nota) liberam ações que antes eram só do dono/admin.

O catálogo abaixo é a fonte única: alimenta a API, a tela "Grupos de acesso" (com o texto "o que concede") e
docs/ACESSOS_E_GRUPOS.md.
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

MANAGER_ROLES = {'OWNER', 'ADMIN'}

# chave → rótulo, o que cada nível concede e quais rotas da API pertencem ao módulo
MODULES = {
    'contatos': {
        'label': 'Contatos', 'grupo': 'Dia a dia',
        'ver': 'Consultar o quadro de contatos (clientes, partes, parceiros), histórico e consentimentos.',
        'editar': 'Cadastrar, editar e arquivar contatos; registrar consentimento de WhatsApp/e-mail.',
        'rotas': ['/api/v1/contacts/'],
    },
    'processos': {
        'label': 'Processos e publicações', 'grupo': 'Dia a dia',
        'ver': 'Ver processos acompanhados, andamentos, publicações do DJEN, calendário forense e cálculo de prazos.',
        'editar': 'Cadastrar processos para acompanhar, revisar/confirmar publicações, cadastrar OABs e feriados locais.',
        'rotas': ['/api/v1/research/', '/api/v1/publications/', '/api/v1/forense/'],
    },
    'documentos': {
        'label': 'Documentos', 'grupo': 'Dia a dia',
        'ver': 'Abrir documentos do escritório e a leitura feita pela IA.',
        'editar': 'Enviar documentos, confirmar ou refazer a leitura da IA e apagar documentos.',
        'rotas': ['/api/v1/documentos/', '/api/v1/extraction-profiles/'],
    },
    'tarefas': {
        'label': 'Tarefas e agenda', 'grupo': 'Dia a dia',
        'ver': 'Ver tarefas, prazos da agenda e compromissos trazidos do Google Agenda.',
        'editar': 'Criar, concluir e reatribuir tarefas; ajustar compromissos do Google Agenda.',
        'rotas': ['/api/v1/tasks/', '/api/v1/integrations/google-calendar/'],
    },
    'emails': {
        'label': 'E-mails', 'grupo': 'Dia a dia',
        'ver': 'Ler as caixas de e-mail conectadas e a triagem automática.',
        'editar': 'Conectar/desconectar caixas de e-mail.',
        'rotas': ['/api/v1/mailboxes/', '/api/v1/emails/'],
    },
    'minutas': {
        'label': 'Minutas e modelos', 'grupo': 'Produção',
        'ver': 'Abrir minutas e modelos de peças/contratos e baixar em Word.',
        'editar': 'Criar e editar minutas e modelos do escritório.',
        'rotas': ['/api/v1/minutas/'],
    },
    'funil': {
        'label': 'Funil de clientes (oportunidades)', 'grupo': 'Carteira',
        'ver': 'Ver oportunidades, etapas do funil e a ficha do cliente (sem valores financeiros).',
        'editar': 'Criar oportunidades e mover etapas do funil.',
        'rotas': ['/api/v1/carteira/oportunidades/', '/api/v1/carteira/clientes/'],
    },
    'financeiro': {
        'label': 'Financeiro do escritório', 'grupo': 'Carteira',
        'ver': 'Ver honorários, parcelas, despesas, painel, fluxo de caixa, DRE e o fiscal do escritório.',
        'editar': 'Criar contratos de honorários, dar baixa em parcelas, lançar despesas (avulsas e recorrentes) e meta do mês.',
        'rotas': ['/api/v1/carteira/contratos/', '/api/v1/carteira/lancamentos/', '/api/v1/carteira/despesas/',
                  '/api/v1/carteira/painel/', '/api/v1/carteira/asaas/webhook-config/', '/api/v1/carteira/financeiro/'],
    },
    'marketing': {
        'label': 'Marketing', 'grupo': 'Produção',
        'ver': 'Ver ideias, calendário de conteúdo, campanhas, formulários de captação e resultados por canal.',
        'editar': 'Escrever conteúdos, criar campanhas e formulários de captação (a publicação depende de aprovação).',
        'rotas': ['/api/v1/marketing/'],
    },
    'automacoes': {
        'label': 'Automações', 'grupo': 'Escritório',
        'ver': 'Ver regras, fluxos, histórico e a conformidade das automações.',
        'editar': 'Criar e editar fluxos com apps e aprovar envios pendentes (as regras do escritório pedem a permissão extra).',
        'rotas': ['/api/v1/automations/', '/api/workflows/', '/api/v1/workflows/', '/api/v1/brain/'],
    },
    'integracoes': {
        'label': 'Integrações', 'grupo': 'Escritório',
        'ver': 'Ver os apps conectados e o catálogo de integrações.',
        'editar': 'Conectar, testar e remover apps (WhatsApp, Asaas, assinatura, ERP...).',
        'rotas': ['/api/v1/integrations/', '/api/v1/erp/', '/api/v1/connections/'],
    },
    'ia': {
        'label': 'Assistente IA', 'grupo': 'Escritório',
        'ver': 'Conversar com o Assistente IA (as ferramentas respeitam os demais acessos da pessoa).',
        'editar': 'Pedir ações ao assistente (tarefa, minuta, contato...) e usar o conector Claude/ChatGPT.',
        'rotas': ['/api/v1/assistant/'],
    },
    'portal': {
        'label': 'Portal do cliente', 'grupo': 'Carteira',
        'ver': 'Ver os links de portal enviados aos clientes.',
        'editar': 'Gerar e revogar links do portal do cliente.',
        'rotas': ['/api/v1/portal/links/'],
    },
    'importacao': {
        'label': 'Importar dados', 'grupo': 'Escritório',
        'ver': 'Ver importações feitas.',
        'editar': 'Importar planilhas de contatos/processos para o Cadrius.',
        'rotas': ['/api/v1/imports/'],
    },
}

# Ações que antes eram só do dono/administrador e o grupo pode liberar.
EXTRAS = {
    'automacoes.gerir': {'label': 'Criar, ligar e desligar regras do escritório', 'modulo': 'automacoes',
                         'concede': 'Criar/editar regras de automação, simular e ligar. Toda regra continua nascendo desligada.'},
    'marketing.aprovar': {'label': 'Aprovar e publicar conteúdo', 'modulo': 'marketing',
                          'concede': 'Aprovar textos (com a checagem OAB) e publicar nas redes conectadas.'},
    'financeiro.cancelar': {'label': 'Cancelar contratos e parcelas', 'modulo': 'financeiro',
                            'concede': 'Cancelar contratos de honorários e parcelas (ação auditada).'},
    'financeiro.nota': {'label': 'Emitir nota fiscal de serviço', 'modulo': 'financeiro',
                        'concede': 'Pedir a emissão da NFS-e de honorários pelo app emissor conectado.'},
}

PRESETS = {
    'advogado': {'nome': 'Advogado(a)', 'descricao': 'Dia a dia jurídico completo, sem financeiro.',
                 'permissoes': [f'{m}.{n}' for m in ('contatos', 'processos', 'documentos', 'tarefas', 'emails', 'minutas', 'funil', 'ia')
                                for n in ('ver', 'editar')] + ['automacoes.ver', 'portal.ver', 'portal.editar', 'marketing.ver']},
    'estagiario': {'nome': 'Estagiário(a)', 'descricao': 'Consulta e prepara; não apaga contatos nem mexe no funil.',
                   'permissoes': ['contatos.ver', 'processos.ver', 'documentos.ver', 'documentos.editar', 'tarefas.ver', 'tarefas.editar',
                                  'minutas.ver', 'minutas.editar', 'ia.ver']},
    'financeiro': {'nome': 'Financeiro', 'descricao': 'Honorários, cobranças, despesas e fiscal do escritório.',
                   'permissoes': ['contatos.ver', 'funil.ver', 'financeiro.ver', 'financeiro.editar', 'financeiro.nota', 'portal.ver',
                                  'tarefas.ver', 'tarefas.editar', 'ia.ver']},
    'atendimento': {'nome': 'Secretaria / atendimento', 'descricao': 'Recebe clientes, agenda e organiza documentos.',
                    'permissoes': ['contatos.ver', 'contatos.editar', 'tarefas.ver', 'tarefas.editar', 'documentos.ver', 'documentos.editar',
                                   'funil.ver', 'funil.editar', 'emails.ver', 'portal.ver', 'portal.editar', 'ia.ver']},
    'marketing': {'nome': 'Marketing', 'descricao': 'Conteúdo, campanhas e captação, com a checagem OAB.',
                  'permissoes': ['marketing.ver', 'marketing.editar', 'funil.ver', 'contatos.ver', 'ia.ver']},
    'leitura': {'nome': 'Somente consulta', 'descricao': 'Vê o dia a dia sem alterar nada.',
                'permissoes': [f'{m}.ver' for m in ('contatos', 'processos', 'documentos', 'tarefas', 'minutas', 'funil')]},
}

ALL = sorted([f'{m}.{n}' for m in MODULES for n in ('ver', 'editar')] + list(EXTRAS))


class ModuleForbidden(PermissionDenied):
    default_detail = 'Seu grupo de acesso não libera esta área. Fale com o responsável pelo escritório.'
    default_code = 'module_forbidden'


def clean(perms) -> list[str]:
    """Normaliza: só chaves conhecidas; "editar" implica "ver"; extra implica ver/editar do módulo."""
    out = {p for p in (perms or []) if p in ALL}
    for p in list(out):
        mod, level = p.split('.', 1)
        if level != 'ver':
            out.add(f'{mod}.ver')
        if p in EXTRAS:
            out.add(f'{EXTRAS[p]["modulo"]}.editar')
    return sorted(out)


def effective(membership) -> set[str] | None:
    """Permissões efetivas; None = sem restrição por grupo (dono/admin ou membro sem grupo → regras do cargo)."""
    if membership is None or membership.role in MANAGER_ROLES or not membership.access_group_id:
        return None
    perms = set(membership.access_group.permissions or [])
    if membership.role == 'VIEWER':
        perms = {p for p in perms if p.endswith('.ver')}
    return perms


def allowed(membership, perm: str, legacy_roles=None) -> bool:
    """A pessoa pode ``perm``? Sem grupo vale o cargo (``legacy_roles``; None = qualquer cargo)."""
    if membership is None:
        return False
    if membership.role in MANAGER_ROLES:
        return True
    perms = effective(membership)
    if perms is None:
        return legacy_roles is None or membership.role in legacy_roles
    return perm in perms


def module_for(path: str) -> str | None:
    best, size = None, 0
    for key, spec in MODULES.items():
        for prefix in spec['rotas']:
            if path.startswith(prefix) and len(prefix) > size:
                best, size = key, len(prefix)
    return best


def check_request(membership, path: str, method: str) -> None:
    """Chamado na autenticação: bloqueia o módulo que o grupo não libera (403 module_forbidden)."""
    perms = effective(membership)
    if perms is None:
        return
    mod = module_for(path)
    if mod is None:
        return
    need = f'{mod}.ver' if method in ('GET', 'HEAD', 'OPTIONS') else f'{mod}.editar'
    if need not in perms:
        raise ModuleForbidden()


def summary(membership) -> dict | None:
    """O que o front usa para montar menu e botões (None = sem restrição de grupo)."""
    perms = effective(membership)
    if perms is None:
        return None
    return {'grupo': membership.access_group.name, 'permissoes': sorted(perms)}


def catalog() -> dict:
    return {
        'modulos': [{'chave': k, 'rotulo': v['label'], 'grupo': v['grupo'], 'ver': v['ver'], 'editar': v['editar']} for k, v in MODULES.items()],
        'extras': [{'chave': k, 'rotulo': v['label'], 'modulo': v['modulo'], 'concede': v['concede']} for k, v in EXTRAS.items()],
        'modelos': [{'chave': k, **v, 'permissoes': clean(v['permissoes'])} for k, v in PRESETS.items()],
        'regras': [
            'Dono e administrador sempre têm acesso total e são quem configura os grupos.',
            'Quem não está em nenhum grupo segue o cargo: membro faz o dia a dia (sem financeiro e sem configurações); '
            '"somente leitura" só consulta.',
            'Quem está num grupo só acessa os módulos marcados; "editar" já inclui "ver".',
            'O perfil "somente leitura" nunca altera nada, mesmo num grupo com "editar".',
            'O Assistente IA e o conector Claude/ChatGPT respeitam o grupo: só mostram o que a pessoa pode ver.',
            'Toda mudança de grupo fica na trilha de auditoria.',
        ],
    }
