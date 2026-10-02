#!/usr/bin/env bash
# Funções comuns (log, segredos, validações). Use:  source "$(dirname "$0")/../lib/common.sh"
set -Eeuo pipefail

c_red=$'\e[31m'; c_grn=$'\e[32m'; c_yel=$'\e[33m'; c_blu=$'\e[34m'; c_off=$'\e[0m'
log()  { printf '%s[%s]%s %s\n' "$c_blu" "$(date +%H:%M:%S)" "$c_off" "$*"; }
ok()   { printf '%s ✔ %s%s\n' "$c_grn" "$*" "$c_off"; }
warn() { printf '%s ⚠ %s%s\n' "$c_yel" "$*" "$c_off" >&2; }
die()  { printf '%s ✘ %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "Execute como root (sudo)."; }

# Segredo alfanumérico (sem caracteres que quebrem .env/URLs): rand_alnum 32
rand_alnum() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; echo; }
# Chave Fernet válida (32 bytes em base64 url-safe)
rand_fernet() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; echo; }
# Chave do Django (longa, alfanumérica)
rand_django() { rand_alnum 64; }

# Lê KEY=valor de um arquivo .env (sem executar o arquivo)
env_get() { local f="$1" k="$2"; grep -E "^${k}=" "$f" | tail -1 | cut -d= -f2-; }

# Substitui @CHAVE@ em um template usando pares passados como CHAVE=valor
render_template() {
  local tpl="$1" out="$2"; shift 2
  local content; content="$(cat "$tpl")"
  local kv k v
  for kv in "$@"; do k="${kv%%=*}"; v="${kv#*=}"; content="${content//@${k}@/${v}}"; done
  printf '%s\n' "$content" >"$out"
}

# Raiz padrão do deploy no servidor
CADRIUS_ROOT="${CADRIUS_ROOT:-/opt/cadrius}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/cadrius/backups}"
ETC_DIR="${ETC_DIR:-/etc/cadrius}"
