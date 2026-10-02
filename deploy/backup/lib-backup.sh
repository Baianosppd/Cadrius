#!/usr/bin/env bash
# Funções do sistema de backup. Importado por backup.sh / verify-restore.sh / restore.sh.
# shellcheck disable=SC2034
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/common.sh"

BACKUP_ENV_FILE="${BACKUP_ENV_FILE:-$ETC_DIR/backup.env}"
STATUS_DIR="${STATUS_DIR:-/var/lib/cadrius}"
PG_CONTAINER="${PG_CONTAINER:-cadrius_postgres}"

load_backup_env() {
  [ -f "$BACKUP_ENV_FILE" ] || die "Falta $BACKUP_ENV_FILE (cp deploy/backup/backup.env.example)."
  # shellcheck disable=SC1090
  set -a; source "$BACKUP_ENV_FILE"; set +a
  : "${BACKUP_GPG_RECIPIENT:?defina BACKUP_GPG_RECIPIENT em $BACKUP_ENV_FILE}"
  : "${BACKUP_DB_PASSWORD:?defina BACKUP_DB_PASSWORD em $BACKUP_ENV_FILE}"
  RETENTION_RECENT_DAYS="${RETENTION_RECENT_DAYS:-3}"
  RETENTION_DAILY_DAYS="${RETENTION_DAILY_DAYS:-14}"
  RETENTION_WEEKLY_DAYS="${RETENTION_WEEKLY_DAYS:-60}"
  RETENTION_MONTHLY_DAYS="${RETENTION_MONTHLY_DAYS:-400}"
  MIN_FREE_PCT="${MIN_FREE_PCT:-15}"
}

# Banco do ambiente: prod -> cadrius_prod ; staging -> cadrius_staging
db_name() { case "$1" in prod) echo cadrius_prod ;; staging) echo cadrius_staging ;; *) die "ambiente inválido: $1" ;; esac; }

# Executa um cliente do PostgreSQL (pg_dump, pg_restore, psql) no contêiner — ou local, só para testes.
pg_cmd() {
  local bin="$1"; shift
  if [ "${CADRIUS_PG_MODE:-docker}" = "local" ]; then
    "$bin" "$@"
  else
    docker exec -i -e PGPASSWORD="${PGPASSWORD:-}" "$PG_CONTAINER" "$bin" "$@"
  fi
}
pg_hostargs() { [ "${CADRIUS_PG_MODE:-docker}" = "local" ] && return 0 || printf -- '-h\nlocalhost\n'; }
# psql como superusuário (socket local no contêiner = trust) — só para verificação/restauração
psql_admin() { pg_cmd psql -X -v ON_ERROR_STOP=1 -U "${PG_ADMIN_USER:-postgres}" "$@"; }

# Diretório temporário em RAM (o dump em texto claro não vai para o disco); cai para disco se faltar espaço.
make_tmp() {
  local t
  if t="$(mktemp -d -p /dev/shm cadrius-backup.XXXXXXXX 2>/dev/null)"; then :; else
    mkdir -p "$BACKUP_ROOT/.tmp"; chmod 700 "$BACKUP_ROOT/.tmp"; t="$(mktemp -d -p "$BACKUP_ROOT/.tmp")"; fi
  chmod 700 "$t"; echo "$t"
}

alert() { # alert "mensagem"
  local msg="[Cadrius/$(hostname -s)] $*"
  warn "$msg"
  [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0
  if [[ "$ALERT_WEBHOOK_URL" == *api.telegram.org* ]]; then
    curl -fsS -m 10 --data-urlencode "text=$msg" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || true
  else  # Discord/Slack/Mattermost (campo "content" e "text")
    local esc="${msg//\\/\\\\}"; esc="${esc//\"/\\\"}"
    curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"content\":\"$esc\",\"text\":\"$esc\"}" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || true
  fi
}

hc_ping() { # hc_ping <url|""> [start|fail]
  local url="$1" kind="${2:-}"; [ -n "$url" ] || return 0
  curl -fsS -m 10 --retry 2 "${url%/}${kind:+/$kind}" >/dev/null 2>&1 || true
}

write_status() { # write_status <env> <ok|failed> <arquivo> <bytes> <offsite:true|false> <mensagem>
  mkdir -p "$STATUS_DIR"
  local f="$STATUS_DIR/backup.status" tmp; tmp="$(mktemp)"
  { [ -f "$f" ] && grep -v "^$1 " "$f" || true; printf '%s %s %s file=%s bytes=%s offsite=%s msg=%s\n' \
      "$1" "$2" "$(date -u +%FT%TZ)" "$3" "$4" "$5" "${6// /_}"; } >"$tmp"
  mv "$tmp" "$f"; chmod 644 "$f"
}

free_pct() { df -P "$BACKUP_ROOT" | awk 'NR==2 {gsub("%","",$5); print 100-$5}'; }
