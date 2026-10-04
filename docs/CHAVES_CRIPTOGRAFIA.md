# Como guardar a ENCRYPTION_KEY e a BLIND_INDEX_KEY (passo a passo)

| Chave | Se perder |
|---|---|
| `ENCRYPTION_KEY` | **dados pessoais cifrados (CPF, telefone, nomes, documentos enviados, segredos de MFA) ficam irrecuperáveis para sempre** |
| `BLIND_INDEX_KEY` | nada se perde: gere outra e rode `manage.py encrypt_pii` (refaz os índices de busca) |
| chave GPG **privada** do backup + senha | os backups (banco, arquivos e o `.env`) ficam ilegíveis |

Regra de ouro: **nunca** cole essas chaves em chat (inclusive comigo), e-mail, WhatsApp, Slack, issue/PR do GitHub ou planilha.

## 1. Ler as chaves no servidor (só na sua tela)
```bash
ssh <seu-usuario>@191.252.221.133
sudo grep -E '^(ENCRYPTION_KEY|BLIND_INDEX_KEY)=' /opt/cadrius/prod/.env
sudo grep -E '^(ENCRYPTION_KEY|BLIND_INDEX_KEY)=' /opt/cadrius/staging/.env    # staging tem chaves PRÓPRIAS
```

## 2. Cópia principal: gerenciador de senhas da empresa
Bitwarden/1Password/Vaultwarden, cofre **compartilhado só com quem precisa** (sugestão: você + Thales — duas pessoas, para não depender de uma só):
- item "Cadrius PROD — chaves de criptografia": campos ocultos `ENCRYPTION_KEY` e `BLIND_INDEX_KEY`, nota com a data;
- item "Cadrius STAGING — chaves de criptografia" (separado);
- item "Cadrius — chave GPG de backup": anexe o arquivo da chave **privada** (`make-keypair.sh` gerou) e a senha dela.

## 3. Cópia de emergência offline (se o gerenciador ficar inacessível)
```bash
# no servidor: gera um arquivo cifrado com senha (você digita a senha; ela vai para o gerenciador, NÃO junto do arquivo)
sudo grep -E '^(ENCRYPTION_KEY|BLIND_INDEX_KEY)=' /opt/cadrius/prod/.env \
  | gpg --symmetric --cipher-algo AES256 -o ~/cadrius-chaves-prod-$(date +%F).gpg
# no seu computador:
scp <seu-usuario>@191.252.221.133:~/cadrius-chaves-prod-*.gpg .
# depois apague a cópia do servidor:
ssh <seu-usuario>@191.252.221.133 'shred -u ~/cadrius-chaves-prod-*.gpg'
```
Guarde o `.gpg` num pendrive em local físico seguro (cofre/gaveta trancada). Opcional: imprimir as chaves e lacrar num envelope no mesmo local.

## 4. Conferir que a cópia está certa (sem expor a chave)
```bash
# servidor
sudo grep '^ENCRYPTION_KEY=' /opt/cadrius/prod/.env | cut -d= -f2- | sha256sum
# seu computador (cole a chave do gerenciador quando o comando pedir; termine com Enter e Ctrl+D)
cat | tr -d '\n' | sha256sum
```
Os dois resumos têm de ser iguais. Repita a conferência **a cada rotação de chave** e ao menos 1× por trimestre (junto com o teste de restauração do backup).

## 5. Quando a chave muda
Rotação (`ENCRYPTION_KEY="NOVA,ANTIGA"`, ver deploy/README.md §11): **guarde a NOVA no gerenciador antes do deploy**; só apague a antiga do cofre depois de `encrypt_pii --dry-run` mostrar 0 linhas pendentes.

## Checklist antes de rodar `encrypt_pii` em produção
- [ ] chaves de PROD no gerenciador (2 pessoas com acesso)
- [ ] cópia offline `.gpg` testada (passo 4 bate)
- [ ] chave GPG privada do backup guardada + senha
- [ ] backup do banco feito na hora (`deploy.sh` faz antes de cada deploy)
