#!/usr/bin/env bash
# RESTAURAÇÃO de um backup cifrado para um banco NOVO (nunca por cima da produção).
# Precisa da chave GPG PRIVADA (no seu computador ou temporariamente aqui; apague depois).
#
#   restore.sh <arquivo.dump.gpg> <nome_do_novo_banco> <papel_dono: cadrius_prod|cadrius_staging>
#
# Depois de validar o conteúdo (consulte o novo banco), para "promover" à produção:
#   1) pare a stack (docker compose stop web worker)  2) ALTER DATABASE cadrius_prod RENAME TO cadrius_prod_old;
#   3) ALTER DATABASE <novo> RENAME TO cadrius_prod;   4) docker compose up -d      (veja deploy/README.md §Restauração)
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/lib-backup.sh"
FILE="${1:?uso: $0 <arquivo.dump.gpg> <novo_banco> <papel_dono>}"; NEWDB="${2:?}"; OWNER="${3:?}"
[[ "$NEWDB" =~ ^[a-z0-9_]+$ ]] || die "nome de banco inválido"
[[ "$NEWDB" != cadrius_prod && "$NEWDB" != cadrius_staging ]] || die "Recuso restaurar por cima de $NEWDB. Use um banco novo e depois renomeie."
[ -f "$FILE" ] || die "arquivo não encontrado: $FILE"
if [ -f "$FILE.sha256" ]; then (cd "$(dirname "$FILE")" && sha256sum -c "$(basename "$FILE").sha256") || die "SHA-256 não confere — arquivo corrompido"; fi

TMP="$(make_tmp)"; trap 'rm -rf "$TMP"' EXIT
log "decifrando (será pedida a senha da chave privada)"
gpg --decrypt --output "$TMP/restore.dump" "$FILE"
log "criando banco $NEWDB (dono $OWNER) e restaurando"
psql_admin -d postgres -c "CREATE DATABASE \"$NEWDB\" OWNER \"$OWNER\" ENCODING 'UTF8' TEMPLATE template0"
pg_cmd pg_restore -U postgres -d "$NEWDB" --no-owner --role="$OWNER" --exit-on-error <"$TMP/restore.dump"
ok "restaurado em $NEWDB. Confira, por exemplo:  docker exec -it $PG_CONTAINER psql -U postgres -d $NEWDB -c 'select count(*) from audit_auditevent'"
