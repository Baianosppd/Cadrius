# CAD-225: ajustes do primeiro teste no app-teste

## 1. Créditos de IA "não descontavam"
- **Causa:** os créditos **eram** descontados no servidor, mas as telas não mostravam o uso:
  - **Equipe** exibia valores fixos ("0 / 1000") para todo mundo;
  - **Perfil** e o aviso do período de teste mostravam só o total do plano ("30 créditos").
- **Correção:**
  - **Perfil:** mostra "X de Y créditos usados este mês" e quanto resta.
  - **Aviso do período de teste:** mostra os créditos restantes.
  - **Equipe:**
    - uso real de cada pessoa no mês;
    - total do escritório (usados, restantes e avulsos);
    - créditos distribuídos em cotas;
    - pedidos à IA por atividade (assistente, escrita, extração, triagem…);
    - botão **Definir cota** por pessoa (dono ou admin).
  - **Triagens com IA** (publicações e e-mails) passam a contar no uso, pelo peso "Triagem" da tabela de pesos do Financeiro. O padrão é 0 créditos, ajustável na Gestão.

## 2. Erro ao conectar o Google Agenda
- **Causa:** o código de segurança do OAuth (o `state`) era guardado num cookie criado por uma chamada da tela
  (app-teste → api-teste). O navegador descartava esse cookie, e todo retorno do Google era recusado como "sessão
  expirada", em qualquer escritório.
- **Correção:**
  - o `state` fica no servidor (Redis), vale 10 minutos e só pode ser usado uma vez;
  - nada depende de cookie;
  - mensagens específicas para "URI de redirecionamento não confere" e "autorização expirou";
  - o motivo da recusa do Google fica no log, sem segredos.

## 3. WhatsApp mais fácil
O estudo das opções e a recomendação estão em [`WHATSAPP_CONEXAO.md`](WHATSAPP_CONEXAO.md).
- **Como conectar:** o Cadrius hospeda a Evolution API.
  1. O escritório informa o número com DDD em **Integrações → WhatsApp do escritório**.
  2. Conecta pelo **código de pareamento** (digitado no próprio celular) ou pelo **QR code**.
- **Link para o celular:** se o celular não estiver por perto, o botão **Gerar link para o celular** cria um link de 15
  minutos, sem login, para quem está com ele.
- **Depois de conectado:** as automações e o aviso ao cliente passam a enviar por esse número.
- **Formato de envio:** atualizado para a Evolution v2, a versão que o Cadrius hospeda.

## 4. Front
- **Menu lateral:**
  - "Dia a dia" fica sempre aberto;
  - Produção, Clientes e finanças, Configurações e Segurança viram grupos que abrem com um clique;
  - o grupo abre sozinho quando a tela atual é dele, e o menu lembra o que você deixou aberto;
  - rótulos mais curtos: "Processos", "Plugins de IA".
- **Cadastro (autônomo ou escritório):** a moldura tinha altura fixa com o excesso escondido, o que cortava as opções
  e os passos em notebooks e celulares. Agora rola. No celular, os passos ficam compactos no topo e o formulário ocupa
  a largura toda, com uma coluna só.
- **Recuperar, redefinir e trocar senha:**
  - mesmo visual do login, no padrão de sistema de gestão: formulário compacto, título de tamanho normal e links
    padronizados;
  - regras da senha à vista enquanto a pessoa digita;
  - tela clara para link expirado.
- **Revisão de alinhamento:** 22 telas conferidas em 1366×768. Os títulos estão na mesma posição e nada passa da
  largura. Na Equipe, o cargo saía como texto técnico (`advogado_pleno`) e foi corrigido.

## Validação
- **Back:** suíte completa, incluindo `billing/tests_usage.py`, `integrations/tests_whatsapp.py` e o fluxo do Google
  Agenda reescrito em `gcal/tests.py`.
- **Front:** 164 testes, lint sem erros e build OK.

## No servidor, depois do deploy
- Não há migração nova.
- **Para o WhatsApp hospedado**, no `.env` do ambiente:
  - `COMPOSE_PROFILES=whatsapp`;
  - `EVOLUTION_API_GLOBAL_KEY` com uma chave longa e aleatória.

  Depois, rode `sudo docker compose --project-name cadrius-<env> up -d evolution-api web worker`.
- **Google Agenda:** basta o deploy. Quem tentou conectar antes precisa clicar em "Conectar" de novo.
