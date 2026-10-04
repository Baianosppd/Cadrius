# Gestão Cadrius — área interna de TI e Financeiro (CAD-168)

Área **só da equipe Cadrius**, separada do app dos escritórios: front em `/gestao` (layout próprio, escuro), API em
`/api/v1/backoffice/`. Toda ação exige **motivo** (mín. 10 caracteres) e vai para a trilha de auditoria (`backoffice.action`).

## Quem acessa
Conta ativa + `is_staff` + (superusuário **ou** grupo da área). Grupos criados pela migração `backoffice.0001_groups`
(quem já era `is_staff` antes ganha as duas áreas, para ninguém perder acesso no deploy).

```bash
# no servidor (container do back)
python manage.py cadrius_staff pessoa@cadrius.ia.br --areas ti,financeiro   # define as áreas
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

Regras: ninguém desativa a própria conta; só superusuário altera outro superusuário; créditos de cortesia não contam como venda
no resumo financeiro; o front esconde o que a área não pode, e o back recusa com 403 de qualquer forma.

## Ainda não tem (próximos passos)
MFA para a equipe (verificação "MFA" segue em falha), reprocessar tarefa que falhou na fila, exportar listas, histórico de ações por escritório na tela.
