# Cadrius: arquitetura e diagramas

Diagramas do sistema completo: contexto, infraestrutura, serviços, fluxos principais, segurança, rotinas, entrega e banco de dados.

- **Como ver:** o GitHub desenha os blocos Mermaid desta página. Cada diagrama também está em `img/` (SVG, para slides e documentos) e a fonte em `fontes/` (`.mmd`).
- **Atualizar:** edite o `.mmd` e gere de novo com `npx -p @mermaid-js/mermaid-cli mmdc -i fontes/X.mmd -o img/X.svg -b white`.
- **Banco de dados:** gerado dos modelos Django (115 tabelas, sem as internas do Django). Cada tabela mostra a chave, os campos principais (até 9) e as chaves estrangeiras; `cifrado` = campo cifrado com índice cego. As ligações com `Organization` e `CustomUser` só aparecem no núcleo, para não poluir.

## Índice

**Sistema e serviços**

- [Visão geral: quem usa e com o que o Cadrius conversa](#01-contexto)
- [Infraestrutura e contêineres (produção e teste)](#02-infraestrutura)
- [Módulos do back-end (apps Django) e dependências](#03-modulos)
- [Front-end: áreas e telas](#04-frontend)
- [Fluxo: login (senha, MFA e SSO) e sessão](#05-login)
- [Fluxo: leitura de documento com IA](#06-documento)
- [Fluxo: automação (gatilho → regra → aprovação → envio)](#07-automacao)
- [Fluxo: Assistente IA (ferramentas e confirmação)](#08-assistente)
- [Fluxo: assinatura, créditos e cobrança (Stripe)](#09-cobranca)
- [Fluxo: publicações do DJEN e prazos](#10-publicacoes)
- [Fluxo: importar carteira de clientes por pastas (Drive ou .zip)](#11-pastas)
- [Camadas de segurança e LGPD](#12-seguranca)
- [Rotinas agendadas (worker)](#13-rotinas)
- [Entrega contínua (CI/CD)](#14-deploy)

**Banco de dados**

- [Núcleo: contas, escritórios e acesso](#20-banco-01-nucleo)
- [Planos, créditos, pagamentos e fiscal da Cadrius](#20-banco-02-assinatura)
- [Clientes, processos, prazos e documentos](#20-banco-03-clientes)
- [Carteira (CRM) e financeiro do escritório](#20-banco-04-financeiro)
- [Automações, fluxos e e-mails](#20-banco-05-automacao)
- [IA: assistente, governança e aprendizado](#20-banco-06-ia)
- [Integrações, Google, ERP, marketing e suporte](#20-banco-07-integracoes)
- [Segurança, auditoria e LGPD](#20-banco-08-seguranca)

# Sistema e serviços

<a id="01-contexto"></a>
## Visão geral: quem usa e com o que o Cadrius conversa

Contexto (C4 nível 1):
- **Quem usa:** o escritório (advogados e equipe), o cliente do escritório (portal, captação e pesquisa) e a equipe Cadrius (Gestão).
- **Serviços externos:** os de que o Cadrius depende.

Imagem: [`img/01-contexto.svg`](img/01-contexto.svg)

```mermaid
flowchart LR
    classDef pessoa fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef sistema fill:#1d4ed8,stroke:#0a2463,color:#fff
    classDef ext fill:#f1f5f9,stroke:#64748b,color:#1e293b
    ADV["Advogados e equipe<br/>do escritório"]:::pessoa
    CLI["Cliente do escritório<br/>(portal, captação, pesquisa)"]:::pessoa
    STAFF["Equipe Cadrius<br/>(Gestão)"]:::pessoa
    CAD(("Cadrius<br/>app + API")):::sistema
    ADV -->|navegador / celular / relógio| CAD
    CLI -->|links públicos com token| CAD
    STAFF -->|Gestão com MFA| CAD
    CAD --> IA["Provedores de IA<br/>Claude · OpenAI · Gemini · Groq<br/>Maritaca · Mistral · OpenRouter · Ollama"]:::ext
    CAD --> GOO["Google<br/>login · Agenda · Planilhas · Docs · Drive"]:::ext
    CAD --> MS["Microsoft<br/>login (SSO)"]:::ext
    CAD --> PAY["Stripe (assinatura Cadrius)<br/>Asaas (cobrança do escritório)"]:::ext
    CAD --> JUD["Judiciário<br/>DJEN (publicações) · DataJud"]:::ext
    CAD --> MSG["Mensagens<br/>WhatsApp (Evolution) · e-mail SMTP/IMAP<br/>Slack · Teams · Telegram"]:::ext
    CAD --> FIS["Fiscal<br/>Focus NFe (NFS-e)"]:::ext
    CAD --> PUB["Dados públicos<br/>BrasilAPI (CNPJ/CEP)"]:::ext
    CAD --> ASS["Assinatura digital<br/>ZapSign · D4Sign · Autentique"]:::ext
    CAD --> OBS["Sentry (erros)<br/>armazenamento externo (backups)"]:::ext
```

<a id="02-infraestrutura"></a>
## Infraestrutura e contêineres (produção e teste)

Os contêineres do servidor, como estão em `deploy/infra/docker-compose.yml` e `deploy/app/docker-compose.yml`:
- **Traefik:** compartilhado entre produção e teste.
- **Por ambiente** (`prod` e `staging`), cada um com o seu: web, worker, frontend, Redis e Evolution.
- **Postgres:** um servidor só, com uma base por ambiente.

Imagem: [`img/02-infraestrutura.svg`](img/02-infraestrutura.svg)

```mermaid
flowchart TB
    classDef edge fill:#0a2463,stroke:#0a2463,color:#fff
    classDef app fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef data fill:#fef3c7,stroke:#b45309,color:#451a03
    classDef ext fill:#f1f5f9,stroke:#64748b,color:#1e293b
    U["Navegador / celular"] -->|HTTPS 443| T
    subgraph INFRA["infra (compartilhada)"]
        T["Traefik<br/>TLS Let's Encrypt · cabeçalhos de segurança<br/>limite por IP · corpo 2 MB (upload 30 MB / .zip 2 GB)"]:::edge
        PG[("PostgreSQL<br/>base cadrius_prod e cadrius_staging")]:::data
        DZ["Dozzle<br/>(logs dos contêineres)"]:::app
    end
    subgraph AMB["ambiente (prod ou staging)"]
        FE["frontend<br/>nginx + React (Vite)<br/>app.cadrius.ia.br"]:::app
        WEB["web<br/>Django + DRF (uvicorn ASGI)<br/>api.cadrius.ia.br"]:::app
        WK["worker<br/>Django-Q (qcluster)<br/>tarefas e rotinas agendadas"]:::app
        RD[("Redis<br/>fila, cache, limites")]:::data
        MEDIA[("volume media<br/>documentos cifrados<br/>.zip temporários")]:::data
        EVO["Evolution API<br/>WhatsApp"]:::app
    end
    T -->|app.*| FE
    T -->|api.*| WEB
    WEB --> PG
    WK --> PG
    WEB <--> RD
    WK <--> RD
    WEB --- MEDIA
    WK --- MEDIA
    WK --> EVO
    WEB --> EVO
    WK -->|HTTPS| EXT["APIs externas<br/>(IA, Google, Stripe, DJEN…)"]:::ext
    WEB -->|HTTPS| EXT
    subgraph HOST["servidor (systemd)"]
        BK["backup diário (pg_dump + gpg)<br/>verificação de restauração<br/>cópia externa (rclone/B2/S3)"]:::app
    end
    BK --> PG
    BK --> OFF[("Armazenamento externo<br/>de backups")]:::data
```

<a id="03-modulos"></a>
## Módulos do back-end (apps Django) e dependências

Os apps Django agrupados por área. As setas mostram quem chama quem nos fluxos principais.

Imagem: [`img/03-modulos.svg`](img/03-modulos.svg)

```mermaid
flowchart LR
    classDef core fill:#1d4ed8,stroke:#0a2463,color:#fff
    classDef dom fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef ia fill:#ede9fe,stroke:#6d28d9,color:#2e1065
    classDef sec fill:#fee2e2,stroke:#b91c1c,color:#450a0a
    classDef int fill:#dcfce7,stroke:#15803d,color:#052e16
    subgraph NUC["Núcleo"]
        accounts["accounts<br/>usuários · escritórios · MFA · SSO · grupos"]:::core
        billing["billing<br/>planos · créditos · Stripe · fiscal"]:::core
        core_["core<br/>cifra · índices cegos · fila"]:::core
        backoffice["backoffice<br/>Gestão Cadrius"]:::core
    end
    subgraph DOM["Escritório"]
        contacts["contacts"]:::dom
        documents["documents<br/>leitura de documentos"]:::dom
        research["research<br/>processos monitorados"]:::dom
        publications["publications<br/>DJEN"]:::dom
        forense["forense<br/>prazos e feriados"]:::dom
        tasks["tasks"]:::dom
        minutas["minutas"]:::dom
        carteira["carteira<br/>CRM e financeiro"]:::dom
        portal["portal do cliente"]:::dom
        marketing["marketing"]:::dom
        imports["imports<br/>planilhas e pastas"]:::dom
        support["support"]:::dom
    end
    subgraph AUT["Automação e IA"]
        automations["automations<br/>regras"]:::ia
        workflows["workflows<br/>fluxos com apps"]:::ia
        assistant["assistant<br/>chat + ferramentas + MCP"]:::ia
        aigov["aigov<br/>IA governada"]:::ia
        brain["brain<br/>aprendizado"]:::ia
        emails["emails<br/>triagem"]:::ia
    end
    subgraph INT["Integrações"]
        gcal["gcal<br/>Google"]:::int
        integrations["integrations<br/>conectores · WhatsApp · dados públicos"]:::int
        erp["erp"]:::int
        webhooks["webhooks"]:::int
    end
    subgraph SEC["Segurança e LGPD"]
        audit["audit<br/>trilha encadeada"]:::sec
        privacy["privacy"]:::sec
        compliance["compliance"]:::sec
    end
    assistant --> aigov
    documents --> aigov
    emails --> aigov
    marketing --> aigov
    aigov --> billing
    documents --> automations
    publications --> automations
    contacts --> automations
    emails --> automations
    carteira --> automations
    gcal --> automations
    automations --> integrations
    automations --> gcal
    assistant --> automations
    assistant --> contacts
    imports --> contacts
    imports --> documents
    brain --> automations
    DOM --> audit
    AUT --> audit
```

<a id="04-frontend"></a>
## Front-end: áreas e telas

A aplicação React (`Cadrius---Front-end`) e as áreas de navegação.

Imagem: [`img/04-frontend.svg`](img/04-frontend.svg)

```mermaid
flowchart TB
    classDef pub fill:#f1f5f9,stroke:#64748b,color:#1e293b
    classDef esc fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef ges fill:#0a2463,stroke:#0a2463,color:#fff
    APP["SPA React + Vite<br/>services/api.js (JWT + renovação com Web Locks)"]
    APP --> P["Público"]:::pub
    APP --> E["Escritório (login)"]:::esc
    APP --> G["Gestão Cadrius (staff + MFA)"]:::ges
    P --> P1["Login · cadastro · senha"]:::pub
    P --> P2["Portal do cliente · captação<br/>pesquisa · parear WhatsApp"]:::pub
    E --> E1["Dia a dia<br/>Painel · Assistente IA · Relógio e voz<br/>Publicações · Processos · Agenda forense · Documentos"]:::esc
    E --> E2["Produção<br/>Minutas · Automações (React Flow) · Contatos"]:::esc
    E --> E3["Clientes e finanças<br/>Carteira · Finanças · Marketing"]:::esc
    E --> E4["Configurações<br/>Equipe · Integrações · IA do escritório<br/>Plugins · Importar dados"]:::esc
    E --> E5["Segurança<br/>Privacidade · IA segura · Auditoria"]:::esc
    G --> G1["Início · Receita (financeiro, fiscal, promoções)<br/>Atendimento (suporte, marketing, jurídico)<br/>Pessoas e acessos · Plataforma (IA, cibersegurança)"]:::ges
```

<a id="05-login"></a>
## Fluxo: login (senha, MFA e SSO) e sessão

JWT de acesso curto e refresh rotativo:
- **"Manter conectado":** 30 dias, renovados a cada uso.
- **Sem marcar:** 1 dia.
- **Gestão Cadrius:** exige MFA.

Imagem: [`img/05-login.svg`](img/05-login.svg)

```mermaid
sequenceDiagram
    autonumber
    actor U as Pessoa
    participant FE as Front (React)
    participant API as API Django
    participant G as Google / Microsoft
    alt E-mail e senha
        U->>FE: e-mail, senha, "manter conectado"
        FE->>API: POST /auth/token/ (lembrar)
        API->>API: axes (bloqueio por tentativas) + senha
        opt MFA ativo
            API-->>FE: mfa_token (5 min)
            U->>FE: código do app autenticador
            FE->>API: POST /auth/mfa/verify/
        end
    else Entrar com Google/Microsoft (SSO)
        FE->>G: autorização (openid email profile, state + nonce)
        G-->>FE: /google/callback?code
        FE->>API: troca do code, valida id_token (JWKS)
        API->>API: SocialIdentity → usuário
    end
    API-->>FE: access (curto) + refresh (30 dias ou 1 dia)
    FE->>API: chamadas com Bearer access
    Note over FE,API: access venceu → POST /auth/token/refresh/<br/>refresh rotativo + blacklist, uma aba renova por vez (Web Locks)
```

<a id="06-documento"></a>
## Fluxo: leitura de documento com IA

Pipeline de `documents/pipeline.py`:
- o arquivo é salvo cifrado;
- a leitura acontece no worker, com dados mascarados e IA governada;
- nada vira prazo sem a revisão de alguém.

Imagem: [`img/06-documento.svg`](img/06-documento.svg)

```mermaid
sequenceDiagram
    autonumber
    actor U as Advogado
    participant API as API
    participant ST as Armazenamento cifrado
    participant Q as Fila (Redis)
    participant W as Worker
    participant GOV as aigov (política + créditos)
    participant IA as Provedor de IA
    U->>API: envia arquivo (até 25 MB)
    API->>ST: grava cifrado (Document)
    API->>Q: enqueue process_document
    API-->>U: 201 (documento salvo)
    Q->>W: process_document
    W->>W: tipo pelo conteúdo → texto (PDF/DOCX) ou OCR
    W->>W: mascara CPF, CNPJ, e-mail e telefone
    W->>GOV: pode usar IA? (política, provedor, saldo de créditos)
    GOV-->>W: provedor + fallback
    W->>IA: extrair partes, datas, prazos e valores
    IA-->>W: JSON
    W->>W: DocumentExtraction = aguardando revisão
    U->>API: confere e confirma
    API->>API: emit("document_confirmed") → automações
```

<a id="07-automacao"></a>
## Fluxo: automação (gatilho → regra → aprovação → envio)

O motor de `automations/engine.py`:
- **Ordem do motor:** deduplicação, condições, planejamento dos passos, execução dos internos, aprovação dos externos (conforme a autonomia) e checagem de consentimento na hora do envio.
- **Ao ligar a regra:** é obrigatório simular antes.

Imagem: [`img/07-automacao.svg`](img/07-automacao.svg)

```mermaid
flowchart TB
    classDef ev fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef dec fill:#fef3c7,stroke:#b45309,color:#451a03
    classDef ok fill:#dcfce7,stroke:#15803d,color:#052e16
    classDef stop fill:#fee2e2,stroke:#b91c1c,color:#450a0a
    EV["Evento<br/>e-mail triado · publicação · documento confirmado<br/>andamento · prazo · honorário · contato · agenda<br/>agendado (cron) · atalho/voz"]:::ev --> EMIT["emit(organização, gatilho, refs, dedupe)"]
    EMIT --> RULES{"Regras ligadas<br/>para o gatilho?"}:::dec
    RULES -- não --> FIM1["nada"]:::stop
    RULES -- sim --> DED{"Já rodou para<br/>este evento?"}:::dec
    DED -- sim --> FIM2["ignorado (dedupe)"]:::stop
    DED -- não --> CTX["Monta o contexto<br/>(cliente, processo, prazo, variáveis)"]
    CTX --> COND{"Condições<br/>atendidas?"}:::dec
    COND -- não --> SK["RuleRun: condições não atendidas"]:::stop
    COND -- sim --> PLAN["Planeja os passos<br/>calcular · tabela · tarefa · aviso · mensagem<br/>planilha/agenda Google · ERP · chat da equipe"]
    PLAN --> INT["Passos internos<br/>executa já"]:::ok
    PLAN --> EXT{"Passo externo<br/>(mensagem, ERP…)"}:::dec
    EXT -- precisa aprovação --> APR["RuleRun: aguardando aprovação<br/>(tela, sino ou relógio)"]:::dec
    APR -- aprovado --> SEND
    APR -- recusado/expirou --> STOP["não envia"]:::stop
    EXT -- autonomia permite --> SEND["Envia"]
    SEND --> CONS{"Consentimento do canal<br/>+ horário comercial?"}:::dec
    CONS -- sim --> OUT["WhatsApp (Evolution) ou e-mail<br/>no visual do escritório"]:::ok
    CONS -- fora do horário --> LATER["agenda para 8h do próximo dia útil"]
    CONS -- sem consentimento --> BLK["bloqueado (motivo registrado)"]:::stop
    OUT --> AUD["auditoria + RuleRun concluída"]
```

<a id="08-assistente"></a>
## Fluxo: Assistente IA (ferramentas e confirmação)

O Assistente consulta os dados por ferramentas. As ações (criar tarefa, regra, contato, mensagem, evento no Google…) viram um pedido de confirmação: só são executadas depois que a pessoa aprova.

Imagem: [`img/08-assistente.svg`](img/08-assistente.svg)

```mermaid
sequenceDiagram
    autonumber
    actor U as Advogado
    participant FE as Front
    participant API as assistant
    participant GOV as aigov
    participant LLM as IA (Claude, OpenAI…)
    participant T as Ferramentas
    U->>FE: "Crie uma automação: intimação por e-mail vira tarefa e avisa o João"
    FE->>API: POST /assistant/conversations/
    API->>GOV: política + créditos + provedor da atividade "assistente"
    API->>LLM: mensagens + catálogo de ferramentas (só as permitidas ao grupo de acesso)
    LLM-->>API: chama buscar_contatos / catalogo_de_automacao
    API->>T: executa (leitura, só dados do escritório)
    T-->>API: resultado (dados de terceiros marcados como não confiáveis)
    LLM-->>API: chama criar_regra(..., novo_contato)
    API->>API: PendingAction + resumo (prévia, nada gravado)
    API-->>FE: resposta + cartão "Aguardando sua confirmação"
    U->>FE: Confirmar
    FE->>API: POST /assistant/actions/{id}/decide/
    API->>T: cadastra o contato (se novo) + cria a regra desligada
    API->>API: auditoria
    API-->>FE: Feito + link para abrir o fluxo
```

<a id="09-cobranca"></a>
## Fluxo: assinatura, créditos e cobrança (Stripe)

Planos, pacotes de créditos e o adicional de mídia passam pelo Checkout do Stripe. A confirmação chega pelo webhook.

Imagem: [`img/09-cobranca.svg`](img/09-cobranca.svg)

```mermaid
sequenceDiagram
    autonumber
    actor D as Dono do escritório
    participant FE as Front
    participant API as billing
    participant S as Stripe
    D->>FE: Assinar plano / comprar créditos / adicional de mídia
    FE->>API: POST checkout (plano, cupom)
    API->>S: cria Checkout Session (metadata: org, tipo)
    S-->>FE: redireciona para o pagamento
    D->>S: paga (cartão / boleto)
    S->>API: webhook /api/billing/webhook/ (assinado)
    API->>API: confere assinatura (STRIPE_WEBHOOK_SECRET) e idempotência
    alt checkout.session.completed
        API->>API: ativa plano · CreditLot · MediaAddon · Payment
    else invoice.paid / payment_succeeded
        API->>API: renova período · Payment
    else invoice.payment_failed
        API->>API: marca atraso (carência)
    else customer.subscription.deleted
        API->>API: cancela (dados mantidos)
    end
    API-->>S: 200
    Note over API: sem saldo de créditos → aigov bloqueia qualquer IA (no_credits)
```

<a id="10-publicacoes"></a>
## Fluxo: publicações do DJEN e prazos

Rotina a cada 3 horas: busca as intimações das OABs acompanhadas, faz a triagem e sugere o prazo. O prazo só entra na agenda depois que alguém confirma.

Imagem: [`img/10-publicacoes.svg`](img/10-publicacoes.svg)

```mermaid
flowchart LR
    classDef job fill:#ede9fe,stroke:#6d28d9,color:#2e1065
    classDef ok fill:#dcfce7,stroke:#15803d,color:#052e16
    S["Agendador Django-Q<br/>publications_poll (180 min)"]:::job --> DJ["DJEN<br/>comunicaapi.pje.jus.br"]
    DJ --> PUB["Publication<br/>(por OabWatch)"]
    PUB --> TRI["Triagem<br/>regras locais ou IA"]
    TRI --> PRZ["Prazo sugerido<br/>forense: dias úteis, feriados,<br/>suspensões do tribunal"]
    PRZ --> REV{"Advogado confirma?"}
    REV -- sim --> TASK["Tarefa / prazo na agenda<br/>(+ Google Agenda)"]:::ok
    PUB --> EMIT["emit publication_new → automações"]
    REV -- descarta --> DESC["Descartada"]
```

<a id="11-pastas"></a>
## Fluxo: importar carteira de clientes por pastas (Drive ou .zip)

CAD-234:
- cada pasta vira um cliente e os arquivos dentro dela, os documentos dele;
- a prévia não grava nada;
- a importação roda em etapas de 40 s e reimportar não duplica.

Imagem: [`img/11-pastas.svg`](img/11-pastas.svg)

```mermaid
sequenceDiagram
    autonumber
    actor U as Advogado
    participant FE as Front
    participant API as imports
    participant G as Google Drive
    participant W as Worker
    alt Pelo Google Drive
        U->>FE: autoriza leitura do Drive (uma vez) e cola o link da pasta-mãe
        FE->>API: POST /imports/pastas/ (link da pasta)
        API->>G: lista subpastas e arquivos (só nomes)
    else Pelo .zip
        U->>FE: envia o .zip baixado do Drive
        FE->>API: POST /imports/pastas/zip/
        API->>API: lê só o índice e guarda o .zip em pasta privada (0600)
    end
    API-->>FE: prévia: cliente, CPF/CNPJ, arquivos, já é contato?
    U->>FE: desmarca o que não quer, IA opcional, Importar
    FE->>API: POST /imports/pastas/:id/importar/
    API->>W: enqueue run
    loop etapas de ~40 s
        W->>W: contato existente (CPF/CNPJ ou nome) ou novo
        W->>G: baixa o arquivo (Docs → PDF) ou lê do .zip
        W->>W: Document cifrado ligado ao contato
    end
    W->>W: apaga o .zip e a prévia + auditoria
    FE->>API: acompanha o progresso
```

<a id="12-seguranca"></a>
## Camadas de segurança e LGPD

Defesa em profundidade, da borda aos dados.

Imagem: [`img/12-seguranca.svg`](img/12-seguranca.svg)

```mermaid
flowchart TB
    classDef l fill:#fee2e2,stroke:#b91c1c,color:#450a0a
    A["Borda<br/>Traefik: TLS, HSTS, cabeçalhos, limite por IP e de corpo<br/>bloqueio de IP pela TI"]:::l
    B["Identidade<br/>senha forte + bloqueio por tentativas (axes)<br/>MFA TOTP · SSO Google/Microsoft · JWT rotativo com blacklist"]:::l
    C["Autorização<br/>escritório isolado (multi-tenant)<br/>cargo + grupo de acesso por módulo"]:::l
    D["Dados<br/>campos pessoais cifrados + índices cegos para busca<br/>arquivos cifrados em repouso · segredos no .env"]:::l
    E["IA governada<br/>provedores permitidos por escritório · dados mascarados<br/>créditos · autonomia supervisionada · kill switch"]:::l
    F["Rastreabilidade<br/>auditoria imutável encadeada por hash · alertas de anomalia<br/>Sentry"]:::l
    G["LGPD<br/>consentimento por canal · pedidos do titular · suboperadores<br/>retenção e expurgo · desligamento do escritório em 30 dias"]:::l
    H["Continuidade<br/>backup diário cifrado (gpg) · cópia externa<br/>teste de restauração automático"]:::l
    A --> B --> C --> D --> E --> F --> G --> H
```

<a id="13-rotinas"></a>
## Rotinas agendadas (worker)

Agendadas pelo comando `setup_security_schedules` e executadas pelo Django-Q.

Imagem: [`img/13-rotinas.svg`](img/13-rotinas.svg)

```mermaid
flowchart LR
    classDef m fill:#ede9fe,stroke:#6d28d9,color:#2e1065
    classDef h fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    classDef d fill:#dcfce7,stroke:#15803d,color:#052e16
    Q(("Django-Q<br/>worker"))
    Q --> M5["5 min<br/>detectar anomalias"]:::m
    Q --> M15["15 min<br/>automações (prazos e agendadas)<br/>Google Agenda (sincronizar)<br/>marketing (publicar agendados)"]:::m
    Q --> H1["1 h<br/>andamentos de processos · notícias<br/>fiscal (NFS-e e obrigações)"]:::h
    Q --> H3["3 h<br/>publicações do DJEN"]:::h
    Q --> H6["6 h<br/>despesas fixas do mês"]:::h
    Q --> D1["diária<br/>cadeia de auditoria · retenção LGPD<br/>fotografia de conformidade<br/>aprendizado da IA · limpeza de importações"]:::d
```

<a id="14-deploy"></a>
## Entrega contínua (CI/CD)

Do pull request ao servidor.

Imagem: [`img/14-deploy.svg`](img/14-deploy.svg)

```mermaid
flowchart LR
    classDef g fill:#dcfce7,stroke:#15803d,color:#052e16
    classDef b fill:#dbeafe,stroke:#1d4ed8,color:#0a2463
    PR["Pull request<br/>CAD-xxx → main"] --> CI["GitHub Actions (CI)<br/>back: testes Django (Postgres+Redis), lint, SAST,<br/>dependências, gitleaks, imagem + Trivy<br/>front: lint, build, testes, imagem nginx"]:::b
    CI --> REV["Revisão e merge"]
    REV -->|main| DP["deploy.yml → servidor<br/>deploy.sh prod"]:::g
    DEV["push em develop"] --> DS["deploy-staging.yml<br/>deploy.sh staging"]:::g
    DP --> STEPS["atualiza o kit · backup antes<br/>git pull back + front · build das imagens<br/>sobe · migra · rotinas · /readyz<br/>falhou → rollback automático"]
    DS --> STEPS
```

# Banco de dados

Toda tabela de dado de escritório tem `organization_id` (isolamento entre escritórios); quase todas têm `created_by`/`created_at`.

<a id="20-banco-01-nucleo"></a>
## Banco de dados: Núcleo: contas, escritórios e acesso

Tabelas: AccessGroup, CustomUser, MFADevice, MFARecoveryCode, Organization, OrganizationMembership, SocialIdentity, UserMessageSendCount. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-01-nucleo.svg`](img/20-banco-01-nucleo.svg)

```mermaid
erDiagram
    AccessGroup {
        bigint id PK
        texto name
        texto description
        json permissions
        int organization_id FK
        int created_by_id FK
    }
    CustomUser {
        data_hora last_login
        bool is_superuser
        texto username
        texto email
        bool is_staff
        bool is_active
        data_hora date_joined
        uuid id PK
        cifrado first_name
    }
    MFADevice {
        bigint id PK
        cifrado secret
        data_hora confirmed_at
        bigint last_step
        int user_id FK
    }
    MFARecoveryCode {
        bigint id PK
        texto code_hash
        data_hora used_at
        int user_id FK
    }
    Organization {
        uuid id PK
        texto account_type
        texto name
        texto nome_fantasia
        texto razao_social
        cifrado cnpj
        texto company_type
        texto tax_regime
        texto company_size
        int plan_id FK
        int pending_promotion_id FK
    }
    OrganizationMembership {
        uuid id PK
        texto role
        texto job_title
        int credit_limit
        bool is_active
        data_hora joined_at
        int user_id FK
        int organization_id FK
        int access_group_id FK
    }
    SocialIdentity {
        bigint id PK
        texto provider
        texto subject
        texto email_at_link
        int user_id FK
    }
    UserMessageSendCount {
        bigint id PK
        int whatsapp_count
        int email_count
        int automations_run_count
        int document_analysis_count
        int user_id FK
    }
    Group {
        int id PK "em outro diagrama"
    }
    Permission {
        int id PK "em outro diagrama"
    }
    Promotion {
        int id PK "em outro diagrama"
    }
    SubscriptionPlan {
        int id PK "em outro diagrama"
    }
    AccessGroup }o--|| Organization : "organization"
    AccessGroup }o--o| CustomUser : "created_by"
    CustomUser }o--o{ Group : "groups"
    CustomUser }o--o{ Permission : "user_permissions"
    MFADevice ||--|| CustomUser : "user"
    MFARecoveryCode }o--|| CustomUser : "user"
    Organization }o--|| SubscriptionPlan : "plan"
    Organization }o--o| Promotion : "pending_promotion"
    OrganizationMembership }o--|| CustomUser : "user"
    OrganizationMembership }o--|| Organization : "organization"
    OrganizationMembership }o--o| AccessGroup : "access_group"
    SocialIdentity }o--|| CustomUser : "user"
    UserMessageSendCount ||--|| CustomUser : "user"
```

<a id="20-banco-02-assinatura"></a>
## Banco de dados: Planos, créditos, pagamentos e fiscal da Cadrius

Tabelas: AIUsageLog, BillingNotice, CreditLot, CreditPack, CreditWeight, FiscalObligation, FiscalObligationDone, MediaAddon, MemberCreditUsage, Payment, PlanPriceHistory, Promotion, PromotionRedemption, SubscriptionPlan. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-02-assinatura.svg`](img/20-banco-02-assinatura.svg)

```mermaid
erDiagram
    AIUsageLog {
        bigint id PK
        data billing_cycle_month
        int extractions_count
        int organization_id FK
    }
    BillingNotice {
        bigint id PK
        texto title
        texto body
        texto severity
        json audience_tiers
        json audience_statuses
        data_hora starts_at
        data_hora ends_at
        bool is_active
    }
    CreditLot {
        bigint id PK
        int credits_total
        int credits_remaining
        data_hora expires_at
        texto stripe_session_id
        int amount_paid_cents
        int organization_id FK
    }
    CreditPack {
        bigint id PK
        texto name
        int credits
        decimal price_brl
        bool is_active
    }
    CreditWeight {
        bigint id PK
        texto operation
        texto label
        int credits
        bool is_active
    }
    FiscalObligation {
        bigint id PK
        texto code
        texto name
        texto description
        texto periodicity
        int due_day
        int due_month
        texto adjust
        bool active
    }
    FiscalObligationDone {
        bigint id PK
        texto competence
        data_hora done_at
        texto note
        int obligation_id FK
        int done_by_id FK
    }
    MediaAddon {
        bigint id PK
        bool active
        texto source
        texto stripe_subscription_id
        texto stripe_session_id
        data_hora started_at
        data_hora ends_at
        int organization_id FK
    }
    MemberCreditUsage {
        bigint id PK
        data billing_cycle_month
        int credits_used
        int membership_id FK
    }
    Payment {
        bigint id PK
        texto kind
        texto description
        int amount_cents
        data_hora paid_at
        texto stripe_id
        texto invoice_status
        texto invoice_number
        data invoice_issued_at
        int organization_id FK
    }
    PlanPriceHistory {
        bigint id PK
        decimal old_price
        decimal new_price
        int old_credits
        int new_credits
        texto changed_by
        data_hora changed_at
        int plan_id FK
    }
    Promotion {
        bigint id PK
        texto code
        texto name
        texto description
        texto kind
        decimal value
        texto duration
        int duration_months
        json plan_tiers
    }
    PromotionRedemption {
        bigint id PK
        texto stripe_session_id
        int promotion_id FK
        int organization_id FK
    }
    SubscriptionPlan {
        bigint id PK
        texto name
        texto tier
        decimal price_brl
        int max_users
        int max_ai_extractions
        bool is_active
    }
    OrganizationMembership {
        int id PK "em outro diagrama"
    }
    FiscalObligationDone }o--|| FiscalObligation : "obligation"
    MemberCreditUsage }o--|| OrganizationMembership : "membership"
    PlanPriceHistory }o--|| SubscriptionPlan : "plan"
    PromotionRedemption }o--|| Promotion : "promotion"
```

<a id="20-banco-03-clientes"></a>
## Banco de dados: Clientes, processos, prazos e documentos

Tabelas: CaseMovement, ClientDocument, Contact, CourtInfo, CourtSuspension, Document, DocumentExtraction, Draft, DraftTemplate, FolderImport, Holiday, ImportJob, IntegrationConfig, IntegrationLog, MonitoredCase, NewsItem, OabWatch, PortalLink, Publication, UserTask. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-03-clientes.svg`](img/20-banco-03-clientes.svg)

```mermaid
erDiagram
    Contact {
        bigint id PK
        texto kind
        texto person_type
        cifrado name
        cifrado document
        cifrado email
        cifrado phone
        cifrado notes
        json tags
        int organization_id FK
        int created_by_id FK
    }
    ClientDocument {
        bigint id PK
        cifrado nome_cliente
        int documento_id FK
    }
    Document {
        bigint id PK
        texto nome
        texto tipo
        texto status
        data_hora data
        arquivo arquivo
        int organization_id FK
        int uploaded_by_id FK
        int contact_id FK
    }
    DocumentExtraction {
        bigint id PK
        texto status
        texto stage
        texto detected_kind
        int text_chars
        bool ocr_used
        texto provider
        int confidence
        cifrado fields
        int document_id FK
        int reviewed_by_id FK
    }
    CourtInfo {
        bigint id PK
        texto tribunal
        texto name
        texto balcao_virtual_url
        texto services_url
        texto hearings_url
        texto hours
        texto notes
        int updated_by_id FK
    }
    CourtSuspension {
        bigint id PK
        texto tribunal
        texto comarca
        texto kind
        data start
        data end
        texto reason
        texto source_url
        int created_by_id FK
    }
    Holiday {
        bigint id PK
        data date
        texto name
        texto tribunal
        bool yearly
        int organization_id FK
    }
    FolderImport {
        bigint id PK
        texto source
        texto label
        texto drive_folder_id
        texto archive_path
        cifrado plan
        json options
        json progress
        texto status
        int organization_id FK
        int created_by_id FK
    }
    ImportJob {
        bigint id PK
        texto target
        texto filename
        texto status
        json columns
        cifrado rows
        int rows_total
        json mapping
        json summary
        int organization_id FK
        int created_by_id FK
    }
    Draft {
        bigint id PK
        texto template_key
        texto title
        texto source_type
        int source_id
        cifrado content
        cifrado generated_content
        cifrado citations
        int pending
        int organization_id FK
        int created_by_id FK
        int reviewed_by_id FK
    }
    DraftTemplate {
        bigint id PK
        texto name
        texto kind
        texto body
        int organization_id FK
        int created_by_id FK
    }
    PortalLink {
        bigint id PK
        texto token_hash
        texto hint
        bool show_finance
        data_hora expires_at
        data_hora revoked_at
        data_hora last_access_at
        int access_count
        int organization_id FK
        int contact_id FK
        int created_by_id FK
    }
    OabWatch {
        bigint id PK
        texto numero
        texto uf
        texto nome
        bool is_active
        data_hora last_checked_at
        texto last_error
        int organization_id FK
        int responsavel_id FK
    }
    Publication {
        bigint id PK
        texto source
        texto external_id
        texto tribunal
        texto tipo
        texto orgao
        texto classe
        cifrado cnj
        cifrado texto
        int organization_id FK
        int watch_id FK
        int case_id FK
        int task_id FK
        int reviewed_by_id FK
    }
    CaseMovement {
        bigint id PK
        data_hora occurred_at
        texto code
        texto name
        texto complement
        texto digest
        bool notified
        int case_id FK
    }
    MonitoredCase {
        bigint id PK
        cifrado cnj
        texto tribunal
        cifrado label
        bool is_active
        data_hora last_checked_at
        data_hora last_movement_at
        texto last_error
        int organization_id FK
        int responsavel_id FK
        int client_id FK
    }
    NewsItem {
        bigint id PK
        texto source
        texto url
        texto title
        texto summary
        data_hora published_at
    }
    IntegrationConfig {
        bigint id PK
        texto name
        cifrado trello_api_key
        cifrado trello_api_token
        texto trello_list_id
        cifrado telegram_bot_token
        texto telegram_chat_id
        bool is_active
    }
    IntegrationLog {
        bigint id PK
        texto service
        texto status
        json request_data
        int response_code
        json response_body
        data_hora attempted_at
        int email_message_id FK
    }
    UserTask {
        bigint id PK
        texto titulo
        texto descricao
        data_hora scheduled_at
        texto priority
        bool sincronizar
        bool completed
        int responsavel_id FK
    }
    EmailMessage {
        int id PK "em outro diagrama"
    }
    ClientDocument }o--|| Document : "documento"
    Document }o--o| Contact : "contact"
    DocumentExtraction ||--|| Document : "document"
    PortalLink }o--|| Contact : "contact"
    Publication }o--o| OabWatch : "watch"
    Publication }o--o| MonitoredCase : "case"
    Publication }o--o| UserTask : "task"
    CaseMovement }o--|| MonitoredCase : "case"
    MonitoredCase }o--o| Contact : "client"
    IntegrationLog }o--|| EmailMessage : "email_message"
```

<a id="20-banco-04-financeiro"></a>
## Banco de dados: Carteira (CRM) e financeiro do escritório

Tabelas: AsaasEvent, Expense, FeeAgreement, FinanceSettings, Opportunity, Receivable, RecurringExpense. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-04-financeiro.svg`](img/20-banco-04-financeiro.svg)

```mermaid
erDiagram
    AsaasEvent {
        bigint id PK
        texto event_id
        texto event
        texto payment_id
        int organization_id FK
    }
    Expense {
        bigint id PK
        texto description
        texto category
        positivebiginteger amount_cents
        data date
        bool reimbursable
        int organization_id FK
        int contact_id FK
        int case_id FK
        int reimbursement_id FK
        int created_by_id FK
    }
    FeeAgreement {
        bigint id PK
        texto title
        texto kind
        positivebiginteger total_cents
        int installments
        data first_due
        decimal success_pct
        texto status
        cifrado notes
        int organization_id FK
        int contact_id FK
        int case_id FK
        int opportunity_id FK
        int created_by_id FK
    }
    FinanceSettings {
        bigint id PK
        positivebiginteger monthly_goal_cents
        texto regime
        decimal iss_pct
        texto service_description
        texto municipal_service_code
        texto municipal_service_name
        texto accountant_email
        int organization_id FK
    }
    Opportunity {
        bigint id PK
        texto title
        texto area
        texto stage
        texto source
        positivebiginteger value_cents
        texto next_action
        data next_action_at
        texto lost_reason
        int organization_id FK
        int contact_id FK
        int campaign_id FK
        int owner_id FK
        int created_by_id FK
    }
    Receivable {
        bigint id PK
        texto description
        positivebiginteger amount_cents
        data due_date
        texto status
        data paid_at
        positivebiginteger paid_cents
        texto method
        texto asaas_id
        int organization_id FK
        int agreement_id FK
        int contact_id FK
        int case_id FK
        int created_by_id FK
    }
    RecurringExpense {
        bigint id PK
        texto description
        texto category
        positivebiginteger amount_cents
        int day
        bool active
        data starts_on
        data ends_on
        texto last_month
        int organization_id FK
        int created_by_id FK
    }
    Campaign {
        int id PK "em outro diagrama"
    }
    Contact {
        int id PK "em outro diagrama"
    }
    MonitoredCase {
        int id PK "em outro diagrama"
    }
    Expense }o--o| Contact : "contact"
    Expense }o--o| MonitoredCase : "case"
    Expense |o--o| Receivable : "reimbursement"
    FeeAgreement }o--|| Contact : "contact"
    FeeAgreement }o--o| MonitoredCase : "case"
    FeeAgreement }o--o| Opportunity : "opportunity"
    Opportunity }o--|| Contact : "contact"
    Opportunity }o--o| Campaign : "campaign"
    Receivable }o--o| FeeAgreement : "agreement"
    Receivable }o--|| Contact : "contact"
    Receivable }o--o| MonitoredCase : "case"
```

<a id="20-banco-05-automacao"></a>
## Banco de dados: Automações, fluxos e e-mails

Tabelas: Action, EmailMessage, EmailTriage, ExecutionLog, MailBox, Notification, PersonalDevice, Rule, RuleRun, Trigger, WebhookTrigger, Workflow. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-05-automacao.svg`](img/20-banco-05-automacao.svg)

```mermaid
erDiagram
    PersonalDevice {
        bigint id PK
        texto name
        texto kind
        texto key_hash
        bool can_approve
        bool notify
        texto ntfy_topic
        data_hora last_used_at
        data_hora revoked_at
        int organization_id FK
        int user_id FK
    }
    Rule {
        bigint id PK
        texto name
        texto description
        bool enabled
        texto trigger
        json trigger_config
        json conditions
        json actions
        bool require_approval
        int organization_id FK
        int created_by_id FK
    }
    RuleRun {
        bigint id PK
        texto trigger
        texto status
        cifrado title
        cifrado steps
        texto dedupe_key
        data_hora decided_at
        texto decision_note
        int rule_id FK
        int organization_id FK
        int decided_by_id FK
    }
    EmailMessage {
        bigint id PK
        texto message_id
        texto subject
        texto sender
        data_hora received_at
        texto body_text
        bool is_dispatched
        int mailbox_id FK
    }
    EmailTriage {
        bigint id PK
        texto category
        texto urgency
        cifrado summary
        texto suggested_action
        data due_date
        texto method
        int email_id FK
        int organization_id FK
        int contact_id FK
    }
    MailBox {
        bigint id PK
        texto name
        texto imap_host
        int imap_port
        texto username
        data_hora last_fetch_at
        bool is_active
        int user_id FK
    }
    Notification {
        bigint id PK
        texto type
        texto title
        texto description
        texto origem
        texto documento
        texto acao
        texto detalhes
        texto action_label
        int user_id FK
        int organization_id FK
    }
    WebhookTrigger {
        bigint id PK
        uuid identifier
        int workflow_id FK
    }
    Action {
        bigint id PK
        texto action_type
        texto endpoint_url
        texto method
        json headers
        texto payload_template
        int workflow_id FK
    }
    ExecutionLog {
        bigint id PK
        texto status
        json trigger_payload
        json final_result
        texto error_message
        int execution_time_ms
        bool ai_origin
        data_hora reviewed_at
        texto review_decision
        int workflow_id FK
        int triggered_by_id FK
        int reviewed_by_id FK
    }
    Trigger {
        bigint id PK
        texto event_type
        json payload_mapping
        uuid webhook_token
        int workflow_id FK
        int connection_id FK
    }
    Workflow {
        bigint id PK
        texto name
        texto description
        bool is_active
        bool ai_generated
        data_hora approved_at
        int organization_id FK
        int approved_by_id FK
    }
    AppConnection {
        int id PK "em outro diagrama"
    }
    Contact {
        int id PK "em outro diagrama"
    }
    RuleRun }o--|| Rule : "rule"
    EmailMessage }o--|| MailBox : "mailbox"
    EmailTriage ||--|| EmailMessage : "email"
    EmailTriage }o--o| Contact : "contact"
    WebhookTrigger ||--|| Workflow : "workflow"
    Action }o--|| Workflow : "workflow"
    ExecutionLog }o--|| Workflow : "workflow"
    Trigger ||--|| Workflow : "workflow"
    Trigger }o--|| AppConnection : "connection"
