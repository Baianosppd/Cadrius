# Conferência front-end × back-end (rotas e contratos)

Gerada em 2026-10-02 comparando as chamadas de `src/` do repositório `cadrius---front-end` (branch `main`, `aad3b0f`) com as rotas reais do Django (`api/v1/…`).
O front usa `baseURL = VITE_API_URL` (`…/api/v1/`).

## ✅ Funcionam (rota existe)
`auth/token/`, `auth/token/refresh/`, `auth/user/`, `auth/profile/` (PATCH), `dashboard/stats/`, `automations/stats/`, `tasks/` (+`{id}/`), `teams/members/`, `teams/permission-groups/`,
`mailboxes/`, `extraction-profiles/`, `emails/`, `api/billing/plans/` (URL absoluta, ignora o `baseURL`).

## ❌ Quebram em teste (o front chama algo que o back não tem)

| # | Front chama | Situação no back | Correção sugerida | Dono |
|---|---|---|---|---|
| 1 | `POST auth/register/` com `{email, password, first_name, cpf, oab_number…}` (`RegisterIndividual.jsx`, `Register.jsx`) | Contrato novo (main): `{nome_completo, cpf, email, senha, plano_id, oab_numero, oab_uf, area_atuacao}` **+ aceite LGPD** `accepted_terms_version`, `accepted_privacy_version`, `accepted_ciencia_version` (versões de `GET /api/v1/legal/documents/`) | Ajustar o payload do front; buscar os documentos vigentes e exibir os checkboxes (CAD-091) | Ryan |
| 2 | Cadastro de empresa (`RegisterEmpresa.jsx`) não chama API | `POST auth/register/empresa/` existe | Conectar o formulário (mesmo aceite LGPD) | Ryan |
| 3 | `GET auth/google/` e `auth/microsoft/` + rota `/google/callback?access=&refresh=` | **Não existem** | CAD-105: fluxo OAuth que termina redirecionando ao front com tokens (preferir *fragment/POST*, não *query string*) e exige aceite de termos | Thales |
| 4 | `POST /api/workflows/generate/` (`AIAssistant.jsx`) | Com a barra inicial o axios gera `/api/v1/api/workflows/generate/` (404). Rota certa: `POST workflows/generate-from-prompt/` | Trocar a URL | Ryan |
| 5 | `POST /ai/flow-assistant/` (`FlowAIChat.jsx`) | Não existe | Usar `workflows/generate-from-prompt/` ou criar o endpoint (passa por `aigov.run_guarded`) | Thales/Ryan |
| 6 | `POST/GET /automacoes/fluxos/` (`FlowEditor.jsx`) | Não existe; correto é `workflows/` com `{trigger, actions[]}` (ver `ROTAS_PARA_O_BACKEND.md` §6) | Definir o contrato nós↔workflow (CAD-077) | Ambos |
| 7 | `POST automation-rules/` (`NewAutomationModal.jsx`) | Não existe (legado) | Migrar para `workflows/` | Ryan |
| 8 | `POST integration-configs/` (`CredentialModal.jsx`) | Não existe (as conexões são `AppConnection`) | Criar `connections/` (CRUD com credenciais cifradas) ou remover o modal | Thales |
| 9 | `POST emails/{id}/reprocess/` (`Processos.jsx`) | Não existe | Criar a ação ou ocultar o botão | Thales |
| 10 | Telas de segurança/privacidade/IA/auditoria | API existe (`security/*`, `audit/*`, `legal/*`, `privacy/*`, `ai/*`), sem tela no React | CAD-091…095 | Ryan |

## ⚠️ Atenção no deploy
* `Dockerfile` do front roda `npm start` (servidor de desenvolvimento) e `.env` versionado aponta para `127.0.0.1`. Em servidor use `deploy/frontend/Dockerfile` (build estático + nginx) com `VITE_API_URL` por ambiente (CAD-106) e **remova `.env` do git**.
* Rotas com barra inicial (`/auth/user/`) funcionam porque o axios junta com o `baseURL`; as que começam com `/api/…` não (itens 4).
* O login por e-mail/senha (`auth/token/`) funciona hoje; só o login social está pendente.
