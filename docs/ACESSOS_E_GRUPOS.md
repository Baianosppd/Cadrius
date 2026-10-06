# Grupos de acesso — o que cada acesso concede (CAD-223)

Documento de referência. A mesma informação aparece no sistema em **Equipe → "O que cada acesso libera"**.
Este arquivo é gerado a partir do catálogo do código (`accounts/access.py` e `backoffice/permissions.py`), então os
dois sempre batem.

## Escritório

### Regras gerais
- Dono e administrador sempre têm acesso total e são quem configura os grupos.
- Quem não está em nenhum grupo segue o cargo: membro faz o dia a dia (sem financeiro e sem configurações); "somente leitura" só consulta.
- Quem está num grupo só acessa os módulos marcados; "editar" já inclui "ver".
- O perfil "somente leitura" nunca altera nada, mesmo num grupo com "editar".
- O Assistente IA e o conector Claude/ChatGPT respeitam o grupo: só mostram o que a pessoa pode ver.
- Toda mudança de grupo fica na trilha de auditoria.

### Módulos

| Módulo | Seção | "Ver" concede | "Ver e alterar" concede |
|---|---|---|---|
| **Contatos** | Dia a dia | Consultar o quadro de contatos (clientes, partes, parceiros), histórico e consentimentos. | Cadastrar, editar e arquivar contatos; registrar consentimento de WhatsApp/e-mail. |
| **Processos e publicações** | Dia a dia | Ver processos acompanhados, andamentos, publicações do DJEN, calendário forense e cálculo de prazos. | Cadastrar processos para acompanhar, revisar/confirmar publicações, cadastrar OABs e feriados locais. |
| **Documentos** | Dia a dia | Abrir documentos do escritório e a leitura feita pela IA. | Enviar documentos, confirmar ou refazer a leitura da IA e apagar documentos. |
| **Tarefas e agenda** | Dia a dia | Ver tarefas, prazos da agenda e compromissos trazidos do Google Agenda. | Criar, concluir e reatribuir tarefas; ajustar compromissos do Google Agenda. |
| **E-mails** | Dia a dia | Ler as caixas de e-mail conectadas e a triagem automática. | Conectar/desconectar caixas de e-mail. |
| **Minutas e modelos** | Produção | Abrir minutas e modelos de peças/contratos e baixar em Word. | Criar e editar minutas e modelos do escritório. |
| **Funil de clientes (oportunidades)** | Carteira | Ver oportunidades, etapas do funil e a ficha do cliente (sem valores financeiros). | Criar oportunidades e mover etapas do funil. |
| **Financeiro do escritório** | Carteira | Ver honorários, parcelas, despesas, painel, fluxo de caixa, DRE e o fiscal do escritório. | Criar contratos de honorários, dar baixa em parcelas, lançar despesas (avulsas e recorrentes) e meta do mês. |
| **Marketing** | Produção | Ver ideias, calendário de conteúdo, campanhas, formulários de captação e resultados por canal. | Escrever conteúdos, criar campanhas e formulários de captação (a publicação depende de aprovação). |
| **Automações** | Escritório | Ver regras, fluxos, histórico e a conformidade das automações. | Criar e editar fluxos com apps e aprovar envios pendentes (as regras do escritório pedem a permissão extra). |
| **Integrações** | Escritório | Ver os apps conectados e o catálogo de integrações. | Conectar, testar e remover apps (WhatsApp, Asaas, assinatura, ERP...). |
| **Assistente IA** | Escritório | Conversar com o Assistente IA (as ferramentas respeitam os demais acessos da pessoa). | Pedir ações ao assistente (tarefa, minuta, contato...) e usar o conector Claude/ChatGPT. |
| **Portal do cliente** | Carteira | Ver os links de portal enviados aos clientes. | Gerar e revogar links do portal do cliente. |
| **Importar dados** | Escritório | Ver importações feitas. | Importar planilhas de contatos/processos para o Cadrius. |

### Permissões extras

Essas ações eram só do dono ou administrador e agora o grupo pode liberar.

| Permissão | O que concede |
|---|---|
| **Criar, ligar e desligar regras do escritório** (`automacoes.gerir`) | Criar/editar regras de automação, simular e ligar. Toda regra continua nascendo desligada. |
| **Aprovar e publicar conteúdo** (`marketing.aprovar`) | Aprovar textos (com a checagem OAB) e publicar nas redes conectadas. |
| **Cancelar contratos e parcelas** (`financeiro.cancelar`) | Cancelar contratos de honorários e parcelas (ação auditada). |
| **Emitir nota fiscal de serviço** (`financeiro.nota`) | Pedir a emissão da NFS-e de honorários pelo app emissor conectado. |

