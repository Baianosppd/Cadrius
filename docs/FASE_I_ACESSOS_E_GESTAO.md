# Fase I (CAD-223) — acessos por grupo, financeiro/fiscal/marketing, integrações, gatilhos, parametrização e fóruns

Referências:
- **Acessos:** [`ACESSOS_E_GRUPOS.md`](ACESSOS_E_GRUPOS.md), a mesma informação de Equipe → "O que cada acesso libera".
- **Fóruns e tribunais:** [`PESQUISA_FORUNS_E_TRIBUNAIS.md`](PESQUISA_FORUNS_E_TRIBUNAIS.md).

## 1. Grupos de acesso do escritório
- **Quem configura:** o dono ou administrador, em Equipe → **Grupos de acesso**.
- **Como cria:**
  - cria grupos por modelo (Advogado, Estagiário, Financeiro, Secretaria, Marketing, Somente consulta) ou do zero;
  - marca cada módulo como *sem acesso*, *ver* ou *ver e alterar*;
  - pode liberar **extras**: ligar regras, aprovar marketing, cancelar contratos, emitir nota.
- **Atribuição:** cada pessoa (membro ou somente leitura) entra num grupo. Quem fica sem grupo segue o cargo, como antes.
  Dono e admin têm sempre acesso total.
- **Onde a regra vale:** na API, para qualquer tela ou chamada (403 `module_forbidden`), no menu, no Assistente IA e
  no conector Claude/ChatGPT.
- **Rastreio:** tudo auditado.
- **Equipe Cadrius:** cada área com nível **total** ou **só consulta**. Nova área **Jurídico**, para o calendário
  forense. Tabela "o que cada área concede" na própria tela.

## 2. Financeiro e fiscal do escritório (Finanças)
- **Fluxo de caixa** de 8, 12 ou 26 semanas: entradas pelas parcelas em aberto; saídas pelas despesas lançadas e pelas
  despesas fixas. Os vencidos ficam à parte.
- **Despesas fixas:** aluguel, sistemas, contador. Lançadas sozinhas no dia escolhido de cada mês, pelo agendamento
  `finance_daily`.
- **Metas e resultado:**
  - meta do mês, com projeção;
  - inadimplência por faixa (a vencer, 1–30, 31–60, 61–90 e 90+ dias);
  - DRE mensal de caixa.
- **Fiscal e contador:**
  - receita por pessoa física e jurídica e receita dos últimos 12 meses (RBT12);
  - estimativa por regime:
    - Simples Anexo IV;
    - Lucro Presumido;
    - Carnê-Leão para o autônomo;
    - ISS fixo da uniprofissional.
  - Recebimentos sem nota.
  - **Pacote do contador** em CSV, com o CPF/CNPJ do pagador exigido no Carnê-Leão. O download é auditado.
  - A estimativa é orientativa e a tela pede para conferir com o contador.
- **NFS-e dos honorários pelo Asaas:**
  - botão "Emitir nota" no pagamento, com confirmação;
  - o status volta pelo webhook (`INVOICE_*`);
  - a nota autorizada dispara o gatilho "Nota fiscal emitida".
- **Gestão Cadrius:**
  - Financeiro: tendência de 12 meses (receita, escritórios novos, cancelamentos, churn) e inadimplentes.
  - Fiscal: RBT12 com alerta dos limites do Simples (R$ 3,6 mi e R$ 4,8 mi).

## 3. Marketing
- **Captação:**
  - formulário público (`/captacao/<token>`) que vira contato e oportunidade "Novo contato";
  - consentimento LGPD obrigatório; WhatsApp e e-mail só ficam autorizados se marcados;
  - armadilha contra robôs e limite por IP;
  - o texto passa pela checagem OAB e alerta "alto" bloqueia até a pessoa confirmar que revisou.
- **Resultados e satisfação:**
  - oportunidades por origem e por campanha, com conversão e honorários fechados;
  - **NPS** pela pesquisa de satisfação (`/pesquisa/<token>`), enviada pela ação de automação **"Pedir avaliação ao
    cliente"**; o comentário fica cifrado.
