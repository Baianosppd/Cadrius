# Plano por equipe — o que Front-end, Design e Back-end precisam fazer

> O que **já existe no back-end** (CAD-056…071) está pronto para consumo: os contratos abaixo são reais (veja também o
> OpenAPI em `/api/docs/`). Este documento detalha o que **não foi feito agora** e quem faz.
> Equipe: Design UX/UI — **Allan**; Front-end — **Ryan**; Back-end — **Thales**; DevSecOps/Tech Lead — **Jullio**.
> Itens numerados em formato de card estão em `docs/CADS_BACKLOG.md` (CAD-072 em diante).

## 0. Regras que valem para todas as telas
1. **Idioma pt-BR**, mensagens claras (sem jargão técnico para advogados). Erros da API trazem `detail` e, quando útil, `code`.
2. **Interceptor Axios**: (a) `401` → tentar `POST /api/v1/auth/token/refresh/` uma vez, senão logout; (b) **`428 consent_required`** →
   abrir o modal de aceite (seção 1.1) e repetir o pedido; (c) **`429`** → mensagem "muitas tentativas, aguarde" respeitando `Retry-After`;
   (d) `403` → "você não tem permissão" (sem expor detalhes); (e) enviar `X-Request-ID` não é necessário — o back devolve `X-Request-ID`
   em toda resposta: **exiba-o no rodapé de qualquer tela de erro** e no Sentry (`Sentry.setTag('request_id', …)`) para suporte correlacionar.
3. **Nunca** colocar e-mail, CPF ou conteúdo de documentos em `console.log`, Sentry ou localStorage. Tokens: preferir memória + refresh; se
   usar `localStorage`, nunca logar.
4. **Acessibilidade WCAG 2.1 AA**: contraste ≥ 4,5:1, foco visível, rótulos em formulários, não depender só de cor (ícone + texto no status),
   navegação por teclado em tabelas/modais.
5. **Papéis** (`/api/v1/auth/user/` + `/api/v1/teams/members/`): `OWNER`, `ADMIN`, `MEMBER`, `VIEWER`. Esconder ações proibidas, mas **o back é quem decide** (403).
6. **Estados obrigatórios** em toda tela: carregando (skeleton), vazio (com orientação), erro (com *tentar novamente* + `request_id`), sem permissão.

---
## 1. FRONT-END (Ryan)

### 1.1 Aceite de termos (cadastro, SSO e reaceite) — CAD-091
- **Cadastro**: antes de enviar, `GET /api/v1/legal/documents/` (público). Mostrar 3 itens com link/modal de leitura e checkbox **não pré-marcado**:
  Termos de Uso (`terms`), Política de Privacidade (`privacy`), Termo de Ciência (`ciencia`). Enviar no `POST /api/v1/auth/register/` os campos
  `accepted_terms_version`, `accepted_privacy_version`, `accepted_ciencia_version` com a `version` exibida (400 se a versão estiver desatualizada → recarregar documentos).
- **Aviso de IA** (`ai_notice`): exibir banner/aviso contextual na primeira vez que o usuário abrir "Gerar automação com IA" e ao ativar perfil de extração.
- **Modal 428**: resposta `{"code":"consent_required","pending":[{"id","kind","version","title"}]}` → listar os documentos pendentes (carregar `content_md` de
  `/legal/documents/`), botão **Aceitar e continuar** que faz `POST /api/v1/legal/consents/ {"document_id": id, "granted": true}` para cada um e repete o pedido original.
  Sem "fechar" — só aceitar ou sair (logout). Renderizar Markdown sem HTML cru (sanitizar).
- **SSO (Google/Microsoft)**: o 1º acesso cai no modal 428; **não** mostrar o dashboard antes.
- **Aceite**: `needs_legal_review: true` ⇒ exibir selo "versão preliminar" **somente** em ambientes não-produtivos.

