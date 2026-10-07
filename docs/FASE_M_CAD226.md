# CAD-226: o Cadrius no dia a dia, do primeiro acesso ao relógio

Plano de UX desta fase e das próximas: [`PLANO_UX_FLUXO_DE_USO.md`](PLANO_UX_FLUXO_DE_USO.md).
Estudo de vídeo e relógio/IoT: [`ESTUDO_VIDEO_E_RELOGIO.md`](ESTUDO_VIDEO_E_RELOGIO.md).

## 1. Fluxo criado pela IA aparece "rodando" em Automações
- **Botão Abrir:** em Automações → Regras, cada regra tem o botão **Abrir**. A regra vira um fluxo desenhado:
  **Quando** (gatilho) → **Se** (condições) → **Faça 1, 2…** (ações).
- **Ao vivo:**
  - com a regra ligada, as setas ficam animadas;
  - a tela confere a cada 5 segundos e mostra as execuções novas sem recarregar;
  - cada passo ganha cor pelo resultado (feito, falhou, aguardando aprovação).
- **No próprio fluxo:** Simular, Ligar/Desligar e Editar. Clicando numa execução, os passos daquela execução aparecem no
  desenho.
- **Assistente:** quando a IA cria, liga ou aceita uma automação, o link da resposta abre direto o fluxo daquela regra
  (`/automacao?aba=regras&regra=<id>`).

## 2. Primeiro acesso: "Fale sobre seu processo"
- **Quando abre:** sozinho no primeiro acesso de quem decide (dono ou administrador), enquanto não houver automação
  ligada.
- **Onde mais está:**
  - no Painel ("Primeiros passos");
  - em Automações → Regras;
  - como atalho em destaque no Assistente.
- **Como a pessoa responde:**
  - marca o que mais pesa no dia a dia (prazos, andamentos, atendimento, e-mail, agenda, cobrança, captação, equipe);
  - conta como trabalha, **digitando ou falando** (ditado por voz no Chrome, Edge e Safari).
- **O que a IA faz:**
  - escolhe as automações dos **modelos prontos** (já revisados);
  - cria uma regra semanal quando a pessoa cita algo que se repete;
  - explica cada escolha com o que a pessoa disse.
- **Sem IA configurada:** as palavras-chave e os temas respondem sozinhos. A entrevista nunca fica sem resposta.
- **Botão "Criar e ver o fluxo":** cria a regra **desligada** e abre o fluxo para simular e ligar.
- **Créditos:** com IA, usa o peso "Rascunho de automação por IA".
- **LGPD:** o texto da pessoa não é guardado; fica só o motivo de cada sugestão.
- **Correção encontrada no teste de ponta a ponta:** aceitar uma sugestão baseada em modelo pronto dava erro 500
  (descrição duplicada). Isso afetava também as sugestões automáticas da Fase E e o "aceitar sugestão" do Assistente.
  Corrigido e coberto por teste.

## 3. Documento escolhido no Assistente
- **Como escolher:** o clipe ao lado da caixa de mensagem abre a lista de documentos do escritório, com busca. Na tela
  do documento, há o botão **Usar no Assistente**.
- **Atalhos depois de escolher:** **Extrair os dados**, **Montar plano de ação**, **Resumir** e **Prazos e riscos**.
- **O que a IA lê:** a ferramenta `ler_documento` lê os **dados já extraídos** e o **texto** do documento, em partes de
  cerca de 9 mil caracteres para documentos longos. Depois responde e oferece criar as tarefas ou salvar o plano em
  Minutas.
- **Segurança:**
  - só documentos do próprio escritório, para quem tem acesso a Documentos;
  - o texto do documento vai delimitado como dado, nunca como instrução, o que protege contra comandos escondidos no
    arquivo.

## 4. E-mail profissional: assinatura e visual
- **Assinatura de cada pessoa** (Perfil → **Assinatura dos e-mails**):
  - um texto (nome, OAB, cargo, telefone);
  - uma **imagem opcional** (assinatura escaneada ou logo, PNG ou JPG de até 200 KB).

  Ela entra nos e-mails que a pessoa envia pelo Cadrius: avisos das regras que ela criou, mensagens confirmadas no
  Assistente e o link do portal do cliente. Sem ela, vale a assinatura do Perfil do escritório.
