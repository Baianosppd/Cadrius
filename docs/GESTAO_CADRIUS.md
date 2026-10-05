# Gestão Cadrius — área interna de TI e Financeiro (CAD-168)

Área **só da equipe Cadrius**, separada do app dos escritórios: front em `/gestao` (layout próprio, escuro), API em
`/api/v1/backoffice/`. Toda ação exige **motivo** (mín. 10 caracteres) e vai para a trilha de auditoria (`backoffice.action`).

## Quem acessa
Conta ativa + `is_staff` + (superusuário **ou** grupo da área). Grupos criados pela migração `backoffice.0001_groups`
(quem já era `is_staff` antes ganha as duas áreas, para ninguém perder acesso no deploy).

```bash
# no servidor (container do back)
python manage.py cadrius_staff pessoa@cadrius.ia.br --areas ti,financeiro,fiscal   # define as áreas (ou pela tela Equipe Cadrius)
python manage.py cadrius_staff pessoa@cadrius.ia.br --areas ""              # remove o acesso
```

| Tela | TI | Financeiro | O que tem |
|---|---|---|---|
| Visão geral | ✓ | ✓ | escritórios, usuários ativos; TI vê fila/falhas, Financeiro vê MRR, testes acabando, pacotes e cortesias |
| Escritórios | ✓ | ✓ | busca, estado efetivo da assinatura, créditos, equipe. Ações: **Financeiro** estender teste (1–60 dias), créditos de cortesia (1–10.000, validade 1–365 dias); **TI** desativar/reativar escritório (desativar encerra as sessões) |
| Financeiro | | ✓ | planos e preços, pacotes, promoções, informes, pesos de crédito, histórico de preços (antigo `/financeiro`) |
| Usuários | ✓ | | busca por e-mail ou nome (cifrado), desbloquear login, enviar link de nova senha, encerrar sessões, desativar/reativar |
| Sistema e operação | ✓ | | banco, Redis, fila Django-Q (tamanho, workers, falhas com dado pessoal mascarado), rotinas agendadas, o que está configurado (sem segredos), verificações, **kill switch global da IA** |
| Segurança e conformidade | ✓ | | Centro de Segurança (antigo `/seguranca`) |
| **Equipe Cadrius** (CAD-170) | ✓ | | criar contas da equipe (TI, Financeiro, Fiscal) — a pessoa recebe o link de definir senha e cadastra o MFA no 1º acesso; alterar áreas; sem área = sai da equipe (sessões encerradas). Não tira a própria TI; superusuário só pelo servidor |
| **Fiscal** (CAD-170, área própria) | | | livro de recebimentos (assinaturas pela invoice do Stripe, pacotes pela sessão — sem duplicar), tomador (razão social + CNPJ, ou CPF do dono), registrar NF emitida/sem NF, exportar CSV para o contador. Fases 2–3 em `docs/PLANO_PROXIMA_FASE.md` §10 |

Regras: ninguém desativa a própria conta; só superusuário altera outro superusuário; créditos de cortesia não contam como venda
no resumo financeiro; o front esconde o que a área não pode, e o back recusa com 403 de qualquer forma.

## Verificação em duas etapas (CAD-169)
Obrigatória para a equipe: sem MFA a pessoa entra no app, mas a Gestão (e as APIs do Financeiro e do Centro de Segurança) respondem
`403 mfa_required` e a tela abre o cadastro (QR + código + 10 códigos de recuperação). Celular perdido: TI → Usuários → "Redefinir
verificação em duas etapas". Donos/admins de escritório: opcional no Perfil; para exigir, `MFA_REQUIRED_FOR_MANAGERS=True` no `.env`.
O `/admin/` do Django ainda é só senha — use a Gestão no dia a dia.

## Ainda não tem (próximos passos)
Reprocessar tarefa que falhou na fila, exportar listas, histórico de ações por escritório na tela.