### 1.2 Privacidade e dados (usuário) — CAD-092
Rota `/configuracoes/privacidade` (todos os papéis):
| Bloco | API | Comportamento |
|---|---|---|
| Meus aceites | `GET /legal/consents/me/` | tabela documento/versão/data; revogar **opcionais** com `POST /legal/consents/ {granted:false,purpose}`; essenciais mostram "para revogar, encerre a conta" (400 `essential_document`) |
| Suboperadores | `GET /legal/subprocessors/` | tabela pública (nome, país, finalidade, transferência internacional) |
| Exportar meus dados | `GET /privacy/me/export/` | baixar JSON (`Blob`); aviso "contém dados pessoais — guarde com segurança" |
| Pedidos ao encarregado | `GET/POST /privacy/requests/` (`type`: access, correction, anonymization, portability, info_sharing, revoke_consent, deletion) | lista com **prazo** (`due_at`), selo "vencido" se `overdue`; criar com observação (≤ 2000) |
| Encerrar escritório (**OWNER**) | `POST /privacy/organization/close/ {"confirm": "<nome exato do escritório>"}` | diálogo destrutivo com digitação do nome; após 202 mostrar banner global "Encerramento agendado para {purge_after}; dados recuperáveis até lá" |
Encarregado/canal: exibir `privacidade@cadrius.ia.br` (vem do back futuramente em `/legal/documents/` — por ora constante de configuração).

### 1.3 Auditoria do escritório (OWNER/ADMIN) — CAD-093
Rota `/seguranca/auditoria`:
- **Cards** (`GET /audit/summary/`): eventos 7d, logins falhos, negados, exports, alertas abertos; gráfico de barras por ação (`by_action`).
- **Trilha** (`GET /audit/events/?action=&prefix=&outcome=&actor_id=&from=&to=&page=`): tabela paginada (50), colunas `occurred_at`, `action` (traduzir via dicionário
  `auth.login.failure → "Login com falha"`…), `actor_label` (já mascarado), `outcome` (pill), `target_type/id`, `ip`, `request_id` (copiar). Filtro por prefixo (auth, data, workflow, member, ai, consent, dsr…).
- **Exportar CSV**: `GET /audit/events/export/` (download; também fica auditado) — avisar "será registrado na trilha".
- **Alertas** (`GET /audit/alerts/?status=open`) + triagem `PATCH /audit/alerts/{id}/ {"status":"ack|resolved|false_positive"}`; severidade com cor **e** ícone; detalhes (`details`) em accordion.
- Papel `MEMBER/VIEWER` não vê o item de menu; se acessar a URL → 403 amigável.

### 1.4 IA segura, aprovações e confirmações — CAD-094
| Tela | APIs | Regras de UX |
|---|---|---|
| **Gerar automação com IA** (editor React Flow) | `POST /api/v1/ai/workflows/ {"prompt","connection_id"}` → `201` workflow com `is_active:false`, `ai_generated:true`, `awaiting_approval:true` | escolher a conexão de gatilho; mostrar o resultado como **rascunho** (faixa âmbar "Rascunho de IA — não está ativo"); erros: `403 {code: global_kill_switch\|org_disabled\|provider_not_allowed\|suggest_only\|daily_limit}` → mensagens específicas; `422 invalid_ai_output` → "a IA gerou algo inválido, reescreva o pedido" |
| **Aprovar/Rejeitar rascunho** (OWNER/ADMIN) | `POST /api/workflows/automations/{id}/approve/` · `/reject/` | pré-visualizar **gatilho + ações + URL de destino + template**; checklist "revisei o destino e as mensagens" antes de habilitar **Aprovar**; `MEMBER` vê "aguardando aprovação de um administrador" (botão ausente); `PATCH is_active:true` em rascunho retorna 400 — não oferecer toggle |
| **Fila de confirmação de execuções** (OWNER/ADMIN) | `GET /api/v1/ai/executions/pending/` · `POST /ai/executions/{id}/review/ {"decision":"approve\|reject"}` | cartões com workflow, ações (tipo/destino) e **nomes dos campos** (`payload_fields` — o conteúdo não é enviado de propósito); badge com contagem no menu; aprovar enfileira o envio |
| **Política de IA do escritório** | `GET/PATCH /api/v1/ai/policy/` (PATCH só OWNER/ADMIN) | níveis (`autonomy_choices`): **Desligada / Somente sugestões / Supervisionada (padrão) / Autonomia limitada**; ao escolher "Autonomia limitada" exibir aviso explicando que ações externas de origem IA deixam de pedir confirmação; provedores permitidos (OPENAI, GEMINI, GROQ); limite diário (≤ 10000); interruptor "IA do escritório" |
| **Atividade da IA** | `GET /api/v1/ai/activity/` (OWNER/ADMIN) | cartões 7d (usos, bloqueios, falhas, por provedor/motivo) e lista dos 50 últimos (sem conteúdo) |
- Em listas de execuções, status `PENDING_REVIEW` = "Aguardando confirmação" (nova cor/ícone).

