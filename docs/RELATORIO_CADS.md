# Relatório de CADs — entregues, parciais, pendentes e fora do escopo do plano (2026-10-05)

**Documento principal de referência:** `docs/PLANO_EVOLUCAO_PRODUTO.md` §12 (CAD-150 … CAD-196), complementado por
`docs/CADS_BACKLOG.md` (CAD-056 … CAD-140). Status levantado no **código e no histórico do git** (back `Baianosppd/Cadrius` e
front `Baianosppd/Cadrius---Front-end`), não só nos documentos.

Legenda: ✅ entregue · 🟡 parcial · ⏳ pendente · ⛔ depende de ação manual/externa · 🔀 entregue **sob outro número de branch**

> ⚠️ **Colisão de numeração (ação necessária):** as branches `CAD-160` … `CAD-175` foram usadas para entregas diferentes do que o
> §12 do plano define com os mesmos números (ex.: no plano `CAD-170` = "Hub de fontes jurídicas"; no git `CAD-170` = kit de deploy +
> TI cria contas + Fiscal fase 1). A seção 3 traz a tabela de correspondência. **Sugestão:** manter os números do git para o que já foi
> entregue (estão em PRs e commits) e **renumerar no plano** os cards do §12 ainda não entregues a partir de **CAD-200**.

---

## 1. Plano de evolução (§12) — situação de cada card

### Fase 0 — Pronto para uso real
| Card do plano | O que pede | Situação | Onde foi entregue |
|---|---|---|---|
| CAD-119 | Plano pago só após o pagamento | ✅ | git `CAD-119` |
| CAD-121 | 503 quando o Redis cair | ✅ | git `CAD-121` |
| CAD-115 | Recuperação de senha por e-mail | ✅ | git `CAD-115` (back e front) |
| CAD-105 | SSO Google/Microsoft | ✅ | git `CAD-105` (authorization code + PKCE) |
| CAD-150 | Cadastro preserva rascunho | ✅ | front `CAD-150` |
| CAD-151 | Backups offsite + chave GPG + restore | ✅ / ⛔ | git `CAD-151` (Supabase); execução e teste de restauração no servidor são manuais |
| CAD-155 | E-mail transacional + alertas | ✅ / ⛔ | git `CAD-155` e `CAD-161` (presets Gmail/Brevo/SES/Locaweb); SPF/DKIM/DMARC no DNS é manual |

### Fase 1 — Dados protegidos
| CAD-152 | Criptografia de PII com índice cego e de tokens | ✅ | git `CAD-152` |
| CAD-153 | Arquivos cifrados + antivírus | 🟡 | 🔀 arquivos cifrados em git `CAD-163/164`; antivírus ClamAV **opcional** (`CLAMAV_HOST` vazio = etapa pulada) |
| CAD-154 | Check `pii_encrypted`, rotação de chave, RoPA/RIPD | 🟡 | check e rotação existem (`compliance/checks.py`, `docs/CHAVES_CRIPTOGRAFIA.md`); RIPD preenchido depende do jurídico (⛔) |

### Fase 2 — Documentos e agenda
| CAD-160 | Pipeline de documentos assíncrono | ✅ | 🔀 git `CAD-163/164` |
| CAD-161 | OCR em worker dedicado | 🟡 | etapa de OCR prevista no pipeline (`ocr_available()`), mas **sem** ocrmypdf/Tesseract instalado: escaneado sem texto é explicado ao usuário |
| CAD-162 | Classificação + extração por tipo com confiança | ✅ | 🔀 git `CAD-163/164` (+ leitura local do motor, git `CAD-165`) |
| CAD-163 | Tela de revisão de extração | ✅ | git `CAD-163` (back e front) |
| CAD-164 | Prazos extraídos → tarefa provisória | ✅ | git `CAD-163/164`; contagem com feriados e recesso em git `CAD-172` (agenda forense) |
| CAD-165 | Google Calendar: OAuth e tokens cifrados | ✅ | 🔀 git `CAD-162` / `CAD-145` — **app OAuth por escritório** (decisão do Jullio) |
| CAD-166 | Sincronização tarefa ↔ evento | ✅ | 🔀 git `CAD-162` |
| CAD-167 | Tela de conexão do calendário | ✅ | 🔀 front `GoogleCalendarCard` |
| CAD-168 | Lembretes de prazo D-5/D-2/D-0 e escalonamento | 🟡 | 🔀 gatilho "Prazo chegando" (N dias úteis) e modelos de automação em git `CAD-172`; não há escalonamento automático D-5/D-2/D-0 fixo |