```

<a id="20-banco-06-ia"></a>
## Banco de dados: IA: assistente, governança e aprendizado

Tabelas: AIActionLog, AIFeedback, AIGovernancePolicy, AIRoute, AssistantSettings, AutomationSuggestion, AutonomyLevel, AutonomyProposal, Conversation, ExtractionProfile, GlobalAISwitch, MemoryItem, Message, OfficeProfile, OfficeRule, OrgAIKey, PendingAction, PersonalToken. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-06-ia.svg`](img/20-banco-06-ia.svg)

```mermaid
erDiagram
    AIActionLog {
        bigint id PK
        uuid organization_id
        texto user_ref
        texto kind
        texto provider
        json data_categories
        int input_chars
        int duration_ms
        bool success
    }
    AIGovernancePolicy {
        bigint id PK
        bool ai_enabled
        texto autonomy_level
        json allowed_providers
        int daily_ai_request_limit
        int max_actions_per_ai_workflow
        texto updated_by
        int organization_id FK
    }
    AIRoute {
        bigint id PK
        texto activity
        json providers
        bool use_reserves
        texto updated_by
    }
    GlobalAISwitch {
        int id PK
        bool ai_enabled
        texto reason
        texto changed_by
        data_hora changed_at
    }
    AssistantSettings {
        bigint id PK
        bool case_strategy
        bool mcp_enabled
        bool use_memory
        int organization_id FK
    }
    Conversation {
        bigint id PK
        texto title
        texto mode
        int organization_id FK
        int user_id FK
        int case_id FK
        int contact_id FK
    }
    Message {
        bigint id PK
        texto role
        cifrado content
        texto provider
        json tools
        int conversation_id FK
    }
    OrgAIKey {
        bigint id PK
        texto provider
        cifrado api_key
        texto base_url
        texto model
        bool paid_account
        texto last4
        data_hora last_used_at
        int organization_id FK
        int created_by_id FK
    }
    PendingAction {
        bigint id PK
        texto tool
        cifrado arguments
        cifrado summary
        texto status
        cifrado result
        data_hora decided_at
        int conversation_id FK
        int message_id FK
    }
    PersonalToken {
        bigint id PK
        texto name
        texto prefix
        texto token_hash
        texto scope
        data_hora expires_at
        data_hora last_used_at
        int uses
        data_hora revoked_at
        int organization_id FK
        int user_id FK
    }
    AIFeedback {
        bigint id PK
        texto action_kind
        texto decision
        texto subject
        cifrado changes
        int confidence
        int organization_id FK
        int user_id FK
    }
    AutomationSuggestion {
        bigint id PK
        texto key
        texto title
        cifrado reason
        int evidence
        cifrado payload
        texto status
        data_hora decided_at
        int organization_id FK
        int rule_id FK
        int decided_by_id FK
    }
    AutonomyLevel {
        bigint id PK
        texto action_kind
        texto mode
        int organization_id FK
        int updated_by_id FK
    }
    AutonomyProposal {
        bigint id PK
        texto action_kind
        texto from_mode
        texto to_mode
        int samples
        decimal approval_rate
        texto status
        data_hora decided_at
        int organization_id FK
        int decided_by_id FK
    }
    MemoryItem {
        bigint id PK
        texto kind
        texto title
        cifrado text
        cifrado payload
        cifrado embedding
        texto source
        int organization_id FK
        int created_by_id FK
    }
    OfficeProfile {
        bigint id PK
        json areas
        texto audience
        texto city
        texto tone
        texto signature
        json social
        json auto_stats
        texto email_layout
        int organization_id FK
    }
    OfficeRule {
        bigint id PK
        texto kind
        texto field
        texto from_value
        texto to_value
        int evidence
        texto status
        data_hora decided_at
        int organization_id FK
        int decided_by_id FK
    }
    ExtractionProfile {
        bigint id PK
        texto name
        texto ai_provider
        texto system_prompt_template
        texto pydantic_schema_name
        int user_id FK
    }
    Contact {
        int id PK "em outro diagrama"
    }
    MonitoredCase {
        int id PK "em outro diagrama"
    }
    Rule {
        int id PK "em outro diagrama"
    }
    Conversation }o--o| MonitoredCase : "case"
    Conversation }o--o| Contact : "contact"
    Message }o--|| Conversation : "conversation"
    PendingAction }o--|| Conversation : "conversation"
    PendingAction }o--o| Message : "message"
    AutomationSuggestion }o--o| Rule : "rule"
```

