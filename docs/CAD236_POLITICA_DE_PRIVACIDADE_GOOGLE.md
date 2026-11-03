# CAD-236: política de privacidade pública e completa (verificação do app OAuth no Google)

## O que o Google pediu
Projeto `optimal-card-420711`. A revisão apontou dois problemas:
- **Link exigia login:** `https://app.cadrius.ia.br/privacidade` levava para a tela de login.
- **Faltavam os dados do Google:** a política não descrevia como o app trata esses dados.

## O que mudou
| Onde | Mudança |
|---|---|
| **Front** | `/politica-de-privacidade` e `/termos-de-uso` abrem sem login. O link antigo `/privacidade` mostra a política para quem não está logado; quem está logado continua vendo o painel LGPD. A tela de login tem links para a política e os termos (o Google exige o link na página inicial). Páginas indexáveis (sitemap e nginx). |
| **Política 2.0** (`privacy/seed_texts.py`, migração `privacy 0003`) | Seção 3, "Dados de usuários do Google": dados acessados por escopo, uso, compartilhamento, a declaração de **Uso Limitado**, armazenamento e proteção, retenção e exclusão (inclusive sem login, por e-mail). Tem também um resumo em inglês para o revisor. |
| **Retenção** (`privacy/retention.py`) | Os compromissos trazidos do Google Agenda são apagados 90 dias depois do fim (`RETENTION_GOOGLE_EVENT_DAYS`), na rotina diária `enforce_retention`. Antes ficavam para sempre. Ao desconectar o Google, já eram apagados. |
| **Suboperadores** | A linha do Google passa a citar o login, a Agenda e o Drive. |

**Reaceite:** a política mudou de versão. Quem aceitou a 1.0 confirma a 2.0 no próximo acesso, pela janela de aceite que já existe.

**O que a política afirma (conferido no código):**
- **Treino de IA:** dados do Google só vão a provedores que não treinam com os dados. Isso vale porque `aigov.llm.candidates(sensitive=True)` é o padrão do Assistente e da leitura de documentos.
- **Desconectar:** revoga o token no Google e apaga os compromissos copiados (cascata de `GoogleCalendarLink`).
- **Arquivos temporários:** o .zip e a prévia da importação são apagados ao terminar; as prévias abandonadas, em até 48 h.

## Depois do deploy (passo a passo)

### 1. Conferir a página
Abra `https://app.cadrius.ia.br/politica-de-privacidade` numa janela anônima. Ela deve aparecer **sem login** e ter a seção "3. Dados de usuários do Google".

### 2. Atualizar o Google Cloud Console
Na tela de consentimento OAuth (Branding):
- **Link da política de privacidade:** `https://app.cadrius.ia.br/politica-de-privacidade`.
- **Link dos termos de serviço:** `https://app.cadrius.ia.br/termos-de-uso`.
- **Página inicial:** `https://app.cadrius.ia.br/` (tem o link para a política, no rodapé do login).
- Salve.

### 3. Responder ao e-mail do Google (no mesmo fio)

> Olá, equipe de Segurança de Dados de Terceiros,
>
> Obrigado pela análise do projeto 147274585446 (optimal-card-420711). Corrigimos os dois pontos:
>
> 1. **Link acessível:** a política agora é pública, sem login, em https://app.cadrius.ia.br/politica-de-privacidade. A página inicial, https://app.cadrius.ia.br/, tem o link para ela, e atualizamos o link no Cloud Console. O endereço antigo, https://app.cadrius.ia.br/privacidade, também mostra a política para visitantes.
> 2. **Dados do Google:** a seção 3, "Dados de usuários do Google", descreve:
>    - os dados acessados por escopo (openid/email/profile, calendar.events, drive.file e drive.readonly);
>    - o uso e a finalidade;
>    - o compartilhamento (não vendemos; só os suboperadores necessários; IA apenas a pedido do usuário e sem treino);
>    - o armazenamento e a proteção (cifrado em repouso, TLS);
>    - a retenção e a exclusão, com o procedimento (desconectar no app, revogar em myaccount.google.com/permissions ou pedir por e-mail, mesmo sem login).
>
>    Inclui a declaração de Uso Limitado e um resumo em inglês no fim da página.
>
> Ficamos à disposição.
>
> Equipe Cadrius

## Testes
- **Back:** `privacy/tests/test_privacy.py` (`GooglePolicyTests`). Testa a política vigente, pública e com todas as seções pedidas, e a limpeza dos compromissos vencidos.
- **Front:** `Markdown.test.jsx` (links e títulos) e `seo.test.js` (sitemap = páginas públicas).
