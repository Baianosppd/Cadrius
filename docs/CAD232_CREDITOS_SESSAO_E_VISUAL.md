# CAD-232: créditos por plano, "Manter conectado" e limpeza visual

## 1. Créditos: cada escritório usa só o que tem direito

| Situação | O que pode usar |
|---|---|
| Gratuito / teste (14 dias) | **30 créditos no total**. Antes, um teste que atravessava a virada do mês ganhava outros 30. Agora conta tudo desde o cadastro. |
| Plano pago escolhido no cadastro, ainda sem pagar | Os mesmos 30 do teste, até o pagamento confirmar. |
| Plano pago ativo | A quantidade do plano **por mês** (renova todo mês) + pacotes avulsos comprados, dentro da validade. |
| Adicional de mídia (CAD-231) | Libera imagem e vídeo com IA. Não dá créditos extras: imagem e vídeo descontam do saldo acima. |
| Teste vencido, pagamento atrasado além da carência, cancelado | Nenhuma IA. Os dados continuam acessíveis. |
| Cota por pessoa (Equipe) | Continua valendo dentro do saldo do escritório. |

**Trava central:** a governança de IA (`aigov.guard.check`) recusa qualquer chamada sem saldo, com o código `no_credits`. Isso vale para tela, automação, e-mail ou Assistente. Antes, a extração de e-mail das automações chamava a IA sem conferir nem descontar; agora confere e desconta.

**Telas:** Perfil, Equipe e Gestão → Escritórios mostram o uso do período certo:

- no teste, o total;
- no plano pago, o mês.

Testes: `billing/tests_plan_limits.py`.

## 2. "Manter conectado"

**Antes:**

- a caixa do login não fazia nada;
- a sessão durava 1 dia fixo;
- o advogado entrava de novo todo dia.

**Agora** (`accounts/session_tokens.py`):

- **Marcado (padrão):** a sessão vale **30 dias** (`SESSION_REMEMBER_DAYS`) e se renova a cada uso. Quem usa o Cadrius pelo menos uma vez por mês não vê mais a tela de login.
- **Desmarcado:** 1 dia, também renovado no uso. É para computador compartilhado.
- **Cadastro novo e login com Google/Microsoft:** já ficam conectados.
- **Equipe Cadrius (Gestão):** nunca fica "lembrada". Máximo de 1 dia, com MFA.
- **Segurança:**
  - cada renovação invalida o token anterior (blacklist);
  - sair, trocar a senha ou a TI encerrar as sessões continua derrubando tudo.
- **Várias abas abertas:** o front renova uma aba por vez (Web Locks). A aba que chega depois usa o token que a outra acabou de gravar, então a sessão não cai.

Testes: `accounts/tests_session.py`.

## 3. Visual

- **Avisos repetitivos:**
  - **Removidos ou encurtados:** "você confirma antes…", "nada acontece sem a sua aprovação", "(usa créditos; segue as regras da OAB…)", "(LGPD)" em cada campo, banners explicativos em Automações, Captação, Equipe, IA do escritório e IA segura.
  - **Ficaram só nos pontos estratégicos:**
    - o Verificador OAB do Marketing, com o selo "alertas OAB" no item;
    - o consentimento do contato;
    - o aviso de dados ao ligar o conector do Claude/ChatGPT;
    - o "não envie senhas" do Suporte.
- **Ícone do Cadrius:**
  - favicon (SVG e ICO), ícones do app (192/512, Apple) e `theme-color`;
  - o mesmo símbolo ao lado do nome no menu do escritório, no topo do celular e na Gestão.
- **Automações:** abrir uma regra mostra o fluxo no **React Flow**:
  - **Passos:** gatilho → condições → ações, num canvas com zoom e arrasto.
  - **Regra ligada:** as conexões ficam animadas.
  - **Cores dos passos:** cada passo é colorido pela última execução ou pela simulação.
  - **Celular:** o fluxo fica vertical.
- **Gestão Cadrius:** menu em grupos recolhíveis, como o do escritório:
  - Início;
  - Receita;
  - Atendimento;
  - Pessoas e acessos;
  - Plataforma.

  O grupo da tela atual abre sozinho. Um grupo que teria um item só vira link direto.
- **Títulos:** passaram a bater com o menu (Processos, Finanças, Auditoria).

## 4. Servidor

- **`.env` (opcional):** `SESSION_REMEMBER_DAYS=30`.
- **Migração:** nenhuma nova.
- **Depois do deploy:** quem está logado continua com a sessão antiga, de 1 dia. No próximo login já recebe a de 30 dias.
