#!/usr/bin/env bash
# CONFERE A CÓPIA EXTERNA: o último backup de cada ambiente existe no destino, é recente e tem o mesmo conteúdo do local.
# Backup "enviado" que não está lá (credencial vencida, bucket errado, cota cheia) só é descoberto quando é tarde demais.
#   verify-offsite.sh [prod|staging|all]     (padrão: all) — roda diariamente via systemd; falha dispara alerta
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/lib-backup.sh"
TARGET="${1:-all}"; load_backup_env; need_root
[ -n "${RCLONE_REMOTE:-}" ] || { warn "RCLONE_REMOTE vazio: nada a verificar"; exit 1; }
command -v rclone >/dev/null || die "rclone não instalado"
MAX_AGE_H="${OFFSITE_MAX_AGE_HOURS:-30}"
envs=(prod staging); [ "$TARGET" != all ] && envs=("$TARGET")

rc=0
for e in "${envs[@]}"; do
  local_dir="$BACKUP_ROOT/$e/recent"; remote_dir="$RCLONE_REMOTE/$e/recent"
  newest="$(ls -1t "$local_dir"/*.gpg 2>/dev/null | head -1 || true)"
  [ -n "$newest" ] || { warn "[$e] nenhum backup local para conferir"; continue; }
  name="$(basename "$newest")"
  # 1) o arquivo está no destino com o mesmo tamanho?
  remote_size="$(rclone lsjson "$remote_dir" --include "$name" 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["Size"] if d else "")' 2>/dev/null || true)"
  local_size="$(stat -c %s "$newest")"
  if [ "$remote_size" != "$local_size" ]; then
    alert "CÓPIA EXTERNA ($e): $name ausente ou diferente no destino (local=$local_size remoto=${remote_size:-nada})."
    write_status "offsite-check-$e" failed "$name" "$local_size" false "ausente_ou_diferente"; rc=1; continue
  fi
  # 2) o conteúdo bate? (hash quando o destino suporta; senão só o tamanho acima)
  if ! rclone check "$local_dir" "$remote_dir" --include "$name" --one-way --quiet 2>/dev/null; then
    alert "CÓPIA EXTERNA ($e): $name com conteúdo divergente no destino."
    write_status "offsite-check-$e" failed "$name" "$local_size" false "conteudo_divergente"; rc=1; continue
  fi
  # 3) está recente?
  age_h=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 3600 ))
  if [ "$age_h" -gt "$MAX_AGE_H" ]; then
    alert "CÓPIA EXTERNA ($e): último backup tem ${age_h} h (> ${MAX_AGE_H} h)."
    write_status "offsite-check-$e" failed "$name" "$local_size" true "desatualizado"; rc=1; continue
  fi
  write_status "offsite-check-$e" ok "$name" "$local_size" true "conferido"
  ok "[$e] cópia externa conferida: $name (${age_h} h)"
done
exit $rc
