# CAD-231: front mais limpo, modelos de minuta, logo nos e-mails e o adicional de mídia com IA

## 1. O que mudou para quem usa

| Tela | Antes | Agora |
|---|---|---|
| Integrações | Google e WhatsApp com formulários inteiros na página, textos longos e o histórico de envios aberto | Só cartões de conectores. "Principais" (Google e WhatsApp do escritório) abre numa janela. O histórico fica recolhido. |
| Cabeçalhos | Subtítulos de uma ou duas linhas explicando a tela | Título forte e subtítulo de até uma linha (ou nenhum). A explicação fica nas dicas e no tour. |
| Minutas | Só modelos prontos ou escritos à mão | Aba **Modelos**: importar Word (.docx), PDF ou texto. As marcações viram campos e o modelo pode ser reaproveitado sempre. Também "Salvar como modelo" a partir de uma minuta. |
| Perfil → Assinatura | Assinatura e cor | Inclui a **logo da empresa**: vai no topo dos e-mails (3 layouts) e nas artes prontas do Marketing. |
| Marketing | "Gerar imagem com IA" ou "Arte da marca" | Estúdio com três caminhos: **Arte pronta** (4 modelos), **Fotos** (do próprio escritório) e **Com IA** (adicional). |
| Celular | Indicadores ímpares deixavam um cartão pela metade; abas grandes | O último indicador ocupa a linha inteira e as abas ficaram mais compactas. |

## 2. Adicional "Estúdio de mídia com IA"

### 2.1 Regra comercial

- **Plano Enterprise:** incluído.
- **Outros planos:** adicional mensal (`MEDIA_ADDON_PRICE_BRL`, padrão R$ 149,00), contratado pelo dono ou administrador em Marketing → imagem do post → "Com IA". É uma assinatura separada no Stripe, então cancelar o adicional não mexe no plano.
- **Cortesia:** a Gestão (área Financeiro) libera em Escritórios, com ou sem prazo, sempre com motivo na auditoria.
- **Consumo:** o adicional libera o recurso e os créditos medem o uso:
  - "Imagem de marketing": 4 créditos;
  - "Vídeo curto de marketing": 40 créditos, editável em Financeiro → pesos.
- A cobrança só acontece quando a imagem ou o vídeo é entregue.

### 2.2 Disponível em todos os planos (sem IA e sem custo)

- **Texto com IA:** já existia; usa os créditos normais.
- **Artes prontas 1080×1080**, na cor e com a logo do escritório:
  - Destaque: fundo na cor da marca e título grande;
  - Citação: fundo claro com a frase em destaque;
  - Dica: faixa "Dica" e texto direto;
  - Com foto: uma foto do escritório com o título por cima.
- **Fotos do escritório:**
  - formatos JPEG, PNG ou WebP, até 8 MB;
  - o Pillow valida, reduz e regrava sem EXIF, ou seja, sem a localização do celular;
  - servem de fundo das artes, de imagem do post ou de referência para a IA.

### 2.3 Com o adicional (Gemini)

- **Imagem:** `gemini-2.5-flash-image` ("Nano Banana") via `generateContent`.
  - Aceita até 3 fotos do escritório como referência (partes `inlineData`), para a imagem sair fiel ao lugar e à equipe.
  - Prompt com as regras da OAB: sobriedade, nada de promessa, nenhum dado de cliente.
- **Vídeo:** Veo (`veo-3.1-fast-generate-preview` por padrão) via `predictLongRunning`, vertical 9:16.
  - Pode partir de uma foto do escritório (quadro inicial).
  - A tela consulta o andamento a cada 10 s. Quando fica pronto, o MP4 é baixado para o armazenamento do Cadrius.
  - Há uma trava contra cobrança dupla.
- **Centralização:** a imagem deixou de usar a OpenAI. Tudo de mídia passa pelo Gemini, com a mesma chave `GEMINI_API_KEY` e respeitando a política de IA do escritório: se o Gemini não estiver entre os provedores permitidos, a IA de mídia fica indisponível.
- **[VALIDAR] na conta Google:**
  - o preço por imagem e por segundo de vídeo no plano pago;
  - o nome do modelo Veo disponível na região;
  - o uso de imagem de referência no Veo (o quadro inicial é suportado; a lista `referenceImages` depende do modelo).