### Fase 3 — Pesquisa e monitoramento
| CAD-170 | Hub de fontes (Provider, cache, rate limit, auditoria) | 🟡 | 🔀 providers separados: DataJud (`research/`, git `CAD-166`) e DJEN (`publications/providers/`, git `CAD-173`); falta a interface única do hub |
| CAD-171 | Provider DataJud | ✅ | 🔀 git `CAD-166` |
| CAD-172 | Provider DJEN + fila de publicações | ✅ | 🔀 git `CAD-173` (fase D, com triagem por IA) |
| CAD-173 | Notícias RSS + legislação (LexML) | 🟡 | 🔀 clipping de notícias em git `CAD-166`; **LexML não feito**; notícias sem tela própria no app (só configuração na Gestão) |
| CAD-174 | Busca unificada (Ctrl+K) + pesquisa de jurisprudência | ⏳ | — (só existe a busca de documentos por nome/cliente) |
| CAD-175 | Jusbrasil sob contrato | ⏳ / ⛔ | depende de contrato; análise crítica em git `CAD-156/157` |
| CAD-176 | Telas Processos, Publicações, Notícias, Pesquisa | 🟡 | Processos acompanhados e Publicações ✅ (git `CAD-172/173`); Notícias e Pesquisa ⏳ |

### Fase 4 — IA que aprende
| CAD-180 | Matriz de autonomia R0–R4 | ✅ | 🔀 git `CAD-165` |
| CAD-181 | Central de aprovações (desfazer 24 h) | ✅ | 🔀 git `CAD-165` (modo `auto_undo`) + front |
| CAD-182 | `ai_feedback` e métricas | ✅ | 🔀 git `CAD-165`; painel de aprendizado em git `CAD-174` |
| CAD-183 | pgvector + memória (RAG por escritório) | 🟡 | memória por escritório ✅ (embeddings por hashing, cifrados); **pgvector só preparado** (script em git `CAD-159`, staging), ainda não usado |
| CAD-184 | Regras aprendidas aprovadas pelo advogado | ✅ | 🔀 git `CAD-165` + vocabulário do escritório em git `CAD-174` |
| CAD-185 | Promoção/rebaixamento de autonomia | ✅ | 🔀 git `CAD-165` |
| CAD-186 | Geração de peças com modelos + citações | ✅ | 🔀 git `CAD-173` (Minutas) + aprendizado de estilo em `CAD-174` |
| CAD-187 | Triagem de entrada (e-mail/WhatsApp/upload) | 🟡 | upload (leitura de documentos) e publicações ✅; triagem de e-mail/WhatsApp ⏳ |
| CAD-188 | Golden sets + painel de qualidade da IA | 🟡 | painel de aprendizado (taxas por tipo) ✅ em `CAD-174`; golden sets ⏳ |

### Fase 5 — ERPs e centralização
| CAD-190 | Framework de conectores declarativos | ✅ | 🔀 git `CAD-167` (`erp/`) + ação "Chamar o ERP" nas automações (`CAD-172`) |
| CAD-191 | Tela "Parametrizar conexão" | 🟡 | API pronta; **sem tela própria no front** (o conector é usado pela ação de automação) |
| CAD-192 | Conector Astrea | ⛔ | Astrea **não tem API pública** (pesquisa da fase E): substituído por exportar planilha + "Importar dados" (`CAD-171`) |
| CAD-193 | Conector Projuris | 🟡 / ⛔ | modelo Projuris no conector (git `CAD-167`); validar API/parceria com o fornecedor |
| CAD-194 | Módulo Processos + clientes/partes cifrados | ✅ | 🔀 contatos cifrados (`CAD-171`), cliente do processo (`CAD-172`), carteira (`CAD-175`) |
| CAD-195 | Financeiro/honorários | ✅ | 🔀 git `CAD-175` (contratos, a receber, despesas, Asaas, régua de cobrança) |
| CAD-196 | Assinatura eletrônica | ✅ | 🔀 ZapSign em git `CAD-174` |

---

## 2. Backlog anterior (`docs/CADS_BACKLOG.md`) — situação