<a id="20-banco-07-integracoes"></a>
## Banco de dados: Integrações, Google, ERP, marketing e suporte

Tabelas: AppConnection, Campaign, CaptureForm, ContentPiece, CustomizationRequest, ErpCallLog, ErpConnector, ExternalEvent, GoogleCalendarApp, GoogleCalendarLink, GoogleFile, IntegrationLog, MarketingAsset, SatisfactionSurvey, SupportAccessGrant, TaskEventMap, Ticket, TicketMessage. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-07-integracoes.svg`](img/20-banco-07-integracoes.svg)

```mermaid
erDiagram
    ErpCallLog {
        bigint id PK
        texto operation
        bool dry_run
        bool ok
        int status_code
        texto error
        int connector_id FK
        int actor_id FK
    }
    ErpConnector {
        bigint id PK
        texto name
        texto preset
        texto base_url
        cifrado credentials
        json operations
        bool live_enabled
        bool is_active
        int organization_id FK
        int created_by_id FK
    }
    ExternalEvent {
        bigint id PK
        texto event_id
        cifrado title
        cifrado description
        cifrado location
        data_hora start
        data_hora end
        bool all_day
        texto kind
        int link_id FK
        int organization_id FK
        int case_id FK
        int contact_id FK
        int task_id FK
    }
    GoogleCalendarApp {
        bigint id PK
        texto client_id
        cifrado client_secret
        bool uses_platform
        bool enabled
        bool share_details
        int event_minutes
        int organization_id FK
    }
    GoogleCalendarLink {
        bigint id PK
        cifrado refresh_token
        texto calendar_id
        texto status
        texto sync_token
        data_hora last_sync_at
        texto last_error
        data_hora connected_at
        bool import_events
        int user_id FK
        int app_id FK
    }
    GoogleFile {
        bigint id PK
        texto kind
        texto name
        texto file_id
        texto url
        data_hora used_at
        int link_id FK
    }
    TaskEventMap {
        bigint id PK
        texto event_id
        data_hora last_synced_at
        int task_id FK
        int link_id FK
    }
    AppConnection {
        bigint id PK
        texto name
        texto app_name
        cifrado credentials
        bool is_active
        int user_id FK
    }
    IntegrationLog {
        bigint id PK
        texto status
        json request_data
        int response_code
        json response_body
        texto error_message
        data_hora attempted_at
        int connection_id FK
    }
    Campaign {
        bigint id PK
        texto scope
        texto name
        texto goal
        texto audience
        json channels
        data starts_on
        data ends_on
        texto notes
        int organization_id FK
        int created_by_id FK
    }
    CaptureForm {
        bigint id PK
        texto token
        texto title
        texto intro
        json areas
        texto thank_you
        bool active
        json compliance
        int submissions
        int organization_id FK
        int campaign_id FK
        int created_by_id FK
    }
    ContentPiece {
        bigint id PK
        texto scope
        texto channel
        texto theme
        texto title
        texto body
        json hashtags
        texto image_hint
        texto image_url
        int organization_id FK
        int campaign_id FK
        int created_by_id FK
        int approved_by_id FK
    }
    MarketingAsset {
        bigint id PK
        texto scope
        texto name
        texto file
        int width
        int height
        int organization_id FK
        int created_by_id FK
    }
    SatisfactionSurvey {
        bigint id PK
        texto token
        texto reason
        int score
        cifrado comment
        data_hora expires_at
        data_hora answered_at
        int organization_id FK
        int contact_id FK
    }
    CustomizationRequest {
        bigint id PK
        texto area
        cifrado objective
        cifrado example
        texto frequency
        int users_affected
        data wanted_by
        texto stage
        cifrado proposal
        int ticket_id FK
        int approved_by_id FK
    }
    SupportAccessGrant {
        bigint id PK
        data_hora expires_at
        data_hora revoked_at
        int ticket_id FK
        int granted_by_id FK
    }
    Ticket {
        bigint id PK
        cifrado subject
        texto category
        texto priority
        texto status
        texto page_url
        data_hora first_response_at
        data_hora resolved_at
        int organization_id FK
        int opened_by_id FK
        int assigned_to_id FK
    }
    TicketMessage {
        bigint id PK
        bool from_staff
        bool internal
        cifrado body
        int ticket_id FK
        int author_id FK
    }
    Contact {
        int id PK "em outro diagrama"
    }
    MonitoredCase {
        int id PK "em outro diagrama"
    }
    UserTask {
        int id PK "em outro diagrama"
    }
    ErpCallLog }o--|| ErpConnector : "connector"
    ExternalEvent }o--|| GoogleCalendarLink : "link"
    ExternalEvent }o--o| MonitoredCase : "case"
    ExternalEvent }o--o| Contact : "contact"
    ExternalEvent }o--o| UserTask : "task"
    GoogleCalendarLink }o--|| GoogleCalendarApp : "app"
    GoogleFile }o--|| GoogleCalendarLink : "link"
    TaskEventMap ||--|| UserTask : "task"
    TaskEventMap }o--|| GoogleCalendarLink : "link"
    IntegrationLog }o--o| AppConnection : "connection"
    CaptureForm }o--o| Campaign : "campaign"
    ContentPiece }o--o| Campaign : "campaign"
    SatisfactionSurvey }o--|| Contact : "contact"
    CustomizationRequest ||--|| Ticket : "ticket"
    SupportAccessGrant }o--|| Ticket : "ticket"
    TicketMessage }o--|| Ticket : "ticket"
