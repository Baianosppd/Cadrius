# Fase E (CAD-174) — pesquisa: integrações, redes sociais e marketing jurídico

Critério usado para entrar no produto: **o escritório usa no dia a dia** e **há API pública utilizável por um escritório pequeno
sem aprovação longa**. O que não passou nos dois critérios ficou fora (lista no fim), para não encher a tela de integrações que
ninguém vai usar.

## 1. Integrações escolhidas

| App | Por que entra | O que o Cadrius faz | Validar antes de produção |
|---|---|---|---|
| **E-mail do escritório (SMTP)** | Todo escritório já tem e-mail (Google Workspace, Microsoft 365, Locaweb). Mensagens saindo do domínio do escritório têm mais confiança e entrega | Automações enviam e-mail pelo SMTP do escritório; sem SMTP, usa o remetente do Cadrius | Senha de app (Google) / SMTP autenticado (Microsoft 365) |
| **ZapSign** | Assinatura eletrônica popular em escritórios pequenos e médios (procuração, contrato de honorários), API simples por token | Documento PDF → assinatura com signatários do quadro de contatos; devolve os links | Contrato do endpoint `/docs/` no sandbox |
| **Asaas** | Cobrança de honorários por boleto/Pix é a dor financeira nº 1; Asaas é citado pelos ERPs jurídicos (ADVBOX) como integração padrão; API e webhooks documentados | Gera cobrança (boleto/Pix) para um contato com CPF/CNPJ | URL do sandbox e campos de `/customers` e `/payments` |
| **Meta (Facebook + Instagram)** | 65% dos escritórios usam redes sociais; Facebook Pages e Instagram profissional têm API oficial de publicação | Publica/agenda os conteúdos aprovados na área de Marketing | Limite do IG (100 posts/24 h), IG exige imagem em URL pública, revisão do app só para contas de terceiros |

Mantidas e documentadas com guia: WhatsApp (Evolution), Telegram, Trello, ClickUp, Google Sheets, Webhook.
**Astrea**: não tem API pública — o guia orienta exportar planilha e usar "Importar dados" (não prometemos o que não existe).

Cada integração tem no catálogo (`integrations/catalog.py`): para que serve no Cadrius, campos pedidos (os secretos nunca voltam
para a tela), passo a passo "onde pegar cada dado", links oficiais e o que validar. O botão **Testar conexão** faz uma chamada só
de leitura (SMTP: login; Asaas: lista 1 cliente; Meta: nome da página; ZapSign: lista documentos; Telegram/Trello/ClickUp: "quem sou eu").

## 2. Ficaram de fora (por enquanto) e por quê

| Ideia | Motivo |
|---|---|
| LinkedIn (publicação automática) | API de páginas exige aprovação do programa "Community Management" — fora do alcance de um escritório. **Solução**: o Cadrius gera o texto, agenda e lembra; a pessoa publica com um clique (copiar) |
| Google Perfil da Empresa (posts) | API exige OAuth com aprovação de acesso da Google; mesmo tratamento do LinkedIn (gerar + lembrar) |
| TikTok | API de publicação exige auditoria do app; pouco uso por escritórios (Provimento recomenda sobriedade) |
| Clicksign / D4Sign | Bons, mas o fluxo de envelopes (Clicksign v3) é mais longo; começar por um provedor (ZapSign) e medir uso |
| Google Drive / OneDrive | O Cadrius já guarda os documentos cifrados; sincronizar cópia fora aumenta superfície de vazamento (LGPD) sem ganho claro |
| Outlook Calendar | Útil, mas exige app Microsoft com consentimento do administrador; Google Calendar já existe. Próxima candidata se houver demanda |

## 3. Redes sociais: o que é possível automatizar

- **Facebook Pages API**: publicar texto, link ou foto; agendamento nativo (`published=false` + `scheduled_publish_time`).
  O Cadrius guarda o agendamento e publica na hora (mesmo caminho para Facebook e Instagram).
- **Instagram Graph API (conta profissional)**: publicação em 2 passos (criar contêiner com `image_url` e publicar); sem
  agendamento nativo; limite de publicações por API em 24 h; exige permissão `instagram_content_publish`.
- **LinkedIn**: API restrita (aprovação). **Google Business Profile**: `localPosts` com OAuth aprovado. → gerar + lembrar.

## 4. Marketing jurídico e a OAB (Provimento 205/2021)

Permitido: marketing de conteúdo **informativo**, sóbrio, redes sociais e até **impulsionamento pago**, desde que o conteúdo seja
informativo. Vedado: mercantilização (preço, desconto, "consulta grátis"), **captação de clientela** (chamada para contratação),
promessa de resultado, autopromoção comparativa ("o melhor"), exposição de clientes/casos, sensacionalismo e ostentação.