| Card | Situação | Observação |
|---|---|---|
| CAD-056 … 071, 104, 110 | ✅ | já marcados como entregues no backlog |
| CAD-072 API de conexões | ✅ | 🔀 entregue como `CAD-110` |
| CAD-073 API de Organização | 🟡 | cadastro de escritório com CNPJ existe; endpoint `GET/PATCH /organization/` dedicado não encontrado |
| CAD-074 Upload e extração | ✅ | 🔀 git `CAD-163/164` |
| CAD-075 Despacho de e-mails para workflows | ⏳ | `is_dispatched` existe; vínculo caixa → perfil → workflow e reprocessamento não encontrados |
| CAD-076 Deduplicação de disparos (60 s) | 🟡 | deduplicação existe nas automações internas, publicações e notificações; **não** nos workflows de webhook |
| CAD-077 Condições + Data Mapper | 🟡 | `payload_mapping` existe nos workflows; condições completas existem nas automações internas (`CAD-172`) |
| CAD-078 Templates de workflows | ✅ | 🔀 modelos prontos de automação (`CAD-172`, `CAD-174`, `CAD-175`) |
| CAD-079 HMAC em webhooks | ⏳ | não encontrado `X-Cadrius-Signature` nos webhooks |
| CAD-080 E-mail transacional e `EmailLog` | 🟡 | SMTP por escritório ✅ (`CAD-174`); `EmailLog` com bounce ⏳ |
| CAD-081 Ação "Criar tarefa" | ✅ | 🔀 ação `create_task` das automações (`CAD-172`) |
| CAD-082 p95 < 200 ms / teste de carga | ⏳ | — |
| CAD-083 MFA + endurecimento do Admin | ✅ / 🟡 | MFA TOTP ✅ (git `CAD-169`); allowlist de IP do `/admin/` no Traefik ⛔ manual |
| CAD-084 Verificação de e-mail | ⏳ | `ACCOUNT_EMAIL_VERIFICATION = 'none'` |
| CAD-085 / 107 `docker-socket-proxy` | ⏳ / ⛔ | só documentado |
| CAD-086 Dívida técnica | ⏳ | `integrations/telegram.py` e `billing/middleware.py` continuam no código |
| CAD-087 Cota de IA unificada | 🟡 | créditos (`billing/credits.py`) e `run_guarded` cobrem a IA nova; o fluxo antigo de workflows ainda usa `QUOTA_EXCEEDED` próprio |
| CAD-088 Cifrar `ExecutionLog` | ⏳ | `trigger_payload`/`final_result` ainda são `JSONField` simples |
| CAD-089 Monitoramento externo e restauração trimestral | 🟡 / ⛔ | `/readyz/` existe; uptime externo e teste trimestral são manuais |
| CAD-090 API de escrita do Centro de Segurança e sessões | 🟡 | Centro de Segurança e auditoria existem; listar/encerrar sessões (`/auth/sessions/`) não encontrado |
| CAD-091 … 095 telas LGPD/IA/Auditoria/Segurança (front) | ✅ | front (`CAD-109` e seguintes) |
| CAD-096 Sentry no React | ✅ | front `services/monitoring.js` |
| CAD-097 … 099 Design (Allan) | ⏳ | padronização visual feita no front (`CAD-174`), mas o design system e o teste com 5 advogados não |
| CAD-100 Saneamento do histórico do git | ⛔ | manual |
| CAD-101 Jurídico/Governança (DPO, DPAs, RIPD) | ⛔ | jurídico |
| CAD-103 Contrato OpenAPI completo | ⏳ | só documentado |
| CAD-106 Dockerfile do front | ✅ | front `CAD-106` |
| CAD-108 Alinhar front e back | ✅ | git `CAD-108` + entregas seguintes |
| CAD-116 Assistente de tarefas por IA | 🟡 | componente `AIAssistant` existe; decidir manter ou remover |
| CAD-118 Refresh em cookie HttpOnly + CSRF | ⏳ | — |
| CAD-122 Documentos: excluir/editar/antivírus | 🟡 | antivírus opcional; demais itens a conferir |
| CAD-135 Executores SMS/Drive/Slack | ⏳ | — |
| CAD-140 Staging isolado | 🟡 | ambiente de teste existe (`app-teste`); basic auth/e-mail capturado a conferir |

---

## 3. Fora do escopo do documento principal (entregas que o plano não descreve com esse número)