```

<a id="20-banco-08-seguranca"></a>
## Banco de dados: Segurança, auditoria e LGPD

Tabelas: AnomalyAlert, AuditChainHead, AuditCheckpoint, AuditEvent, BlockedIP, ComplianceSnapshot, ConsentRecord, ControlAssessment, DataSubjectRequest, LegalDocument, OrganizationOffboarding, SubprocessorEntry. Gerado dos modelos Django. Mostra a chave, os principais campos ("cifrado" = guardado cifrado) e as ligações. Ligações com `Organization` e `CustomUser` ficam só no Núcleo, para não poluir o desenho.

Imagem: [`img/20-banco-08-seguranca.svg`](img/20-banco-08-seguranca.svg)

```mermaid
erDiagram
    AnomalyAlert {
        bigint id PK
        texto rule
        texto severity
        texto status
        texto actor_id
        texto actor_label
        uuid organization_id
        ip ip
        texto summary
    }
    AuditChainHead {
        int id PK
        bigint last_seq
        texto last_hash
    }
    AuditCheckpoint {
        bigint id PK
        bigint purged_until_seq
        texto last_hash
        int purged_count
        texto reason
    }
    AuditEvent {
        bigint seq PK
        uuid uid
        data_hora occurred_at
        texto request_id
        texto actor_type
        texto actor_id
        texto actor_label
        uuid organization_id
        texto action
    }
    BlockedIP {
        bigint id PK
        texto network
        texto reason
        texto created_by
        data_hora expires_at
        int hits
        data_hora last_hit_at
    }
    ComplianceSnapshot {
        bigint id PK
        texto framework
        real score
        json counts
        json failing
    }
    ControlAssessment {
        bigint id PK
        texto framework
        texto control_id
        texto status
        texto owner
        texto evidence_url
        texto justification
        texto reviewed_by
        data_hora reviewed_at
    }
    ConsentRecord {
        bigint id PK
        texto user_ref
        uuid organization_id
        texto purpose
        texto legal_basis
        bool granted
        data_hora occurred_at
        ip ip
        texto user_agent_hash
        int user_id FK
        int document_id FK
    }
    DataSubjectRequest {
        uuid id PK
        texto user_ref
        uuid organization_id
        texto type
        texto status
        texto notes
        data_hora opened_at
        data_hora due_at
        data_hora fulfilled_at
        int user_id FK
    }
    LegalDocument {
        bigint id PK
        texto kind
        texto version
        texto title
        texto content_md
        texto content_sha256
        texto locale
        bool requires_reconsent
        bool is_current
    }
    OrganizationOffboarding {
        bigint id PK
        uuid organization_id
        texto organization_name
        texto requested_by
        data_hora requested_at
        data_hora purge_after
        texto status
        data_hora purged_at
        json summary
    }
    SubprocessorEntry {
        bigint id PK
        texto name
        texto country
        texto purpose
        json data_categories
        bool international_transfer
        texto safeguards
        texto dpa_url
        bool contract_verified
    }
    ConsentRecord }o--|| LegalDocument : "document"
```
