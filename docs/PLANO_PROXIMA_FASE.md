# Próxima fase — Cadrius como centro do escritório (CAD-170+)

Base: tudo do `PLANO_EVOLUCAO_PRODUTO.md` que já está em produção (cobrança, SSO, PII cifrado, Gestão TI/Financeiro, MFA, documentos,
IA local, pesquisa DataJud, conector de ERP). Itens marcados **[VALIDAR]** dependem de documentação/contrato de terceiros não verificados.

---

## 1. Pesquisa: o que os ERPs jurídicos oferecem (e o que falta no Cadrius)

Fontes: comparativos 2026 (Astrea, ADVBOX, Projuris ADV, EasyJur, CPJ, Legal One) — ver links no fim.

| Funcionalidade | Mercado (quem destaca) | Cadrius hoje | Prioridade |
|---|---|---|---|
| **Captura de publicações e intimações** (diários, DJEN, sistemas dos tribunais) | todos; EasyJur/Projuris em "centenas de tribunais" | só andamentos via DataJud por nº CNJ | **P1** |
| **Monitoramento de processos** e aviso por e-mail/WhatsApp/app | ADVBOX ("caça" movimentações), Astrea (push) | DataJud + notificação interna | P1 (ampliar canais) |
| **Prazos** com feriados forenses, recesso e cálculo automático | Projuris, Legal One | tarefas + Google Calendar, sem calendário forense | **P1** |
| **Carteira de clientes / CRM jurídico** (cliente, partes, contatos, funil de captação, contrato de honorários) | ADVBOX (CRM + negociação de honorários), Astrea | só `ClientDocument.nome_cliente` | **P1** |
| **Controladoria jurídica** (distribuição de tarefas, produção por advogado, SLA interno, kanban) | ADVBOX, Astrea (kanban) | tarefas simples | P2 |
| **Financeiro do escritório**: honorários à vista/parcelados/recorrentes, boleto/PIX/cartão, régua de cobrança, custas por processo, margem | ADVBOX, Astrea, EasyJur (conta digital PJ) | não (só o financeiro do próprio Cadrius) | P2 |
| **Timesheet** e faturamento por hora | Legal One, Astrea | não | P3 |
| **Portal / app do cliente** (acompanhar processo, andamentos "traduzidos" por IA, WhatsApp) | Astrea | não | P2 |
| **Modelos de documentos** e geração de peças | Astrea, Projuris | extração sim, geração não | P2 |
| **Assinatura eletrônica** | via integrações (Clicksign/D4Sign/ZapSign) | não | P3 |
| **BI / relatórios** de produtividade e financeiro | Legal One, Projuris | dashboard básico | P3 |
| **Notas fiscais e conta digital** | EasyJur, Legal One Advanced | não | P3 (ver §6) |
| **IA generativa** (triagem de publicações, prazos, resumo) | Legal One (2026), Astrea | extração + motor que aprende + aprovação humana | diferencial |

**Leitura crítica:** o mercado vende *captura + prazos + financeiro*. O diferencial do Cadrius continua sendo **IA que aprende com o
escritório com o advogado no controle** (autonomia R1–R4). O caminho é cobrir o básico que o cliente espera (P1) e usar a IA em
cima disso (triagem de publicações, prazos sugeridos, automações recomendadas), não competir em "número de tribunais".

---

## 2. Automações que funcionam de verdade (P1)

Hoje: gatilho externo (webhook/mensagem) → ações webhook, WhatsApp (Evolution) e e-mail. Falta o que o escritório mais usa:

1. **Gatilhos internos:** documento lido/confirmado, prazo criado ou vencendo (D-3, D-1), andamento novo (DataJud), publicação nova
   (DJEN), cliente cadastrado, tarefa concluída, horário (todo dia 8h, toda segunda).
2. **Ações internas:** criar tarefa/prazo, notificar pessoa da equipe, atualizar campo do cliente/processo, gerar documento a partir de
   modelo, chamar o conector de ERP (com confirmação), enviar WhatsApp/e-mail para **contato do quadro** (§4).
