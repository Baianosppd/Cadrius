# Estudo (CAD-226): vídeo no Marketing e relógio/IoT para gatilhos

## 1. Por que o Marketing não gerava vídeo e as imagens vinham como "template"
- **Imagem:** o Cadrius só escrevia uma *sugestão* de arte ("Arte sóbria com o título…"). Nenhuma imagem era gerada, e
  a prévia do post mostrava o espaço vazio com essa sugestão. Por isso parecia um template.
- **Vídeo:** o canal "Vídeo curto" entrega o **roteiro** (gancho, cenas e encerramento). O Cadrius nunca teve geração de
  vídeo.
- **Texto:** quando a IA não responde, sem chave ou sem crédito, o conteúdo sai como **esqueleto** com `[COMPLETAR]`.
  Isso continua igual, e o aviso na tela explica o motivo.

## 2. O que foi feito nesta entrega: imagem de verdade
No editor do conteúdo, o cartão **Imagem do post** tem dois botões.

| Botão | Como funciona | Custo |
|---|---|---|
| **Gerar imagem com IA** | Usa a IA de imagem configurada: OpenAI `gpt-image-1` ou Gemini `gemini-2.5-flash-image`. Respeita as IAs que o escritório permite. O pedido leva a cena descrita e o tema, nunca dado de cliente, com as regras da OAB (sobriedade, sem ostentação, sem texto na imagem). | Peso **"Imagem de marketing" = 4 créditos**, editável no Financeiro. Só cobra se a imagem chegar. |
| **Arte da marca (sem IA)** | Cartão 1080×1080 na cor do escritório, com o título e o nome do escritório. | Grátis |

- **Quando a IA de imagem falha**, o Cadrius faz a arte da marca e avisa.
- **Link público:** a imagem ganha um link assinado (`/api/v1/publico/marketing/imagem/…`), que é o que o Instagram
  exige para publicar.
- **Botão Baixar:** serve para postar à mão nos outros canais.

**No servidor:** basta ter `OPENAI_API_KEY` ou `GEMINI_API_KEY` no `.env`. Opcionalmente, troque o modelo com
`MARKETING_IMAGE_OPENAI_MODEL` ou `MARKETING_IMAGE_GEMINI_MODEL`. `API_PUBLIC_URL` precisa estar preenchido, como já
está para o Google Agenda.

## 3. Vídeo: opções estudadas

| Opção | Como seria | Custo estimado | Prós | Contras |
|---|---|---|---|---|
| A. **Vídeo de slides** (sem IA de vídeo) | Roteiro → 4 a 6 cenas com a imagem de cada cena + legenda + transição. O servidor monta o MP4 com `ffmpeg`. | Só as imagens (créditos) | Barato, previsível, a cara do escritório | Precisa do `ffmpeg` na imagem Docker (cerca de 80 MB); não é "filmado" |
| B. **IA de vídeo** (Google Veo 3 pela API Gemini, OpenAI Sora 2) | Texto da cena → clipe de 4 a 8 s com movimento | Cerca de US$ 0,15 a 0,50 por segundo (um Reels de 30 s fica entre R$ 25 e 80) | Visual de vídeo de verdade | Caro; demora minutos (fila); risco de imagem fora do tom da OAB; o escritório precisa aprovar cada vídeo |
| C. **Avatar falando** (HeyGen, Synthesia) | O advogado grava um avatar uma vez; o roteiro vira um vídeo dele falando | Assinatura do provedor (de US$ 30 a 90 por mês) + API | Muito pessoal | Contrato à parte; o uso de imagem e voz exige termo do advogado |
| D. **Montar no app de edição** (situação atual) | Roteiro + imagens do Cadrius → CapCut, Canva ou Instagram Edits | Zero | Já funciona hoje | Passo manual |

**Recomendação:**
1. **Agora:** opção D, com as imagens desta entrega. A tela já orienta: gere a imagem de cada cena e monte no app.
2. **Próxima fase:** opção A, o "vídeo de slides", gerado pelo Cadrius com `ffmpeg`. Custo baixo e resultado
   consistente.
3. **Opção B** (Veo ou Sora) como recurso pago à parte, com crédito alto por vídeo e aprovação obrigatória. **Antes de
   ligar, você aprova o custo**, porque é cobrança real nas contas de IA.
4. **Opção C** só se algum cliente pedir, com contrato próprio.

## 4. Relógio, celular e IoT para disparar automações
**Viabilidade:** sim, e sem app próprio. Relógios e assistentes de voz conseguem chamar um link (webhook). O Cadrius
agora tem o gatilho **"Atalho (relógio, celular ou voz)"**.

### Como funciona
1. Em Automações → Regras, crie a regra com o gatilho **Atalho**. Exemplos de ação: "criar tarefa urgente", "avisar a
   equipe no sino" ou "avisar no Slack/Teams".
2. Abra a regra, clique em **Gerar link do atalho** e copie o link. Por segurança, ele aparece uma vez só.
3. Configure no aparelho. O passo a passo aparece na tela:
   - **Apple Watch e iPhone:** no app Atalhos, use "Obter conteúdo de URL" com o método POST. O atalho pode ditar um texto
     (vira `{{atalho.texto}}`) e aparecer no relógio ou responder à Siri.
   - **Android e Wear OS:** app HTTP Shortcuts (ou Tasker), com um botão (tile) no relógio.
   - **Alexa, Google e botões inteligentes** (Flic, Shelly): IFTTT ou Home Assistant chamando o link.
4. O relógio recebe a resposta "Feito: <nome da regra>", e a execução aparece **ao vivo** no fluxo da regra.

### Ideias de uso
- "Cheguei ao fórum": avisa a equipe e cria a tarefa de registrar a audiência.
- "Acabou a audiência: <recado ditado>": cria a tarefa de ata com o recado.
- "Me lembre de ligar para o cliente X": tarefa para amanhã cedo.
- Botão físico na recepção, "cliente chegou": avisa o advogado no sino.

### Segurança
- **Chave do link:** tem 256 bits e o banco guarda só o hash. Gerar outra invalida a anterior.
- **Limites de uso:** no máximo 6 acionamentos por minuto, mais o limite diário de execuções da regra.
- **Regra desligada:** o atalho responde "a regra está desligada".
- **Sem envio a cliente:** o gatilho não tem destinatário, então nunca manda mensagem a cliente.
- **Auditoria:** gerar link e acionar ficam na auditoria, sem o texto ditado.

### Próximos passos possíveis
- App próprio de relógio (watchOS/Wear OS) com login: só faz sentido com demanda. O webhook já cobre 90% dos usos.
- NFC: uma etiqueta na mesa da audiência ou na recepção dispara o atalho do iPhone sozinha.