- **Contatos:**
  - aniversário guardado só como dia e mês (minimização LGPD);
  - "Buscar na Receita" pelo CNPJ (BrasilAPI, sem chave).

## 4. Gatilhos novos (25 no total)
- Contato pelo formulário de captação;
- cliente respondeu a pesquisa de satisfação;
- nota fiscal emitida;
- despesa lançada;
- suspensão de prazos no tribunal;
- aniversário do cliente;
- oportunidade parada no funil (N dias);
- processo sem andamento (N dias);
- contrato terminando (N dias antes da última parcela);
- acompanhamento da meta do mês (dia do mês escolhido).

São 10 modelos prontos, um por gatilho. Exemplos:
- detrator vira tarefa de ligar;
- processo parado vira tarefa de consultar o Balcão Virtual;
- suspensão vira aviso com o link oficial.

## 5. Integrações novas
- **Pesquisa jurídica:** Judit, Jusbrasil Soluções.
- **Assinatura:** Autentique.
- **Fiscal:** NFE.io.
- **ERP:** Omie.
- **Marketing:** Brevo, Mailchimp, RD Station.
- **Comunicação:** Zoom, Zenvia (SMS/WhatsApp oficial).
- **Dados:** BrasilAPI (CNPJ e CEP), já ativo.

Os apps com "testar conexão" automático são Brevo, Mailchimp, NFE.io, Autentique, Omie e Zoom. Os demais trazem um
"validar" explicando como conferir.

## 6. Automação e gestão em conformidade
Automações → **Conformidade**:
- **Nota de conformidade** do escritório.
- **Regras que precisam de atenção:**
  - mensagens a clientes sem aprovação;
  - texto com alerta OAB ou LGPD;
  - regras ligadas sem simular a versão atual;
  - regras criadas por quem saiu da equipe.
- **Envios bloqueados** por falta de consentimento.
- **Resumo de acessos:** pessoas sem grupo, grupos com financeiro e permissões extras.

A Gestão Cadrius vê só as contagens, sem conteúdo.

## 7. Suporte: pedido de parametrização
- **Onde pedir:** Suporte → **Pedir parametrização**.
  - Área: automação, integração, relatório, modelo, acessos, financeiro, fiscal, marketing, importação ou
    tribunais.
  - O formulário tem dicas por área.
- **Fluxo:**
  1. Recebido → em análise → **proposta** (o que será feito, prazo e custo).
  2. **Aprovação do dono ou admin.**
  3. Em execução → entregue.
- **Regras:**
  - nada que gere custo é executado sem o "aprovo", que é auditado;
  - a conversa segue no chamado vinculado;
  - a Gestão Cadrius tem a fila por etapa.

## 8. Fóruns e tribunais
- **Calendário forense nacional:**
  - suspensões, falta de expediente e indisponibilidade de sistema por tribunal, sempre com o link do ato oficial;
  - entram na contagem de prazos e avisam os escritórios com processo ali.
- **Serviços dos tribunais:** Balcão Virtual, custas e pauta, na Agenda forense.
- **Plano das fases 2 e 3:** guias de custas, Juízo 100% Digital, certidões, MNI, Domicílio Judicial Eletrônico,
  Jus.br e cartórios. Detalhes em `PESQUISA_FORUNS_E_TRIBUNAIS.md`.

## Migrações
- `accounts 0015`
- `carteira 0002`
- `contacts 0002`
- `marketing 0002`
- `forense 0002`
- `automations 0005`
- `support 0002`
- `integrations 0005`

Depois do deploy, rodar `python manage.py setup_security_schedules` para agendar as despesas fixas.

## Validação
- **Back:**
  - 598 testes OK, incluindo `accounts/tests_access.py`, `carteira/tests_i.py` e `automations/tests_i.py`;
  - ruff limpo nos arquivos alterados.
- **Front:** 163 testes, lint sem erros e build OK.
- **E2E:** grupos de acesso (o estagiário recebe 403 no financeiro), finanças, captação pelo celular, NPS,
  conformidade, parametrização ponta a ponta e suspensão cadastrada na Gestão aparecendo na Agenda forense.