3. **Condições** simples (se tipo de documento = intimação; se valor > X) e **variáveis** vindas do gatilho (`{{processo.cnj}}`).
4. **Simular antes de ativar** (dry-run com dados reais, sem enviar nada) e histórico por execução com motivo da falha.
5. **Modelos prontos** ("intimação lida → prazo + aviso ao responsável", "andamento novo → WhatsApp ao cliente com resumo aprovado").
6. Tudo passa pela matriz de autonomia: envio externo = R3 (aprovação, ou automático só com modelo pré-aprovado).

**Entregue na fase C (CAD-172)** — app `automations` (`/api/v1/automations/`, tela Automações → abas Regras/Aprovações/Histórico):
- Gatilhos: documento confirmado, andamento novo (DataJud), prazo chegando (N dias úteis antes), contato cadastrado à mão, agenda
  (diária/semanal). Ações: criar tarefa (data em dias úteis ou antes do prazo), avisar a equipe, WhatsApp/e-mail ao contato, ERP.
- Regra nasce desligada e só liga depois de **simulada** com a configuração exata (usa o evento real mais recente ou um exemplo).
  Mudou a lógica de uma regra ligada → ela desliga até simular de novo.
- Envio para fora espera **aprovação** (dono/admin/advogado) por padrão; ERP sempre. Consentimento do canal é conferido no plano e
  de novo na hora do envio; aprovação expira em 7 dias; limite de 200 execuções/24 h por regra (passou → pausa e avisa).
- A fila só carrega ids (dados pessoais lidos no worker); passos e títulos das execuções ficam cifrados; cada evento roda 1 vez por regra.
- `automations_tick` (a cada 15 min, em `setup_security_schedules`): prazos chegando, agenda e expiração de aprovações.
- Processo acompanhado ganhou **cliente** (contato do quadro) — é o destinatário de "andamento novo → WhatsApp ao cliente".
- Ainda não: publicação nova (DJEN, fase D), tarefa concluída, atualizar campo, gerar documento de modelo, e-mail pelo Gmail do escritório
  (hoje sai pelo remetente do Cadrius).

## 3. IA que aprende o escritório e recomenda automações (P1→P2)

- **Sinais já coletados:** decisões na Central de Aprovações, correções de extração, regras aprendidas, autonomia por tipo de ação.
- **Novo:** registrar *ações manuais repetidas* (ex.: toda intimação vira tarefa para a mesma pessoa em 5 dias) e, ao atingir
  N ocorrências com padrão estável, **sugerir a automação pronta** na Central ("Você fez isto 12 vezes; quer automatizar?") —
  o advogado aceita, ajusta ou recusa (recusa vira sinal negativo).
- Perfil do escritório (áreas de atuação, tribunais, clientes recorrentes, tom de comunicação) alimentando os prompts, isolado por
  escritório, sem treinar modelo de terceiros (memória local + exemplos aprovados, como já é feito).
- Métricas por escritório: taxa de aceite das sugestões, erros desfeitos, tempo economizado.

## 4. Quadro de contatos (CRM) para automações (P1)

Entidade **Contato** (cliente PF/PJ, parte contrária, testemunha, perito, correspondente, fornecedor) com dados **cifrados** (mesmo
padrão do CPF), canais (WhatsApp, e-mail), etiquetas, vínculo com processos e documentos, **consentimento/opt-out por canal (LGPD)**,
histórico de mensagens. Vira o destinatário das automações e a base da **carteira de clientes** (contratos de honorários, status
do relacionamento, funil de captação na fase P2). Importável por planilha (§7).

## 5. Documentos: extração e onde usar

Já existe: leitura (OCR opcional), extração com IA ou local, revisão humana, prazos sugeridos, arquivo cifrado. Usos a ligar:
- **Cadastro automático** de cliente/contato e processo a partir de procuração, contrato, petição inicial.
- **Prazos e tarefas** a partir de intimações (já sugere; ligar à agenda forense §8).
- **Gatilho de automação** (documento de tipo X → fluxo Y).
- **Minutas**: notificação extrajudicial, petição de juntada, resposta ao cliente — geradas sobre o documento e o modelo do escritório,
  sempre como rascunho (R1) e com citação do trecho de origem.
- **Checagem**: cláusulas de risco em contratos, valores e datas divergentes entre documentos.
- **Busca semântica** no acervo do escritório (memória já existente).