### 2.4 Endpoints

| Método | Caminho | Para quê |
|---|---|---|
| GET | `/api/billing/addons/midia/` | Situação do adicional (ativo, incluído no plano, origem, preço, recursos) |
| POST | `/api/billing/addons/midia/checkout/` | Checkout Stripe (assinatura mensal, `metadata.kind = media_addon`) |
| POST | `/api/billing/addons/midia/cancelar/` | Cancela no fim do período já pago |
| GET/POST | `/api/v1/marketing/fotos/` | Lista e envia fotos (multipart `arquivo`) |
| DELETE | `/api/v1/marketing/fotos/<id>/` | Apaga uma foto |
| POST | `/api/v1/marketing/conteudos/<id>/imagem/` | `{modo: marca \| foto \| ia, estilo, foto_id, referencias: [ids]}` |
| GET/POST | `/api/v1/marketing/conteudos/<id>/video/` | Pede o vídeo / consulta o andamento |
| GET | `/api/v1/publico/marketing/arquivo/<token>/` | Foto ou vídeo por link assinado (só `marketing/fotos` e `marketing/video`) |

Webhook do Stripe:

- `checkout.session.completed` com `kind=media_addon` ativa o adicional, mas só se o valor pago conferir com o preço.
- `invoice.paid` da assinatura do adicional entra no livro do Fiscal.
- `customer.subscription.deleted` do adicional desliga só o adicional.

## 3. Estudo de UX (auditoria desta fase)

Foram capturadas 28 telas em desktop (1366 px) e celular (390 px), com medições automáticas: título, subtítulo, rolagem lateral, elementos que passam da tela e alvos de toque pequenos.

- **Rolagem lateral da página:** nenhuma. Tabelas, abas e o funil rolam dentro do próprio bloco, como deve ser.
- **Subtítulos:** todos com uma linha ou nenhum. Os dois que sobravam longos ("IA do escritório" e "Financeiro" da Gestão) foram encurtados.
- **Indicadores no celular:**
  - Antes, com 3 indicadores, o terceiro ficava pela metade da largura.
  - Agora ocupa a linha (Automações, Carteira e qualquer `.grid`).
- **Abas no celular:** fonte e espaçamento menores, para caber mais. As que não cabem continuam rolando.
- **Editor do Marketing:**
  - A imagem virou um bloco com 3 caminhos claros, em vez de botões soltos.
  - O link de imagem colado foi para "Usar o link de uma imagem", recolhido.
  - O link enorme gerado pelo Cadrius não aparece mais no meio da tela.

Próximos passos sugeridos (não feitos nesta fase):

1. Teste de usabilidade com 3 advogados no Marketing novo e na importação de modelos (roteiro em `ROTEIRO_TESTE_USABILIDADE.md` do front).
2. Cortar a imagem do post no próprio navegador antes de enviar, para quem quer um enquadramento diferente do automático.
3. Biblioteca de artes do escritório: salvar a arte pronta como modelo, com cores e textos fixos.

## 4. Servidor

- **`.env` (todas opcionais, exceto a do Gemini para a IA de mídia):**
  - `GEMINI_API_KEY`: a mesma chave já usada no texto;
  - `MEDIA_ADDON_PRICE_BRL=149.00`;
  - `MARKETING_IMAGE_GEMINI_MODEL=` (vazio: `gemini-2.5-flash-image`);
  - `MARKETING_VIDEO_GEMINI_MODEL=` (vazio: `veo-3.1-fast-generate-preview`).
- **Migrações:**
  - `billing.0009_adicional_midia`;
  - `marketing.0004_fotos_e_video`;
  - `brain.0004_logo_email`.
  - O contêiner do back roda o `migrate` ao subir.
- **Stripe:** nada novo a cadastrar. O checkout cria o preço na hora (`price_data` com `recurring`) e o webhook atual já recebe os eventos.