| Branch / CAD no git | O que foi entregue | Relação com o plano |
|---|---|---|
| `CAD-142`, `143`, `144` | Correções de deploy: chave SSH com CRLF, smoke-test com 428 | operacional, fora do plano |
| `CAD-145` | Plano de evolução + decisão do Calendar por escritório | documento |
| `CAD-156`, `157` | Análise de preços/créditos e análise crítica do Jusbrasil | documento (apoio ao CAD-119/175 do plano) |
| `CAD-158` | Arquitetura do motor de IA local + 3 provedores | documento (apoio à fase 4) |
| `CAD-159` | pgvector: troca controlada da imagem do Postgres (staging) | apoio ao CAD-183 do plano |
| `CAD-160` | Área administrativa do financeiro da Cadrius (preços, pacotes, promoções) | **novo** (não existe no §12 com esse número) |
| `CAD-161` | Presets de provedor de e-mail | apoio ao CAD-155 |
| `CAD-162` | Google Calendar por escritório | = CAD-165/166 do plano |
| `CAD-163/164` | Leitura de documentos com revisão humana e arquivos cifrados | = CAD-160/162/163/164 e parte do 153 do plano |
| `CAD-165` | Motor Cadrius (memória, feedback, regras, autonomia) | = CAD-180…185 do plano |
| `CAD-166` | DataJud + clipping de notícias | = CAD-171 e parte do 173 do plano |
| `CAD-167` | Conector declarativo de ERP (modelo Projuris) | = CAD-190/193 do plano |
| `CAD-168` | **Gestão Cadrius** (área interna de TI e Financeiro) | **novo** |
| `CAD-169` | MFA (TOTP) obrigatório para a equipe + contas de validação | = CAD-083 do backlog |
| `CAD-170` | Kit de deploy que se atualiza, TI cria contas da equipe, **Fiscal fase 1** | **novo** (no plano, CAD-170 = hub de fontes) |
| `CAD-171` (fase B) | Contatos (CRM) cifrados, Importar dados, **Suporte com acesso assistido** | parte do CAD-194; Suporte e Importação são **novos** |
| `CAD-172` (fase C) | Automações internas com simulação e aprovação, **agenda forense**, cliente do processo | parte do CAD-168/164; automações internas e agenda forense são **novas** |
| `CAD-173` (fase D) | Caixa de publicações do DJEN com triagem + **Minutas** | = CAD-172 e CAD-186 do plano |
| `CAD-174` (fase E) | **Marketing** (escritório e Cadrius), catálogo de integrações (SMTP, ZapSign, Asaas, Meta), IA que sugere automações, perfil e vocabulário do escritório, **login Produção/Teste**, revisão visual e mobile | parte do CAD-196/184/188; Marketing, login Produção/Teste e revisão do front são **novos** |
| `CAD-175` (fase F) | **Carteira de clientes** (funil, contratos), **Finanças do escritório**, **Portal do cliente**, **Fiscal fases 2–3** (NFS-e e obrigações) | = CAD-195 e parte do 194; funil, portal e Fiscal 2–3 são **novos** |
| front `CAD-109`, `111`, `112`, `113` | Telas de segurança/LGPD e ajustes do front | cards do `docs/PLANO_FRONT_END.md` (repositório do front) |

Itens **novos** a registrar no plano (não existem lá): área administrativa do financeiro, Gestão Cadrius (TI, Financeiro, Fiscal,
Suporte, Marketing), Fiscal fases 1–3, Suporte com acesso assistido, Importar dados, automações internas e agenda forense, Marketing
jurídico com verificador da OAB, login Produção/Teste, funil de captação, portal do cliente.

---

## 4. Pendentes — sugestão de renumeração para atualizar o plano

| Novo nº sugerido | Pendência (origem) |
|---|---|
| CAD-200 | Hub único de fontes jurídicas (plano CAD-170) |
| CAD-201 | Legislação LexML + tela de Notícias (plano CAD-173/176) |
| CAD-202 | Busca unificada Ctrl+K + pesquisa de jurisprudência (plano CAD-174) |
| CAD-203 | Jusbrasil sob contrato (plano CAD-175) ⛔ |
| CAD-204 | OCR real com ocrmypdf/Tesseract em worker (plano CAD-161) |
| CAD-205 | Antivírus obrigatório em produção (plano CAD-153 / backlog CAD-122) |
| CAD-206 | pgvector em uso na memória (plano CAD-183) |
| CAD-207 | Triagem de e-mail/WhatsApp (plano CAD-187) |
| CAD-208 | Golden sets da IA (plano CAD-188) |
| CAD-209 | Tela "Parametrizar conexão" do ERP (plano CAD-191) |
| CAD-210 | Escalonamento de lembretes D-5/D-2/D-0 (plano CAD-168) |
| CAD-211 | HMAC nos webhooks + deduplicação nos workflows (backlog CAD-079/076) |
| CAD-212 | Despacho de e-mails para workflows + reprocessamento (backlog CAD-075) |
| CAD-213 | `EmailLog` com bounce + verificação de e-mail (backlog CAD-080/084) |
| CAD-214 | Cifrar `ExecutionLog` + cota única de IA + dívida técnica (backlog CAD-088/087/086) |
| CAD-215 | Sessões ativas e refresh em cookie HttpOnly (backlog CAD-090/118) |
| CAD-216 | OpenAPI completo + p95/carga (backlog CAD-103/082) |
| CAD-217 | API de Organização dedicada (backlog CAD-073) |
| CAD-218 | Validações externas da fase F: Focus NFe em homologação, prazos do contador, webhook Asaas ⛔ |
| — | Manuais/externos que continuam: CAD-085/107 (socket-proxy), CAD-089, CAD-097…099 (design), CAD-100 (histórico do git), CAD-101 (jurídico) |