## 6. Intimações, publicações e "criar intimação" (P1)

- **Caixa de publicações** via **DJEN** (comunicações processuais por OAB/nome do advogado) **[VALIDAR API e termos de uso do CNJ]**;
  triagem por IA (tipo, prazo provável, processo vinculado) → advogado confirma → prazo + tarefa.
**Entregue na fase D (CAD-173)** — app `publications` (`/api/v1/publications/`, tela Publicações) e app `minutas`
(`/api/v1/minutas/`, tela Minutas):
- OABs do escritório acompanhadas no DJEN (API pública Comunica do CNJ, `publications_poll` a cada 3 h; 1ª consulta busca 7 dias,
  as seguintes 3 dias; o id da comunicação evita duplicar). **[VALIDAR]** formato das datas e nomes dos campos no Swagger oficial
  antes de produção; termos de uso/limite de requisições (`x-ratelimit-*`).
- Triagem: leitura local (ato, "prazo de N (N) dias", audiência; sem prazo escrito, o prazo legal típico do CPC com confiança baixa) +
  IA quando a política permitir (texto mascarado, `aigov` kind `triage`, 0 crédito). Vencimento sugerido em dias úteis pela agenda
  forense a partir da publicação (DJe). Teor e partes cifrados.
- Advogado confirma (ajusta prazo/vencimento, acompanha o processo) → tarefa "Prazo: …" na agenda + aprendizado (`AIFeedback`);
  descartar/reabrir; processo acompanhado é vinculado pelo nº CNJ (cliente aparece na caixa).
- Gatilho de automação **Publicação nova** (+ modelo "prazo fatal → preparar a peça 2 dias úteis antes").
- Minutas: 4 modelos do Cadrius (comunicado ao cliente, juntada, ciência/cumprimento, notificação extrajudicial) + modelos do
  escritório; variáveis da publicação/documento; o que falta vira `[COMPLETAR: …]` (não marca como revisada enquanto houver);
  IA opcional (15 créditos, texto mascarado) só fica com citações que existem literalmente na fonte; exporta .docx.
- Ainda não: Domicílio Judicial Eletrônico, busca de processos por parte/OAB fora do DJEN, protocolo de peças.

- **Domicílio Judicial Eletrônico** (citações de PJ) — API REST com credencial do escritório **[VALIDAR]**.
- **Busca de processos em aberto:** DataJud aceita busca por número; busca por parte/OAB não é garantida na API pública
  **[VALIDAR]** → combinar: importar a lista do escritório (planilha/ERP), DJEN por OAB e cadastro pelo nº CNJ.
- **"Criar intimação/notificação"**: gerar a **minuta** (notificação extrajudicial, petição de intimação) a partir do documento e do
  contato, com aprovação do advogado. **Protocolar no tribunal é R4** (sempre humano); não há API pública geral de peticionamento —
  o Cadrius entrega o PDF/minuta e um checklist de protocolo.

## 7. Importação de dados (P1)

Área "Importar dados": **CSV/XLSX** (depois Google Sheets e exportações de outros ERPs) → o sistema lê o cabeçalho, a IA **sugere o
mapeamento de colunas** (nome, CPF, telefone, nº do processo…), o usuário confirma, **simulação** mostra o que será criado/atualizado e
os erros por linha, e só então importa. Destinos: contatos, processos (gera monitoramento), tarefas/prazos, lançamentos financeiros.
Dados pessoais cifrados na entrada; arquivo original apagado após N dias; auditoria; limite de tamanho; dedupe por CPF/CNPJ/CNJ.
Os dados importados alimentam a IA (perfil do escritório) e viram variáveis nas automações.

## 8. Agenda forense (P1)
Feriados nacionais, estaduais e do tribunal + recesso (20/12–20/01) + suspensões; contagem em dias úteis (CPC art. 219); prazo
sugerido mostra a conta feita. Fonte dos feriados por tribunal **[VALIDAR — calendários publicados pelos TJs]**.

