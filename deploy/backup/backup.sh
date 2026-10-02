#!/usr/bin/env bash
# BACKUP CIFRADO do PostgreSQL (e dos segredos), com retenção em camadas e cópia externa.
#
#   backup.sh <prod|staging|all> [rótulo]      rótulo: scheduled (padrão) | pre-deploy | manual
#
# Fluxo por ambiente:
#   pg_dump -Fc (usuário SOMENTE-LEITURA) → valida o arquivo (pg_restore -l) → cifra com GPG (chave PÚBLICA;
#   a privada NUNCA fica no servidor) → sha256 → recent/ (+ daily/ weekly/ monthly/ via hardlink) → rclone para fora do VPS.
#   O dump em texto claro vive só em /dev/shm (RAM) e é apagado ao final.
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/lib-backup.sh"

TARGET="${1:-}"; LABEL="${2:-scheduled}"
[[ "$TARGET" =~ ^(prod|staging|all)$ ]] || die "Uso: $0 <prod|staging|all> [scheduled|pre-deploy|manual]"
[[ "$LABEL" =~ ^[a-z-]+$ ]] || die "rótulo inválido"
load_backup_env
need_root

if [ "$TARGET" = "all" ]; then rc=0; for e in prod staging; do "$0" "$e" "$LABEL" || rc=1; done; exit $rc; fi

ENV_NAME="$TARGET"; DB="$(db_name "$ENV_NAME")"
HC_VAR="HC_PING_URL_$(echo "$ENV_NAME" | tr a-z A-Z)"; HC_URL="${!HC_VAR:-}"
OUT="$BACKUP_ROOT/$ENV_NAME"; mkdir -p "$OUT"/{recent,daily,weekly,monthly} "$BACKUP_ROOT/secrets"; chmod 700 "$BACKUP_ROOT"
exec 9>"/tmp/cadrius-backup-$ENV_NAME.lock"; flock -n 9 || die "Backup de $ENV_NAME já em andamento."

TS="$(date -u +%Y%m%dT%H%M%SZ)"; TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
fail() { local rc=$?; cleanup; alert "BACKUP FALHOU ($ENV_NAME): ${1:-erro na linha $2} (código $rc)"; hc_ping "$HC_URL" fail
         write_status "$ENV_NAME" failed - 0 false "${1:-falha}"; exit 1; }
trap 'fail "" $LINENO' ERR
trap cleanup EXIT

hc_ping "$HC_URL" start
FREE="$(free_pct)"; [ "$FREE" -ge "$MIN_FREE_PCT" ] || fail "pouco espaço em disco ($FREE% livre < $MIN_FREE_PCT%)"

TMP="$(make_tmp)"
PLAIN="$TMP/$DB.dump"
log "[$ENV_NAME] pg_dump de $DB"
mapfile -t HOSTARGS < <(pg_hostargs)
PGPASSWORD="$BACKUP_DB_PASSWORD" pg_cmd pg_dump "${HOSTARGS[@]}" -U cadrius_backup -d "$DB" -Fc -Z 6 --no-owner >"$PLAIN"
[ -s "$PLAIN" ] || fail "dump vazio"

log "[$ENV_NAME] validando o arquivo (pg_restore --list)"
ITEMS="$(pg_cmd pg_restore --list <"$PLAIN" | grep -c ' TABLE ' || true)"
[ "$ITEMS" -ge 1 ] || fail "dump inválido (nenhuma tabela listada)"

FINAL_NAME="${DB}_${TS}_${LABEL}.dump.gpg"; FINAL="$OUT/recent/$FINAL_NAME"
log "[$ENV_NAME] cifrando com GPG ($BACKUP_GPG_RECIPIENT)"
gpg --batch --yes --quiet --trust-model always --compress-algo none -r "$BACKUP_GPG_RECIPIENT" -o "$FINAL" -e "$PLAIN"
( cd "$OUT/recent" && sha256sum "$FINAL_NAME" >"$FINAL_NAME.sha256" )
BYTES="$(stat -c %s "$FINAL")"; rm -f "$PLAIN"