### Modelos prontos

O dono ou administrador cria o grupo com um clique e ajusta.

| Modelo | Para quem | Libera |
|---|---|---|
| **Advogado(a)** | Dia a dia jurídico completo, sem financeiro. | Contatos (alterar), Processos e publicações (alterar), Documentos (alterar), Tarefas e agenda (alterar), E-mails (alterar), Minutas e modelos (alterar), Funil de clientes (oportunidades) (alterar), Marketing (ver), Automações (ver), Assistente IA (alterar), Portal do cliente (alterar) |
| **Estagiário(a)** | Consulta e prepara; não apaga contatos nem mexe no funil. | Contatos (ver), Processos e publicações (ver), Documentos (alterar), Tarefas e agenda (alterar), Minutas e modelos (alterar), Assistente IA (ver) |
| **Financeiro** | Honorários, cobranças, despesas e fiscal do escritório. | Contatos (ver), Tarefas e agenda (alterar), Funil de clientes (oportunidades) (ver), Financeiro do escritório (alterar), Assistente IA (ver), Portal do cliente (ver), Emitir nota fiscal de serviço |
| **Secretaria / atendimento** | Recebe clientes, agenda e organiza documentos. | Contatos (alterar), Documentos (alterar), Tarefas e agenda (alterar), E-mails (ver), Funil de clientes (oportunidades) (alterar), Assistente IA (ver), Portal do cliente (alterar) |
| **Marketing** | Conteúdo, campanhas e captação, com a checagem OAB. | Contatos (ver), Funil de clientes (oportunidades) (ver), Marketing (alterar), Assistente IA (ver) |
| **Somente consulta** | Vê o dia a dia sem alterar nada. | Contatos (ver), Processos e publicações (ver), Documentos (ver), Tarefas e agenda (ver), Minutas e modelos (ver), Funil de clientes (oportunidades) (ver) |

### Como funciona por dentro

- **Cada chamada à API** passa pela checagem do grupo na autenticação: módulo sem "ver" ou sem "alterar" devolve 403
  `module_forbidden`.
- **Menu:** o menu esconde o que o grupo não libera.
- **Assistente IA e conector Claude/ChatGPT:**
  - só oferecem ferramentas dos módulos liberados;
  - ações pedem "alterar";
  - ferramentas de gestão pedem a permissão extra.
- **Auditoria:** toda criação, alteração ou remoção de grupo e toda troca de grupo de uma pessoa ficam registradas
  (`team.access_group_saved`, `team.access_group_deleted`, `team.access_assigned`).

## Equipe Cadrius (Gestão)

Cada pessoa da equipe tem, por área, **acesso total** ou **só consulta**. Com "só consulta", qualquer alteração recebe 403.
A TI define os níveis em Gestão → Equipe Cadrius, e cada mudança fica na auditoria (`staff.areas_changed`).

| Área | Acesso total concede | Só consulta concede |
|---|---|---|
| **TI** | Saúde do sistema, Cibersegurança (bloqueio de IP, alertas), contas de usuários (senha temporária, bloqueio), equipe Cadrius (criar contas e definir áreas) e chave geral da IA. | Ver painéis de saúde, Cibersegurança, usuários e equipe, sem executar ações. |
| **Financeiro** | Planos e preços, promoções, créditos, assinaturas dos escritórios e indicadores (receita recorrente, cancelamentos, inadimplência). | Ver planos, assinaturas e indicadores sem alterar preços, promoções ou créditos. |
| **Fiscal** | Recebimentos da Cadrius, emissão/cancelamento de NFS-e, obrigações do mês e pacote do contador. | Ver recebimentos, notas e obrigações; baixar o pacote do contador. |
| **Suporte** | Fila de chamados e pedidos de parametrização: responder, mudar status, orçar e entregar. Dados do escritório só com acesso assistido concedido pelo cliente. | Ler a fila de chamados e parametrizações sem responder. |
| **Marketing** | Conteúdo e campanhas da Cadrius, crescimento (cadastros, conversão) e checagem OAB. | Ver conteúdos, campanhas e indicadores de crescimento. |
| **Jurídico** | Calendário forense nacional: suspensões de prazo e indisponibilidades por tribunal (avisam os escritórios e entram na contagem de prazos) e dados dos tribunais (Balcão Virtual, links de serviços). | Ver o calendário forense e os dados dos tribunais. |