**Entregue na fase C (CAD-172)** — app `forense` (`/api/v1/forense/prazo/`, `/feriados/`; tela Agenda forense): CPC arts. 219, 220 e 224,
DJe (Lei 11.419 art. 4º §3º: publicação = 1º dia útil após a disponibilização), feriados nacionais + móveis (Carnaval, Sexta-feira Santa,
Corpus Christi) e Justiça Federal (Lei 5.010/66) calculados; municipais/estaduais/do tribunal cadastrados pelo escritório (pontuais ou
anuais, para todos ou um tribunal). Mostra os dias pulados e o motivo; é sugestão, o advogado confere. **[VALIDAR]** Carnaval/Corpus
Christi e o expediente da Quarta-feira de Cinzas variam por tribunal (hoje a quarta conta como útil).

## 9. Integrações: mais apps e "como pegar os dados" (P1)

**Guia dentro do app** para cada integração: passo a passo numerado (onde clicar, qual permissão marcar, o que copiar), campos com
validação e exemplo, botão **Testar conexão**, mensagens de erro que dizem o que corrigir, link para a documentação oficial.
O guia é conteúdo versionado (Markdown por integração), editável pela equipe Cadrius sem deploy.

Catálogo proposto (por ordem):
1. **Comunicação:** WhatsApp oficial (Meta Cloud API) além do Evolution; Gmail/Outlook (ler e-mails → documentos); Telegram (já há).
2. **Documentos:** Google Drive / OneDrive / Dropbox (importar e salvar), assinatura eletrônica (Clicksign, ZapSign, D4Sign) **[VALIDAR APIs]**.
3. **Tarefas:** Trello (já há), ClickUp, Asana, Notion; Google Calendar (já há), Outlook Calendar.
4. **Financeiro:** Asaas / Pagar.me / Mercado Pago (boleto/PIX dos honorários), emissor de NFS-e (Focus NFe, NFE.io, eNotas) **[VALIDAR]**.
5. **ERPs jurídicos:** Projuris (já modelado), Astrea, ADVBOX **[VALIDAR APIs]**.
6. **Genéricas:** webhooks de entrada/saída prontos para Zapier, Make e n8n.

## 10. Gestão Cadrius: TI cria administradores + setor Fiscal

- **TI cria contas da equipe** (TI, Financeiro, Fiscal) pela Gestão: e-mail, nome, áreas; a pessoa recebe o link de definir senha e
  cadastra o MFA no 1º acesso. Só TI; motivo obrigatório; auditado; superusuário não é criado por aqui. *(implementado nesta fase)*
- **Setor Fiscal da Cadrius** (a empresa Cadrius, não os escritórios):
  - **Fase 1 (feita agora):** área e permissão "Fiscal", visão de faturamento por período (o que foi cobrado e de quem, base para as
    notas) e exportação CSV para o contador.
  - **Fase 2:** emissão de **NFS-e** das assinaturas e pacotes de créditos via emissor (padrão nacional da NFS-e) **[VALIDAR
    provedor e município]**, com conferência antes de emitir; cancelamento e carta de correção; envio da nota ao cliente.
  - **Fase 3:** calendário de obrigações (DAS/DCTFWeb/ISS), retenções na fonte em clientes PJ, relatórios para o contador, e a
    transição da **reforma tributária (CBS/IBS, 2026–2033)** **[VALIDAR com o contador]**.
  - Depois: oferecer um **módulo fiscal para os escritórios** (NFS-e dos honorários, ISS da sociedade de advogados, sucumbência na
    base do ISS no Simples) — pedido comum do mercado (EasyJur/Legal One).

## 11. Suporte ao usuário com a equipe Cadrius (P1)

- **Cliente:** botão "Ajuda" em todas as telas → abrir chamado (categoria, descrição, print/anexo, tela de origem preenchida
  automaticamente), acompanhar status e conversar no chamado; base de artigos (FAQ) antes de abrir.
- **Equipe (Gestão → Suporte, novo grupo "Cadrius Suporte"):** fila com prioridade/SLA, atribuição, respostas prontas, notas internas,
  métricas (tempo de 1ª resposta, resolução).
- **LGPD:** a equipe **não vê dados do escritório** por padrão; o cliente concede **acesso assistido temporário** (ex.: 24 h, só leitura,
  auditado) quando o chamado exigir.
- Notificações por e-mail e no app; depois WhatsApp.

---

## Ordem sugerida