# Promoção em camadas (hardlinks: não duplicam espaço)
TODAY="$(date +%F)"; DOW="$(date +%u)"; DOM="$(date +%d)"
if [ "$LABEL" = "scheduled" ] && ! ls "$OUT"/daily/*"$(date +%Y%m%d)"* >/dev/null 2>&1 \
   && ! find "$OUT/daily" -name "${DB}_$(date +%Y%m%d)*" | grep -q .; then
  ln -f "$FINAL" "$OUT/daily/$FINAL_NAME"; ln -f "$FINAL.sha256" "$OUT/daily/$FINAL_NAME.sha256"
  [ "$DOW" = "7" ] && { ln -f "$FINAL" "$OUT/weekly/$FINAL_NAME";  ln -f "$FINAL.sha256" "$OUT/weekly/$FINAL_NAME.sha256"; }
  [ "$DOM" = "01" ] && { ln -f "$FINAL" "$OUT/monthly/$FINAL_NAME"; ln -f "$FINAL.sha256" "$OUT/monthly/$FINAL_NAME.sha256"; }
  # segredos (ENCRYPTION_KEY!, senhas, .env): 1x por dia, também cifrados
  SEC="$BACKUP_ROOT/secrets/secrets_${TS}.tar.gz.gpg"
  FILES=(); for f in "$CADRIUS_ROOT"/infra/.env "$CADRIUS_ROOT"/prod/.env "$CADRIUS_ROOT"/staging/.env "$BACKUP_ENV_FILE"; do [ -f "$f" ] && FILES+=("$f"); done
  tar -czf - "${FILES[@]}" 2>/dev/null | gpg --batch --yes --quiet --trust-model always -r "$BACKUP_GPG_RECIPIENT" -o "$SEC" -e
  find "$BACKUP_ROOT/secrets" -name 'secrets_*.gpg' -mtime +"$RETENTION_MONTHLY_DAYS" -delete
fi

# Retenção local
find "$OUT/recent"  -type f -mtime +"$RETENTION_RECENT_DAYS"  -delete
find "$OUT/daily"   -type f -mtime +"$RETENTION_DAILY_DAYS"   -delete
find "$OUT/weekly"  -type f -mtime +"$RETENTION_WEEKLY_DAYS"  -delete
find "$OUT/monthly" -type f -mtime +"$RETENTION_MONTHLY_DAYS" -delete

# Cópia EXTERNA (backup que mora só no mesmo VPS não protege contra perda do VPS)
OFFSITE=false
if [ -n "${RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  log "[$ENV_NAME] enviando para $RCLONE_REMOTE"
  if rclone copy "$BACKUP_ROOT" "$RCLONE_REMOTE" --include "/{prod,staging,secrets}/**" --exclude ".tmp/**" \
       --transfers 2 --retries 3 --low-level-retries 5 --quiet; then
    OFFSITE=true
    for cat in recent:$RETENTION_RECENT_DAYS daily:$RETENTION_DAILY_DAYS weekly:$RETENTION_WEEKLY_DAYS monthly:$RETENTION_MONTHLY_DAYS; do
      rclone delete "$RCLONE_REMOTE/$ENV_NAME/${cat%%:*}" --min-age "${cat##*:}d" --quiet 2>/dev/null || true
    done
  else
    alert "Backup $ENV_NAME gravado localmente, mas o ENVIO EXTERNO falhou (rclone)."
  fi
else
  alert "Backup $ENV_NAME só LOCAL: configure RCLONE_REMOTE em $BACKUP_ENV_FILE (cópia externa é obrigatória)."
fi

write_status "$ENV_NAME" ok "$FINAL_NAME" "$BYTES" "$OFFSITE" "ok"
hc_ping "$HC_URL"
ok "[$ENV_NAME] backup $FINAL_NAME ($(numfmt --to=iec "$BYTES" 2>/dev/null || echo "$BYTES")B) offsite=$OFFSITE"
