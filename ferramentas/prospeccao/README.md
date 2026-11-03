# Prospecção de clientes com o Harvey + Google Places (CAD-238)

**Público:** advogados autônomos e escritórios pequenos e médios, todas as áreas, nas 27 capitais.

**Divisão de tarefas:**

| Peça | O que faz |
|---|---|
| **API do Google Places** (oficial) | Encontra os escritórios. |
| **Harvey** | Lê o site de cada escritório, acha quem decide e o e-mail publicado, escreve um e-mail curto em português e espera você aprovar antes de enviar. |

## O que tem nesta pasta
| Arquivo | Para quê |
|---|---|
| `harvey-google-places.patch` | Acrescenta ao Harvey o provedor `google_places` (API oficial, com teto de gasto) e o reconhecimento de descadastro em português ("não, obrigado", "sair", "me remova", "parem de enviar"). Inclui testes. A suíte do Harvey passou inteira com o patch. |
| `HARVEY_BASE_COMMIT` | Versão do Harvey em que o patch foi feito e testado. |
| `harvey.local.yaml` | Configuração do Cadrius: produto, preços, público, 27 capitais com coordenadas, janela de envio no horário de Brasília, aquecimento e aprovação obrigatória. |
| `email_rules.md` | Regras de escrita: português, até 90 palavras, sem promessas inventadas, 1 link no máximo. |

## Custo do Google Places
- **Preço:** cada consulta traz até 20 escritórios e cada busca usa até 3 consultas (60 escritórios). Com telefone e site, a consulta cai na faixa "Text Search Enterprise": **1.000 consultas grátis por mês** e depois cerca de **US$ 35 por 1.000**.
- **Volume das 27 capitais:** 11 termos (escritório de advocacia, advogado e 9 áreas) × 27 capitais = 297 buscas, **no máximo 891 consultas**. Cabe nas 1.000 grátis do mês.
- **Primeira rodada:** com 3 cidades são no máximo 99 consultas.
- **Estimativa do Harvey:** ele sempre mostra o custo em dólar sem contar a parte grátis. O `--max-spend` é o teto da rodada.

## Passo a passo (uma vez)

### 1. Domínio separado para prospecção (obrigatório)
**Nunca** envie e-mail frio de `@cadrius.ia.br`. Se o domínio cair em lista de spam, os e-mails de senha, avisos e cobrança do sistema param de chegar.

1. **Registrar o domínio** no registro.br, por exemplo `cadriusjuridico.com.br` ou `usecadrius.com.br`. Confira a disponibilidade lá.
2. **Redirecionar o site do domínio novo** para `https://app.cadrius.ia.br`.
3. **Criar uma caixa no Google Workspace** no domínio novo (por exemplo `jullio@cadriusjuridico.com.br`).
4. **Ligar SPF, DKIM e DMARC** pelo assistente do Workspace.
5. **Aquecer a caixa por 3 semanas** antes de prospectar, com um serviço de aquecimento (o Harvey sugere o TrulyInbox). Anote a data de início em `warmup.start_date`.
6. **Conferir:** `harvey warmup cadriusjuridico.com.br` diz se o domínio está pronto.

### 2. Chave da API do Google Places
1. No Google Cloud Console, crie um **projeto separado**, por exemplo "Cadrius Prospecção". Não use o projeto do login do Google, que está em verificação.
2. **Faturamento:** ative-o no projeto (é exigido mesmo dentro da faixa grátis).
3. **API:** em APIs e serviços → Biblioteca, ative **Places API (New)**.
4. **Chave:** em Credenciais → Criar chave de API → Restringir chave → só "Places API (New)".
5. **Cota diária:** em Cotas da Places API (New), limite as consultas de Text Search a **40 por dia**. Assim a conta nunca passa de 1.000 no mês.
6. **Alerta:** em Faturamento → Orçamentos e alertas, crie um alerta de **US$ 5**.
7. **Segurança da chave:** não cole a chave no chat, em e-mail nem no GitHub. Ela vai só no `.env` do Harvey, no seu computador.

### 3. Instalar o Harvey com o patch (no seu computador)
Requisitos: macOS ou Linux, Python 3.11 ou mais novo, e o Claude Code instalado e logado.

```bash
git clone https://github.com/ethanplusai/harvey.git && cd harvey
git apply /caminho/para/Cadrius/ferramentas/prospeccao/harvey-google-places.patch
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
cp /caminho/para/Cadrius/ferramentas/prospeccao/harvey.local.yaml harvey.local.yaml
cp /caminho/para/Cadrius/ferramentas/prospeccao/email_rules.md skills/email_rules.md
cp .env.example .env
harvey gmail auth          # liga a caixa de prospecção (Google Workspace)
```

Se o `git apply` falhar numa versão nova do Harvey, use a versão testada: `git checkout $(cat .../HARVEY_BASE_COMMIT)` e aplique de novo.

No `.env` do Harvey, preencha:
```
GOOGLE_PLACES_API_KEY=<sua chave>
GOOGLE_PLACES_LANGUAGE=pt-BR
GOOGLE_PLACES_REGION=BR
```

No `harvey.local.yaml`, troque os campos marcados com `TROCAR`:
- e-mail da caixa nova;
- data de início do aquecimento;
- endereço comercial;
- domínios que nunca devem receber (clientes atuais, parceiros).

## Rodando

```bash
# 1) Quanto custa, sem chamar nada
harvey discover --provider google_places --estimate

# 2) Primeira rodada pequena: uma cidade, teto de US$ 2 (cabe nas consultas grátis)
harvey discover --provider google_places --city "Curitiba, PR" --max-spend 2

# 3) Ver o que achou: empresas, quem decide, e-mail encontrado
harvey dashboard           # abre em http://127.0.0.1:5555

# 4) Com o aquecimento pronto: o Harvey escreve e enfileira. NADA sai sem você aprovar no Outbox.
harvey run
```

Depois de ver a qualidade de uma cidade, rode as outras, algumas por dia. A cota de 40 consultas por dia segura o ritmo.

## Regras que valem sempre
- **Só dados profissionais públicos:** nome do escritório, site e e-mail profissional do domínio do escritório. O Harvey usa primeiro o e-mail publicado no próprio site (contato@, nome@escritorio). Quando não acha nenhum, ele deduz o formato (por exemplo nome.sobrenome@escritorio) e só envia se o endereço passar na verificação; endereços duvidosos ficam de fora (`send_to_risky: false`). No Outbox você vê de onde veio cada endereço antes de aprovar.
- **Descadastro em todo e-mail:** a linha já vem configurada. Quem responder "não, obrigado", "sair" ou "me remova" sai da lista na hora e nunca mais recebe.
- **Ritmo:** no máximo 30 envios por dia depois do aquecimento, só em dias úteis, das 9h às 17h. Se as devoluções passarem de 3%, tudo para sozinho.
- **Aprovação:** fica ligada (`require_approval: true`). Leia os primeiros 50 e-mails antes de pensar em aprovar em lote.
- **Base legal (LGPD):** prospecção B2B com legítimo interesse, minimização (só dados de contato profissional) e opção de saída simples. Quem pedir para sair entra em `do_not_contact`.
