#!/usr/bin/env bash
# TESTE AUTOMÁTICO DE RESTAURAÇÃO (semanal): faz um dump novo do banco, restaura em um banco descartável
# e compara contagens. Backup que nunca foi restaurado é só uma esperança — este teste prova que funciona.
# (Não usa a chave privada: valida dump + restauração; o ciclo com GPG é validado no simulado trimestral.)
#   verify-restore.sh [prod|staging]    (padrão: prod)
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/lib-backup.sh"
ENV_NAME="${1:-prod}"; DB="$(db_name "$ENV_NAME")"; SCRATCH="restore_test_$$"
load_backup_env; need_root
TMP="$(make_tmp)"
drop_scratch() { psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" >/dev/null 2>&1 || true; }
cleanup() { drop_scratch; rm -rf "$TMP"; }
trap cleanup EXIT
trap 'alert "TESTE DE RESTAURAÇÃO FALHOU ($ENV_NAME) na linha $LINENO"; write_status "restore-test-$ENV_NAME" failed - 0 false falha; exit 1' ERR

mapfile -t HOSTARGS < <(pg_hostargs)
PGPASSWORD="$BACKUP_DB_PASSWORD" pg_cmd pg_dump "${HOSTARGS[@]}" -U cadrius_backup -d "$DB" -Fc --no-owner >"$TMP/t.dump"
psql_admin -d postgres -c "CREATE DATABASE \"$SCRATCH\" TEMPLATE template0 ENCODING 'UTF8'" >/dev/null
pg_cmd pg_restore -U postgres -d "$SCRATCH" --no-owner --exit-on-error <"$TMP/t.dump"

q() { psql_admin -d "$1" -At -c "$2" | tr -d '[:space:]'; }
# tabelas do Django que precisam existir e ter as MESMAS contagens do original
FAILED=0
for t in django_migrations accounts_customuser audit_auditevent privacy_consentrecord workflows_workflow; do
  src="$(q "$DB" "select count(*) from $t" 2>/dev/null || echo ERR)"; dst="$(q "$SCRATCH" "select count(*) from $t" 2>/dev/null || echo ERR)"
  if [ "$src" != "$dst" ] || [ "$dst" = "ERR" ]; then warn "divergência em $t: original=$src restaurado=$dst"; FAILED=1; fi
done
# a trilha de auditoria precisa continuar íntegra (trigger de imutabilidade presente na cópia)
trg="$(q "$SCRATCH" "select count(*) from pg_trigger where tgname='audit_auditevent_immutable'")"
[ "$trg" = "1" ] || { warn "trigger de imutabilidade ausente na cópia restaurada"; FAILED=1; }
[ "$FAILED" = "0" ] || { alert "TESTE DE RESTAURAÇÃO ($ENV_NAME): divergências encontradas — veja o log"; write_status "restore-test-$ENV_NAME" failed - 0 false divergencia; exit 1; }
write_status "restore-test-$ENV_NAME" ok - "$(stat -c %s "$TMP/t.dump")" false "restaurou_e_conferiu"
ok "[$ENV_NAME] restauração testada: tabelas e contagens conferem"