| Fase | Entrega | Por quê |
|---|---|---|
| **A (agora)** | Kit de deploy automático ✔ · TI cria administradores ✔ · setor Fiscal fase 1 ✔ | operação da equipe |
| **B** ✔ (CAD-171) | Quadro de contatos · Importação de dados (contatos/processos) · Suporte (chamados + acesso assistido) | base para automações e atendimento |
| **C** ✔ (CAD-172) | Automações com gatilhos/ações internos + simulação + modelos · agenda forense · cliente do processo | "funcionar de verdade" |
| **D** ✔ (CAD-173) | Caixa de publicações (DJEN) + triagem por IA · minutas sobre documentos | maior dor do advogado |
| **E** ✔ (CAD-174) | IA recomenda automações · perfil e vocabulário do escritório · catálogo de integrações com guia (SMTP, ZapSign, Asaas, Meta) · Marketing (escritório e Cadrius) com verificador OAB · login Produção/Teste · front padronizado e responsivo — ver [PESQUISA_FASE_E.md](PESQUISA_FASE_E.md) | diferencial + alcance |
| **F** ✔ (CAD-175) | Funil de captação e contratos de honorários · finanças do escritório com cobrança Asaas, baixa automática e régua de cobrança · portal do cliente por link seguro · Fiscal fases 2–3 (NFS-e com conferência e obrigações) — ver [PESQUISA_FASE_F.md](PESQUISA_FASE_F.md) | centralização |

## Fontes da pesquisa
- [Sistema para Escritório de Advocacia 2026: CPJ, Astrea, Projuris + IA com LGPD](https://ialocus.com.br/blog/post-sistema-advocacia-lgpd-cpj-astrea-projuris-2026.html)
- [Melhor Software Jurídico em 2026: Guia por Perfil](https://www.bigadv.com.br/blog/melhor-software-juridico/)
- [AdvBox vs Astrea vs Projuris ADV (2026)](https://seasy.host/2026/04/02/advbox-vs-astrea-vs-projuris-adv-software-juridico-2026/)
- [Easyjur ou Astrea](https://easyjur.com/blog/easyjur-ou-astrea-qual-o-melhor-software-juridico/)
- [ADVBOX — o diferencial](https://advbox.com.br/blog/o-diferencial-da-advbox/) · [ADVBOX CRM](https://advbox.com.br/crm) · [Plano Banca Max](https://advbox.com.br/blog/plano-juridico-banca-max-advbox/)
- [Projuris — monitoramento de publicações](https://www.projuris.com.br/blog/monitoramento-de-publicacoes/) · [Projuris ADV vale a pena?](https://www.projuris.com.br/blog/projuris-adv-vale-a-pena/)
- [Legal One — software jurídico](https://www.thomsonreuters.com.br/pt/juridico/legal-one/firm/legal-one-o-software-juridico-essencial-para-seu-escritorio.html) · [Legal One — IA (2026)](https://www.thomsonreuters.com.br/pt/sala-de-imprensa/tr-automatiza-rotinas-juridicas-com-novas-funcionalidades-de-ia-no-legal-one.html)
- [Astrea — B2B Stack](https://www.b2bstack.com.br/product/astrea) · [Astrea ou Projuris](https://www.aurum.com.br/blog/astrea-ou-software-concorrente/)
- [DJEN e Domicílio Judicial Eletrônico — TJMG](https://www.tjmg.jus.br/data/files/9D/13/5A/D6/C0AD6910CF20A669DE08CCA8/DJEN%20e%20Domicilio%20Judicial%20Eletronico%20-%20Usuarios%20Externos%20_1_.pdf) · [Domicílio Judicial Eletrônico 2026](https://www.barbieriadvogados.com/?p=1002)
- [Contabilidade para escritório de advocacia 2026](https://www.contabilidadezen.com.br/blog/contabilidade-escritorio-advocacia-2026/) · [Sucumbência no ISS do Simples — Conjur](https://www.conjur.com.br/?p=916403) · [IAB — reforma tributária e sociedades de advogados](https://iabnacional.org.br/wp-content/uploads/2025/11/Indicacao-no-106_2025-Reforma-tributaria-_Tributacao-de-sociedades-de-advogados.pdf)
