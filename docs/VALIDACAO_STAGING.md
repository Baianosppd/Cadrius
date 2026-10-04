# Roteiro de validação no ambiente de teste (api-teste / app-teste)

## Criar as contas (no servidor)
```bash
cd /opt/cadrius/staging && docker compose --project-name cadrius-staging exec web python manage.py seed_validation_users
```
O comando **recusa produção**, cria 4 contas da equipe e 7 escritórios `[TESTE]` (um por estado de assinatura) com 10 usuários, e
imprime as senhas **uma vez** — guarde-as no gerenciador de senhas (item "Cadrius STAGING — contas de validação").
Senhas novas: `--reset-passwords`. Apagar tudo depois: `--remove` (escritórios reais não são tocados).

Antes, se ainda não houver planos: `python manage.py seed_plans --apply` (no staging pode).

## Contas e o que validar

| Conta (@teste.cadrius.ia.br) | Cenário | Esperado |
|---|---|---|
| `gestao.ti` | equipe TI | 1º acesso à **Gestão** pede o MFA (QR + código + 10 códigos de recuperação); depois vê Visão geral, Escritórios, Usuários, Sistema, Segurança — **não** vê Financeiro |
| `gestao.financeiro` | equipe Financeiro | vê Visão geral (com MRR), Escritórios, Financeiro; pode estender teste e dar cortesia; **não** vê Usuários/Sistema; não consegue desativar escritório |
| `gestao.completa` | as duas áreas | tudo; teste "Redefinir verificação em duas etapas" de outra conta e o kill switch da IA (religue depois) |
| `gestao.semarea` | equipe sem área | Gestão mostra "sem área" — nenhuma tela de dados |
| `dono` / `admin` | escritório ativo | app normal; Perfil → ativar MFA (opcional); auditoria do escritório visível |
| `advogado` | membro | não vê Auditoria; não vê Gestão |
| `leitura` | só leitura | não cria/edita; conector de ERP só simula |
| `dono.trial` | teste acabando em 3 dias | banner de teste; Gestão → estender teste (Financeiro) |
| `dono.vencido` | teste vencido | IA/automações pausadas, dados acessíveis, banner para assinar |
| `dono.pendente` | pagamento pendente (carência) | tudo funciona + banner de pagamento |
| `dono.restrito` / `dono.suspenso` / `dono.cancelado` | inadimplência 10 / 20 dias, cancelado | IA pausada; leitura e exportação liberadas; sem convites novos |

## MFA — testes rápidos
1. Login com senha → pede código → código errado recusado → código certo entra.
2. Use um **código de recuperação** no lugar do código: entra e avisa quantos restam.
3. 5 códigos errados seguidos → volta para a senha.
4. Perfil → "Gerar novos códigos" (os antigos param de valer) e "Desativar" (pede senha + código).
5. Equipe sem MFA entra no app normalmente, mas a Gestão exige o cadastro.
6. Celular perdido: `gestao.ti` → Usuários → "Redefinir verificação em duas etapas" (motivo obrigatório) → a pessoa entra só com senha e cadastra de novo.
7. Login com Google/Microsoft (se o SSO estiver configurado no staging) também pede o código.

Registre o resultado de cada linha (ok / falhou + print) no card de QA.