- **Visual do escritório** (dono ou admin, no mesmo cartão):
  - **Moderno**: faixa com a cor do escritório;
  - **Clássico**: sóbrio, com serifa;
  - **Simples**: só o texto e a assinatura.

  O escritório escolhe também a cor. O botão **Ver como fica** mostra a prévia.
- **Nas regras:** as ações de e-mail têm **Visual do e-mail** e **Ver prévia**.
- **No Assistente:** a IA pode escolher o visual ao propor o envio, e o cartão de confirmação diz qual vai.
- **Como o e-mail sai:**
  - texto puro + HTML;
  - a imagem da assinatura vai embutida (CID), sem o cliente precisar "carregar imagens";
  - o rodapé LGPD continua.
- **Proteção do conteúdo:** todo texto é escapado; só links `https` viram links.

## 5. Marketing com imagem de verdade
- **De onde veio o problema:** as "imagens como template" eram só a sugestão de arte em texto. Agora o cartão **Imagem
  do post** gera:
  - **imagem com IA** (OpenAI `gpt-image-1` ou Gemini, com as regras da OAB, sem dado de cliente; 4 créditos e só cobra
    se entregar);
  - ou **Arte da marca** (grátis): cor do escritório, título e nome.
- **Link público:** a imagem ganha um link assinado (o Instagram publica por URL) e o botão Baixar.
- **Vídeo:** o Cadrius entrega o roteiro com cenas. O estudo e a recomendação estão em `ESTUDO_VIDEO_E_RELOGIO.md`:
  - agora: imagens por cena + app de edição;
  - depois: vídeo de slides gerado pelo Cadrius;
  - IA de vídeo só com sua aprovação de custo.

## 6. Relógio, celular e voz
- **Gatilho novo: "Atalho (relógio, celular ou voz)".** A regra ganha um **link secreto**. Chamar o link roda a regra na
  hora.
- **Texto ditado:** se houver, vira `{{atalho.texto}}`. A tarefa vai para quem criou o atalho.
- **Passo a passo na tela** para:
  - Apple Watch e iPhone (Atalhos/Siri);
  - Android e Wear OS (HTTP Shortcuts);
  - Alexa, Google e botões (IFTTT/Home Assistant).
- **Segurança:**
  - a chave é mostrada uma vez e o banco guarda só o hash;
  - gerar outra invalida a anterior;
  - no máximo 6 acionamentos por minuto;
  - o atalho nunca manda mensagem a cliente;
  - tudo vai para a auditoria.

## 7. Troca da senha temporária
Mesmo padrão do login, com mais cuidado:
- etapas (senha temporária → nova senha → pronto);
- a conta em uso fica visível;
- **mostrar/ocultar senha** em todos os campos;
- **barra de força** com os requisitos à vista;
- aviso ao vivo de "as senhas conferem";
- botão liberado só quando está tudo certo;
- dica de gerenciador de senhas.

Redefinir senha pelo link do e-mail ganhou o mesmo campo e a mesma barra.

## Validação
- **Back:** suíte completa. Testes novos:
  - `brain/tests_discovery.py`;
  - `assistant/tests_docs.py`;
  - `integrations/tests_email_layout.py`;
  - `marketing/tests_images.py`;
  - `automations/tests_shortcut.py`.
- **Front:** testes unitários (`faseM.test.js`), lint sem erros e build OK.
- **E2E no navegador:**
  1. a entrevista abriu sozinha;
  2. 3 sugestões apareceram;
  3. "Criar e ver o fluxo" abriu a regra;
  4. a regra foi simulada e ligada;
  5. o link do atalho foi gerado;
  6. o "relógio" (POST) chamou o link e a execução apareceu ao vivo no fluxo;
  7. a assinatura foi salva com a prévia do e-mail;
  8. a arte da marca apareceu no post;
  9. a tela de senha temporária foi conferida no notebook e no celular.

## No servidor, depois do deploy
1. `docker compose … exec web python manage.py migrate`. Migrações novas:
   - `accounts 0017`;
   - `brain 0003`;
   - `marketing 0003`;
   - `automations 0006`.
2. O peso "Imagem de marketing" (4 créditos) aparece sozinho no Financeiro → Pesos na primeira abertura.
3. Imagem com IA: `OPENAI_API_KEY` ou `GEMINI_API_KEY` no `.env` (o mesmo que já liga as IAs). Confira se
   `API_PUBLIC_URL` está preenchido, porque é a base dos links da imagem e do atalho.
4. Reinicie `web` e `worker`.
