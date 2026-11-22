"""Gera os diagramas do banco de dados a partir dos modelos do Django.

    python docs/diagramas/gerador/banco.py

Escreve docs/diagramas/fontes/D00-mapa-dominios.dot, um D01..D15.dot por área (Graphviz, pé de galinha) e gerador/banco.json (textos das pranchas).
Regras do padrão (PADRAO_VISUAL.md):
- no máximo 8 tabelas por diagrama; cada tabela entra em exatamente uma área (o script recusa se não);
- por tabela: chave primária, chaves estrangeiras e até 3 campos de negócio, sem passar de 5 linhas (mínimo 1 campo);
- organization_id e as colunas de autoria (created_by, user...) apontam para Contas e acesso (D01) e só aparecem lá;
- chave estrangeira para outra área vira atributo com o destino no comentário, sem linha cruzando diagramas.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
DIAG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cadrius.settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'gerador-de-diagramas')

import django  # noqa: E402

django.setup()
from django.apps import apps  # noqa: E402

MAX_TABELAS = 8
MAX_CAMPOS = 3
MAX_LINHAS = 5      # PK + FKs + campos: os campos de negócio só entram até completar 5 linhas (mínimo 1)
NUCLEO = {'accounts.Organization', 'accounts.CustomUser'}
IGNORAR = {'created_at', 'updated_at', 'modified_at', 'id'}

AREAS = [
    ('D01', 'Escritórios e vínculos', 'Escritórios, usuários, vínculos e grupos de acesso. Toda tabela das outras áreas '
     'aponta para Organization (o escritório) e, quando registra autoria, para CustomUser.',
     ['accounts.Organization', 'accounts.CustomUser', 'accounts.OrganizationMembership', 'accounts.AccessGroup']),
    ('D01b', 'Login e segurança da conta', 'Segundo fator (MFA) e códigos de recuperação, identidades de login social '
     '(Google, Microsoft) e contadores de envio por usuário.',
     ['accounts.MFADevice', 'accounts.MFARecoveryCode', 'accounts.SocialIdentity', 'accounts.UserMessageSendCount']),
    ('D02', 'Assinatura, pagamentos e fiscal da Cadrius', 'Planos, histórico de preço, pagamentos do Stripe, cupons, '
     'adicional de mídia e obrigações fiscais da própria Cadrius.',
     ['billing.SubscriptionPlan', 'billing.PlanPriceHistory', 'billing.Payment', 'billing.Promotion',
      'billing.PromotionRedemption', 'billing.MediaAddon', 'billing.FiscalObligation', 'billing.FiscalObligationDone']),
    ('D03', 'Créditos e IA governada', 'Pacotes e lotes de créditos, peso de cada operação, consumo por membro e as '
     'políticas que decidem qual provedor de IA o escritório pode usar.',
     ['billing.CreditPack', 'billing.CreditLot', 'billing.CreditWeight', 'billing.AIUsageLog',
      'billing.MemberCreditUsage', 'aigov.AIGovernancePolicy', 'aigov.AIRoute', 'aigov.GlobalAISwitch']),
    ('D04', 'Clientes e documentos', 'Contatos do escritório, documentos cifrados, leitura com IA, portal do cliente '
     'e importações (planilhas e pastas).',
     ['contacts.Contact', 'documents.Document', 'documents.ClientDocument', 'documents.DocumentExtraction',
      'extraction.ExtractionProfile', 'portal.PortalLink', 'imports.ImportJob', 'imports.FolderImport']),
    ('D05', 'Processos, publicações e prazos', 'Processos monitorados e andamentos, OABs acompanhadas no DJEN, '
     'publicações, feriados e suspensões dos tribunais.',
     ['research.MonitoredCase', 'research.CaseMovement', 'research.NewsItem', 'publications.OabWatch',
      'publications.Publication', 'forense.Holiday', 'forense.CourtSuspension', 'forense.CourtInfo']),
    ('D06', 'Tarefas, minutas e Google Agenda', 'Tarefas e prazos, modelos e minutas, e a ligação com o Google '
     '(agenda, eventos trazidos e arquivos criados no Drive).',
     ['tasks.UserTask', 'minutas.DraftTemplate', 'minutas.Draft', 'gcal.GoogleCalendarApp',
      'gcal.GoogleCalendarLink', 'gcal.TaskEventMap', 'gcal.ExternalEvent', 'gcal.GoogleFile']),
    ('D07', 'Carteira e honorários', 'Oportunidades, contratos de honorários, contas a receber e despesas ligadas a '
     'clientes e processos.',
     ['carteira.Opportunity', 'carteira.FeeAgreement', 'carteira.Receivable', 'carteira.Expense']),
    ('D07', 'Financeiro do escritório', 'Despesas fixas, metas e regime fiscal do escritório e eventos recebidos do '
     'Asaas (cobrança).',
     ['carteira.RecurringExpense', 'carteira.FinanceSettings', 'carteira.AsaasEvent']),
    ('D08', 'Marketing', 'Campanhas, conteúdos, imagens, formulários de captação e pesquisas de satisfação.',
     ['marketing.Campaign', 'marketing.ContentPiece', 'marketing.MarketingAsset', 'marketing.CaptureForm',
      'marketing.SatisfactionSurvey']),
    ('D09', 'Regras de automação', 'Regras (gatilho, condições e passos), cada execução com seu resultado e os '
     'aparelhos pessoais que aprovam pelo relógio ou celular.',
     ['automations.Rule', 'automations.RuleRun', 'automations.PersonalDevice']),
    ('D09', 'Fluxos com aplicativos', 'Fluxos visuais com gatilhos de aplicativos externos e webhooks, ações e '
     'registro de execução.',
     ['workflows.Workflow', 'workflows.Trigger', 'workflows.Action', 'workflows.ExecutionLog', 'webhooks.WebhookTrigger']),
    ('D10', 'Conversas do Assistente', 'Conversas, mensagens, ações que aguardam a confirmação da pessoa e o registro '
     'de tudo o que a IA fez.',
     ['assistant.Conversation', 'assistant.Message', 'assistant.PendingAction', 'aigov.AIActionLog']),
    ('D10', 'Configuração do Assistente', 'Preferências do Assistente por escritório, chaves próprias de IA (BYOK) e '
     'tokens pessoais para conectar o Cadrius a outras IAs (MCP).',
     ['assistant.AssistantSettings', 'assistant.OrgAIKey', 'assistant.PersonalToken']),
    ('D11', 'Aprendizado da IA', 'Memória e regras do escritório, feedback, nível de autonomia e sugestões de '
     'automação.',
     ['brain.OfficeProfile', 'brain.MemoryItem', 'brain.OfficeRule', 'brain.AIFeedback', 'brain.AutonomyLevel',
      'brain.AutonomyProposal', 'brain.AutomationSuggestion']),
    ('D12', 'E-mails e avisos', 'Caixas de e-mail, mensagens recebidas e triagem, notificações do sistema e avisos '
     'de cobrança.',
     ['emails.MailBox', 'emails.EmailMessage', 'emails.EmailTriage', 'notifications.Notification',
      'billing.BillingNotice', 'tasks.IntegrationConfig', 'tasks.IntegrationLog']),
    ('D13', 'Conectores e suporte', 'Conexões com aplicativos e ERP com seus registros de chamada, e os chamados de '
     'suporte com acesso temporário.',
     ['integrations.AppConnection', 'integrations.IntegrationLog', 'erp.ErpConnector', 'erp.ErpCallLog',
      'support.Ticket', 'support.TicketMessage', 'support.SupportAccessGrant', 'support.CustomizationRequest']),
    ('D14', 'Auditoria e segurança', 'Trilha de auditoria encadeada por hash, pontos de verificação, alertas de '
     'anomalia, IPs bloqueados e avaliação de controles.',
     ['audit.AuditEvent', 'audit.AuditChainHead', 'audit.AuditCheckpoint', 'audit.AnomalyAlert', 'audit.BlockedIP',
      'compliance.ControlAssessment', 'compliance.ComplianceSnapshot']),
    ('D15', 'Privacidade (LGPD)', 'Documentos legais versionados, aceites, suboperadores, pedidos dos titulares e '
     'desligamento de escritórios.',
     ['privacy.LegalDocument', 'privacy.ConsentRecord', 'privacy.SubprocessorEntry', 'privacy.DataSubjectRequest',
      'privacy.OrganizationOffboarding']),
    ('D20', 'Filas e agendamentos (Django-Q)', 'Tabelas da biblioteca Django-Q, que roda as rotinas da S03. Schedule '
     'guarda o que repete e quando; cada disparo vira uma Task com o resultado (Schedule.task aponta para a última, '
     'Task.name repete o nome do agendamento; não há chave estrangeira). OrmQ fica vazia: a fila do Cadrius é o Redis.',
     ['django_q.Schedule', 'django_q.Task', 'django_q.OrmQ']),
]

# Tabelas de bibliotecas: os campos de negócio mostrados são escolhidos à mão (os primeiros seriam técnicos).
BIBLIOTECAS = ('django_q.',)   # áreas só de bibliotecas: sem ligação com o resto, ficam fora do mapa D00
CAMPOS = {
    'django_q.Schedule': ['func', 'next_run', 'task'],
    'django_q.Task': ['name', 'func', 'success'],
    'django_q.OrmQ': ['key', 'lock'],
}

TIPOS = {
    'AutoField': 'int', 'BigAutoField': 'int', 'IntegerField': 'int', 'PositiveIntegerField': 'int',
    'PositiveSmallIntegerField': 'int', 'SmallIntegerField': 'int', 'BigIntegerField': 'int',
    'PositiveBigIntegerField': 'int', 'SmallAutoField': 'int',
    'UUIDField': 'uuid', 'CharField': 'texto', 'TextField': 'texto', 'SlugField': 'texto', 'URLField': 'url',
    'EmailField': 'email', 'BooleanField': 'bool', 'DateField': 'data', 'DateTimeField': 'datahora',
    'DecimalField': 'decimal', 'FloatField': 'decimal', 'JSONField': 'json', 'FileField': 'arquivo',
    'ImageField': 'imagem', 'GenericIPAddressField': 'ip', 'DurationField': 'duracao', 'BinaryField': 'binario',
}


AREAS = [(f'D{i:02d}', nome, texto, membros) for i, (_, nome, texto, membros) in enumerate(AREAS, start=1)]


def label(m):
    return f'{m._meta.app_label}.{m.__name__}'


def entidade(m, duplicados):
    return f'{m._meta.app_label.capitalize()}{m.__name__}' if m.__name__ in duplicados else m.__name__


def tipo(f):
    cls = type(f).__name__
    if 'Encrypted' in cls:
        return 'cifrado'
    return TIPOS.get(f.get_internal_type(), 'texto')


def main():
    modelos = {label(m): m for m in apps.get_models() if label(m) in {x for a in AREAS for x in a[3]}}
    todos = [x for a in AREAS for x in a[3]]
    repetidos = [x for x, n in Counter(todos).items() if n > 1]
    faltando = sorted(set(todos) - set(modelos))
    projeto = {label(m) for m in apps.get_models()
               if m.__module__.split('.')[0] in {p.name for p in RAIZ.iterdir() if p.is_dir()}}
    sem_area = sorted(projeto - set(todos))
    grandes = [a[0] for a in AREAS if len(a[3]) > MAX_TABELAS]
    if repetidos or faltando or sem_area or grandes:
        sys.exit(f'Áreas inválidas: repetidos={repetidos} faltando={faltando} sem_area={sem_area} >8={grandes}')

    area_de = {x: a[0] for a in AREAS for x in a[3]}
    nomes = Counter(m.__name__ for m in modelos.values())
    dup = {n for n, c in nomes.items() if c > 1}
    catalogo, cruzam = [], Counter()

    for codigo, nome, texto, membros in AREAS:
        tabelas, rel, externos = [], [], set()
        for lab in membros:
            m = modelos[lab]
            linhas, campos = [], 0
            for f in m._meta.fields:
                if f.is_relation and f.related_model:
                    alvo = label(f.related_model)
                    if alvo in NUCLEO and area_de.get(label(m)) != area_de[alvo]:
                        continue
                    if area_de.get(alvo) == codigo:
                        rel.append((entidade(f.related_model, dup), f.target_field.column, entidade(m, dup), f.column,
                                    f.one_to_one, f.null))
                        linhas.append((f.column, 'FK', ''))
                    else:
                        destino = area_de.get(alvo)
                        linhas.append((f.column, 'FK', f'{f.related_model.__name__} ({destino})' if destino else ''))
                        if destino:
                            cruzam[(codigo, destino)] += 1
                            externos.add(destino)
                    continue
                if f.primary_key:
                    linhas.insert(0, (f.column, 'PK', tipo(f)))
                    continue
                if lab in CAMPOS and f.name not in CAMPOS[lab]:
                    continue
                if f.name in IGNORAR or f.column.endswith(('_bidx', '_idx', '_sha256', '_hash')) or campos >= MAX_CAMPOS:
                    continue
                linhas.append((f.column, 'UK' if f.unique else '', tipo(f)))
                campos += 1
            chaves = [x for x in linhas if x[1] in ('PK', 'FK')]
            negocio = [x for x in linhas if x[1] not in ('PK', 'FK')]
            linhas = chaves + negocio[:max(1, MAX_LINHAS - len(chaves))]
            tabelas.append((entidade(m, dup), linhas))
        (DIAG / 'fontes' / f'{codigo}-{slug(nome)}.dot').write_text(dot_area(codigo, tabelas, rel))
        liga = ', '.join(sorted(externos))
        catalogo.append({
            'id': codigo, 'arquivo': f'{codigo}-{slug(nome)}', 'titulo': f'Banco de dados: {nome}',
            'tipo': 'dados', 'nivel': 'Modelo de dados · Entidade-relacionamento',
            'descricao': texto + (f' Liga-se a {liga}.' if liga else ''),
            'tabelas': len(membros),
        })

    (DIAG / 'fontes' / 'D00-mapa-dominios.dot').write_text(dot_mapa(cruzam))
    proprias = [a for a in AREAS if not all(x.startswith(BIBLIOTECAS) for x in a[3])]
    total = sum(len(a[3]) for a in proprias)
    catalogo.insert(0, {
        'id': 'D00', 'arquivo': 'D00-mapa-dominios', 'titulo': 'Banco de dados: mapa das áreas',
        'tipo': 'mapa', 'nivel': 'Modelo de dados · Visão geral',
        'descricao': f'{total} tabelas do Cadrius em {len(proprias)} áreas de até {MAX_TABELAS} tabelas. As setas mostram '
                     'as chaves estrangeiras entre áreas; as que todas têm para D01 (escritório e autoria) ficam de fora. '
                     'As tabelas da biblioteca de filas estão à parte, em D20.',
    })
    (DIAG / 'gerador' / 'banco.json').write_text(json.dumps(catalogo, ensure_ascii=False, indent=2) + '\n')
    print(f'{total} tabelas próprias em {len(proprias)} áreas, {len(AREAS)} pranchas de área, {len(cruzam)} ligações entre áreas')


# --------------------------------------------------------------------------- Graphviz (pé de galinha)
CABECALHO = """digraph G {
  graph [rankdir=LR, pack=true, packmode="array_u", nodesep=0.3, ranksep=0.6, bgcolor="transparent",
         fontname="Inter", pad=0.1, splines=spline]
  node [shape=plain, fontname="Inter", fontsize=15]
  edge [color="#475569", penwidth=1.4, arrowsize=1.0, dir=both]
"""
COR_PK, COR_FK, COR_UK = '#0B3D6E', '#2E6DB4', '#2F855A'


def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def dot_tabela(nome, linhas):
    corpo = [f'<tr><td colspan="3" bgcolor="#1F5FAD" align="left" cellpadding="7">'
             f'<font color="#FFFFFF" point-size="16"><b>{esc(nome)}</b></font></td></tr>']
    for i, (coluna, chave, info) in enumerate(linhas):
        fundo = '#FFFFFF' if i % 2 else '#F1F5F9'
        cor = {'PK': COR_PK, 'FK': COR_FK, 'UK': COR_UK}.get(chave, '#1E293B')
        texto = f'<b>{esc(coluna)}</b>' if chave == 'PK' else esc(coluna)
        marca = f'<font color="{cor}"><b>{chave}</b></font>' if chave else ' '
        nota = f'<font color="#475569">{esc(info)}</font>' if info else ' '
        # porta de chegada (FK) na primeira célula e de saída (PK) na última: as setas encostam na borda da tabela
        corpo.append(f'<tr><td port="{esc(coluna)}" align="left" bgcolor="{fundo}">{texto}</td>'
                     f'<td align="left" bgcolor="{fundo}">{marca}</td>'
                     f'<td port="{esc(coluna)}_saida" align="left" bgcolor="{fundo}">{nota}</td></tr>')
    tabela = ('<table border="1" cellborder="0" cellspacing="0" cellpadding="4" color="#2E6DB4">'
              + ''.join(corpo) + '</table>')
    return f'  "{nome}" [label=<{tabela}>]\n'


def dot_area(codigo, tabelas, rel):
    saida = CABECALHO + ''.join(dot_tabela(n, l) for n, l in tabelas)
    for pai, chave_pai, filho, coluna, um_para_um, opcional in rel:
        lado_pai = 'teeodot' if opcional else 'teetee'
        lado_filho = 'teeodot' if um_para_um else 'crowodot'
        saida += f'  "{pai}":"{chave_pai}_saida":e -> "{filho}":"{coluna}":w [arrowtail={lado_pai}, arrowhead={lado_filho}]\n'
    return saida + '}\n'


def dot_mapa(cruzam):
    saida = CABECALHO.replace('shape=plain', 'shape=box, style="filled", margin="0.25,0.12"')
    saida = saida.replace('edge [color="#475569", penwidth=1.4, arrowsize=1.0, dir=both]',
                          'edge [color="#475569", penwidth=1.4, arrowsize=0.9, fontname="Inter", fontsize=15]')
    for codigo, nome, _, membros in AREAS:
        if all(x.startswith(BIBLIOTECAS) for x in membros):
            continue
        cor, texto, borda = ('#1F5FAD', '#FFFFFF', '#123F78') if codigo == 'D01' else ('#D6E6F7', '#0B2545', '#2E6DB4')
        saida += (f'  {codigo} [label=<<b>{codigo} {esc(nome)}</b><br/>{len(membros)} tabelas>, fillcolor="{cor}", '
                  f'fontcolor="{texto}", color="{borda}"]\n')
    for (a, b), n in sorted(cruzam.items()):
        saida += f'  {a} -> {b} [label="  {n} FK  "]\n' if n > 1 else f'  {a} -> {b}\n'
    return saida + '}\n'


def slug(texto):
    import unicodedata
    s = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower()
    return '-'.join(''.join(c if c.isalnum() else ' ' for c in s).split())


if __name__ == '__main__':
    main()