### 1.5 Centro de Segurança (equipe — `is_staff`) — CAD-095
Hoje existe versão renderizada pelo Django em **`/security-center/`** (usar como protótipo funcional e referência de conteúdo). O React deve substituir,
consumindo `/api/v1/security/*` (staff; 403 para os demais):
| Tela | Fonte de dados | Itens |
|---|---|---|
| Visão geral | `GET /security/overview/` | 3 anéis de pontuação (ISO 27001, ISO 27701, LGPD) + geral; integridade da trilha; eventos 24h; alertas por severidade; IA (ligada/desligada); "pontos que exigem ação" (`failing_checks`) |
| Normas (3 telas iguais) | `GET /security/controls/?framework=iso27001\|iso27701\|lgpd[&status=]` | agrupar por `theme`; linha com `id`, `title`, `status` (pill), `source` (auto/manual/mixed), `evidence`, verificações (`checks[]`), avaliação manual; filtros por status; **exportar CSV** (link para `/security-center/{fw}/export.csv` até existir endpoint JSON/CSV — CAD-090) |
| Avaliação manual de controle | **precisa de API** (CAD-090) | modal: status, responsável, link de evidência, justificativa (**obrigatória** para "Não aplicável"), próxima revisão |
| Postura técnica | `GET /security/checks/` | tabela de verificações com status e detalhe |
| Trilha global / Alertas / Privacidade / IA / Kill switch | **precisam de API** (CAD-090) | ver telas HTML equivalentes para o conteúdo; **Kill switch**: botão destrutivo vermelho, exige motivo, confirmação em 2 passos, banner global enquanto desligado |
| RoPA | `GET /security/ropa/` | cartões por operação; exportar CSV |
- Tempo real: *polling* de 30–60 s no overview (sem WebSocket por enquanto).

### 1.6 Demais pendências de front que dependem do back
- **Conexões/integrações** (RF-019): tela de cofre (WhatsApp/Sheets/Webhook…) após CAD-072 (API de `AppConnection` com segredos *write-only*).
- **Cadastro completo de organização** (RF-005) e campos OAB/UF/área (RF-001) após CAD-073.
- **Upload de documentos** (RF-009) após CAD-074.
- **Sentry no front** (CAD-056, parte React): `@sentry/react`, `VITE_SENTRY_DSN`, `environment`, `release`, `Sentry.setUser({id})` e tag `organization_id` (somente IDs), `beforeSend` removendo e-mail/CPF; ErrorBoundary.
- **Variáveis**: `VITE_API_URL`, `VITE_SENTRY_DSN`, `VITE_APP_VERSION`. CSP do front: `connect-src` apenas a API e o Sentry.
- **Responsividade** (RNF-003): validar as telas novas em 360px/768px/1280px.

### 1.7 Critérios de aceite (Front)
- Nenhuma chamada autenticada ignora 428/401/429/403; teste de integração com mocks de cada status.
- Cadastro **impossível** sem os 3 aceites; versão enviada = versão exibida.
- Ações destrutivas (kill switch, encerrar escritório, rejeitar rascunho) exigem confirmação explícita.
- Lighthouse A11y ≥ 95 nas telas novas; navegação completa por teclado.

---
## 2. DESIGN (Allan)

### 2.1 Princípios (pesquisa com usuários, documento §11–12)
Azul-marinho como âncora (confiança/seriedade), fundo claro cinza/branco, **sem cores agressivas ou neon**. Em segurança, a cor de alerta (vermelho/âmbar)
deve aparecer **só onde exige ação** — se tudo é vermelho, nada é. Linguagem calma, direta, em pt-BR.

### 2.2 Tokens propostos (já usados no protótipo `/security-center/`)
| Token | Valor | Uso |
|---|---|---|
| `navy-900` / `navy-700` | `#0B2A5B` / `#123A7A` | menu, títulos, botão primário |
| `bg` / `card` / `line` | `#F3F5F9` / `#FFFFFF` / `#DDE3EC` | fundo, cartões, bordas |
| `ink` / `muted` | `#1B2433` / `#5B677A` | texto / apoio (contraste ≥ 4,5:1) |
| `ok` | texto `#1E7B4B` sobre `#E4F4EB` | implementado, íntegra, sucesso |
| `warn` | `#8A5A00` sobre `#FFF1D6` | parcial, pendente, atenção |
| `bad` | `#A4262C` sobre `#FDE7E9` | falha, crítico, adulterado, kill switch |
| `info` | `#17508F` sobre `#E3EEFB` | em análise, informação |
| `na` | `#4A5568` sobre `#ECEFF4` | não aplicável/não avaliado |
Tipografia: família do design system atual; títulos 24/18 px, corpo 14–16 px, mono (IDs/hashes) 12–13 px. Espaçamento base 4/8 px; raio de cartão 14 px.

