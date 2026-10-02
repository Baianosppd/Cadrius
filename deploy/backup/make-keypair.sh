#!/usr/bin/env bash
# Rode NO SEU COMPUTADOR (não no servidor). Gera o par de chaves GPG dos backups:
#   • chave PÚBLICA  -> vai para o servidor (cifra os backups)
#   • chave PRIVADA  -> fica COM VOCÊ, fora do servidor (decifra na hora de restaurar)
# Sem a privada ninguém — nem você — recupera os backups. Guarde-a em 2 lugares (gerenciador de senhas + mídia offline).
set -Eeuo pipefail
NAME="Cadrius Backup"; MAIL="backup@cadrius.ia.br"
echo "Será pedida uma SENHA FORTE para proteger a chave privada (anote em local seguro)."
gpg --quick-generate-key "$NAME <$MAIL>" rsa4096 encr 5y
FPR="$(gpg --list-keys --with-colons "$MAIL" | awk -F: '/^fpr:/ {print $10; exit}')"
gpg --armor --export "$FPR" >cadrius-backup-public.asc
gpg --armor --export-secret-keys "$FPR" >cadrius-backup-PRIVADA.asc
chmod 600 cadrius-backup-PRIVADA.asc
cat <<MSG

Fingerprint: $FPR
  1) Envie ao servidor SÓ a pública:   scp cadrius-backup-public.asc root@191.252.221.133:/root/
  2) No bootstrap informe:             --gpg-pubkey /root/cadrius-backup-public.asc
  3) GUARDE cadrius-backup-PRIVADA.asc + a senha (2 cópias, fora do servidor) e apague-a daqui.
  A chave expira em 5 anos: anote a data para renovar (gpg --edit-key $FPR expire).
MSG