Como o Cadrius ajuda:
1. **Gerador** com as regras no prompt + perfil do escritório (áreas, tom, cidade) + exemplos já aprovados pelo escritório.
2. **Verificador** (`marketing/compliance.py`) que marca alertas *alto/médio/baixo*; alerta alto impede aprovar/agendar até
   corrigir ou a pessoa confirmar que revisou. Também alerta CPF, nº de processo e telefone no texto (LGPD/sigilo).
3. **Ideias de pauta** sem IA: datas do calendário (Dia do Consumidor, aniversário da Lei Maria da Penha, recesso forense…) e
   temas sempre úteis por área.
4. **Aprovação por dono/administrador** (é a voz pública do escritório) e calendário editorial com publicação automática (Meta)
   ou lembrete (demais canais).

O que mais gera alcance (pesquisa): LinkedIn para autoridade entre profissionais; Instagram/Reels para explicar direitos em
linguagem simples; **blog com SEO** e **Perfil no Google** para quem procura um advogado na cidade.

## 5. Marketing da própria Cadrius (Gestão → Marketing)

Mesmo motor (gerador, verificador CDC/CONAR, calendário, campanhas) + **indicadores de crescimento** (cadastros, testes,
conversão e cancelamentos por semana) + **playbook** de aquisição: conteúdo educativo semanal (LinkedIn + blog), webinars com
subseções da OAB/ESA, teste grátis com onboarding, programa de indicação em créditos de IA, vídeos curtos "antes e depois" e
Perfil no Google. Publicação na página da Cadrius via variáveis `CADRIUS_META_PAGE_ID/TOKEN/IG_USER_ID` no `.env`.

## 6. IA que aprende por escritório (o que entrou nesta fase)

Tudo isolado por escritório, cifrado em repouso e **sem treinar modelo de terceiros**: aprender = lembrar o que a equipe aprovou e
propor regras que um advogado aprova.

| Sinal | O que o Cadrius aprende | Onde aparece |
|---|---|---|
| Tarefas/eventos repetidos | Automações sugeridas (ex.: "toda segunda a mesma tarefa" → regra semanal) | Automação → Regras → Sugestões da IA |
| Processos, documentos, publicações | Perfil do escritório (áreas, tribunais, tipos de peça) usado nos prompts | IA → Perfil |
| Minuta revisada / post aprovado | Exemplo de estilo (few-shot) e medida de quanto a pessoa editou | IA → Aprendizado |
| **Trocas de termos repetidas** | **Vocabulário do escritório**: a mesma troca ("o requerente" → "a parte autora") em 3 textos vira proposta; aprovada, entra no prompt e é aplicada no texto gerado. Nomes próprios, números e pontuação nunca viram regra | IA → Regras / Central de aprovações |
| Correções na leitura de documentos | Regras de correção de campo (já existia, CAD-165) | IA → Regras |

## Fontes
- [Provimento 205/2021 (texto)](https://www.conjur.com.br/dl/pr/provimento-2052021.pdf) · [OAB SP — novo provimento](https://www.oabsp.org.br/noticia/21-07-16-1620-aprovado-novo-provimento-sobre-publicidade-na-advocacia) · [Marketing jurídico 2026 — Previdenciarista](https://previdenciarista.com/blog/marketing-juridico-guia-completo-e-atualizado/)
- [Instagram — publicação de conteúdo (Meta)](https://developers.facebook.com/documentation/instagram-platform/content-publishing) · [Limites da API do Instagram 2026](https://instantdm.com/blog/instagram-api-rate-limits-explained-2026-developer-guide) · [Guia Instagram API 2026](https://www.getphyllo.com/post/instagram-api-guide) · [Agendar posts no Facebook por API](https://zernio.com/blog/schedule-a-facebook-post) · [LinkedIn: automação e restrições](https://linkedapi.io/guides/how-to-automate-linkedin-posts.md)
- [Google Business Profile — novidades da API (localPosts recorrentes)](https://developers.google.com/my-business/content/latest-updates)
- [Asaas — guia de cobranças](https://docs.asaas.com/docs/guia-de-cobrancas) · [Asaas — webhooks de cobrança](https://docs.asaas.com/docs/webhook-para-cobrancas) · [Clicksign API v3 (envelopes)](https://jentic.com/apis/clicksign)
- [ADVBOX x Astrea x Projuris — integrações](https://asquadz.ai/blog/softwares-gestao-juridica-comparativo/) · [Astrea sem API pública](https://asquadz.ai/blog/astrea-preco-como-funciona/) · [ADVBOX — API e integrações](https://asquadz.ai/blog/advbox-preco-planos-vale-a-pena/)
- [Marketing no Direito — Thomson Reuters](https://www.thomsonreuters.com.br/pt/juridico/blog/marketing-no-direito-redes-sociais.html) · [Turivius — estratégia de marketing jurídico](https://turivius.com/portal/marketing-juridico/)