### 2.3 Componentes novos a especificar (Figma + estados)
1. **Pill de status** (ícone + texto; 5 estados de controle + 4 de severidade + 4 de alerta). 2. **Anel de pontuação** (0–100, cor por faixa: <50 vermelho, 50–79 âmbar, ≥80 verde, rótulo central).
3. **Tabela de dados** com filtros, paginação, linha expansível ("Evidência") e *sticky header*. 4. **Linha do tempo de eventos** (ator, ação traduzida, resultado, `request_id` copiável).
5. **Cartão de aprovação** (pré-visualização gatilho → ações → destino; checklist; Aprovar/Rejeitar). 6. **Faixa "Rascunho de IA"** (âmbar) e selo "Gerado por IA" nas listas.
7. **Modal de consentimento** (documento + versão + hash curto; só Aceitar/Sair). 8. **Diálogo destrutivo com digitação** (encerrar escritório) e **confirmação em 2 passos** (kill switch).
9. **Banner global** (IA desligada pela plataforma; escritório em encerramento; cadeia de auditoria adulterada) — hierarquia: crítico > aviso > info.
10. **Seletor de nível de autonomia da IA** (4 opções com explicação e consequência em linguagem simples). 11. **Estados vazios** ("Nenhum alerta aberto ✔") e de erro com `request_id`.

### 2.4 Fluxos a desenhar (protótipo navegável)
- **Cadastro com aceite** (individual e empresa) e **reaceite** (428) — sem "dark patterns": caixas desmarcadas, texto legível, link para suboperadores.
- **Pedido do titular** (criar → acompanhar prazo → baixar dados) e **encerramento do escritório** (30 dias, desfazer).
- **IA: pedir → rascunho → revisar → aprovar/rejeitar → execução com confirmação** (incluindo a fila de confirmações).
- **Resposta a alerta** (do alerta à triagem) e **Centro de Segurança** completo (visão geral, normas, matriz com avaliação manual, kill switch).
- Microcopy revisada com o jurídico para termos sensíveis (consentimento, transferência internacional, IA).

### 2.5 Entregáveis e aceite
Biblioteca no Figma (componentes + variantes + estados), 12 telas em alta fidelidade (desktop e mobile), protótipo dos 4 fluxos, tokens exportados (JSON) e checagem de
contraste/foco documentada. Aceite: revisão com Ryan (viabilidade) e teste de usabilidade rápido com 5 advogados nas telas de aprovação de IA e de privacidade.

---
## 3. BACK-END (Thales)
Pendências do back (detalhe e critérios em `docs/CADS_BACKLOG.md`), em ordem de prioridade:
1. **CAD-075 (crítico)** despachar e-mails novos para os workflows (`process_email` nunca é agendado) + reprocessar logs `PENDING` órfãos.
2. **CAD-072** API de conexões (cofre) com segredos *write-only*. 3. **CAD-073** API de organização + cadastro completo (OAB/UF/área).
4. **CAD-090** endpoints de **escrita** do Centro de Segurança (avaliar controle, kill switch, triagem de alerta, verificar cadeia, trilha global) + "atividade da conta".
5. **CAD-077** avaliação de gatilhos (condições) e *data mapper*. 6. **CAD-076** deduplicação. 7. **CAD-079** HMAC em webhooks. 8. **CAD-080** e-mail transacional + `EmailLog`.
9. **CAD-074** upload e extração de PDF/imagem. 10. **CAD-081** ação "criar tarefa". 11. **CAD-082** medição de desempenho. 12. Limpeza de dívida (**CAD-086/087/088**).
Regras: todo endpoint novo (a) isola por escritório (`TenantQuerysetMixin`), (b) usa `OrgRolePermission`/`IsOrgManager`, (c) registra evento em `audit.service.log`,
(d) valida entrada (inclusive URLs → `integrations.ssrf`), (e) tem teste de vazamento entre escritórios, (f) entra em `compliance/ropa.py` se tratar dado pessoal novo.

## 4. DEVSECOPS (Jullio) — o que fica
Rotacionar segredos e limpar histórico (⛔), criar secrets do deploy (`docs/AUDITORIA_SEGURANCA.md` §4), validar TLS/compose em *staging*,
MFA/admin (CAD-083), socket-proxy (CAD-085), monitoramento externo e teste de restauração trimestral (CAD-089), nomear encarregado e fechar DPAs (jurídico).
