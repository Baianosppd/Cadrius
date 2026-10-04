#!/usr/bin/env bash
# CONFIGURA A CÓPIA EXTERNA (rclone, S3-compatível: Backblaze B2, Wasabi, AWS S3, Locaweb Objetos…), testa e ativa.
# As chaves são pedidas sem eco e ficam só no /root/.config/rclone/rclone.conf (chmod 600) — nunca no git nem no chat.
#
#   setup-offsite.sh
#   (opcional) env: OFFSITE_PROVIDER=Other|AWS|Wasabi|Backblaze   OFFSITE_ENDPOINT=https://s3.us-west-004.backblazeb2.com
#                   OFFSITE_REGION=us-west-004   OFFSITE_BUCKET=cadrius-backups-AAAA
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/lib-backup.sh"
need_root
command -v rclone >/dev/null || { log "instalando rclone"; curl -fsSL https://rclone.org/install.sh | bash; }

REMOTE_NAME="${OFFSITE_REMOTE_NAME:-offsite}"
read -r -p "Endpoint S3 (ex.: https://s3.us-west-004.backblazeb2.com; vazio = AWS): " ENDPOINT_IN
ENDPOINT="${OFFSITE_ENDPOINT:-$ENDPOINT_IN}"
read -r -p "Região (ex.: us-west-004 / sa-east-1) [vazio = padrão do provedor]: " REGION_IN
REGION="${OFFSITE_REGION:-$REGION_IN}"
read -r -p "Nome do bucket (já criado, PRIVADO, com versionamento/Object Lock): " BUCKET_IN
BUCKET="${OFFSITE_BUCKET:-$BUCKET_IN}"; [ -n "$BUCKET" ] || die "Informe o bucket."
read -r -p "Access key ID: " AK
read -r -s -p "Secret access key (não aparece): " SK; echo
[ -n "$AK" ] && [ -n "$SK" ] || die "Chaves vazias."

rclone config delete "$REMOTE_NAME" >/dev/null 2>&1 || true
args=("$REMOTE_NAME" s3 "provider=${OFFSITE_PROVIDER:-Other}" "access_key_id=$AK" "secret_access_key=$SK" "no_check_bucket=true")
[ -n "$ENDPOINT" ] && args+=("endpoint=$ENDPOINT")
[ -n "$REGION" ] && args+=("region=$REGION")
[ -z "$ENDPOINT" ] && args[2]="provider=AWS"
rclone config create "${args[@]}" >/dev/null; unset AK SK
chmod 600 /root/.config/rclone/rclone.conf

log "testando escrita, leitura e hash no destino…"
probe="$(mktemp)"; date -u +"cadrius offsite probe %FT%TZ" >"$probe"
rclone copyto "$probe" "$REMOTE_NAME:$BUCKET/.probe/probe.txt" || die "Não consegui GRAVAR no bucket (chave, bucket ou endpoint errados)."
rclone check "$(dirname "$probe")" "$REMOTE_NAME:$BUCKET/.probe" --include "$(basename "$probe")" --one-way --quiet 2>/dev/null \
  || warn "o destino não confirmou o hash (ok para alguns provedores); seguindo pelo tamanho."
rm -f "$probe"
if rclone deletefile "$REMOTE_NAME:$BUCKET/.probe/probe.txt" >/dev/null 2>&1; then
  warn "A chave deste servidor PODE APAGAR objetos. Para proteção contra ransomware: crie uma chave só de escrita + Object Lock e defina OFFSITE_PRUNE=false."
else
  ok "A chave NÃO consegue apagar objetos (ótimo: use OFFSITE_PRUNE=false e deixe a retenção no bucket)."
fi

# grava no backup.env (sem duplicar)
f="$BACKUP_ENV_FILE"; touch "$f"; chmod 600 "$f"
grep -v -E '^(RCLONE_REMOTE|OFFSITE_PRUNE)=' "$f" >"$f.tmp" || true
{ echo "RCLONE_REMOTE=$REMOTE_NAME:$BUCKET"; echo "OFFSITE_PRUNE=${OFFSITE_PRUNE:-true}"; } >>"$f.tmp"; mv "$f.tmp" "$f"; chmod 600 "$f"

ok "Cópia externa configurada: $REMOTE_NAME:$BUCKET"
echo "Próximo passo:  sudo $HERE/backup.sh prod manual && sudo $HERE/verify-offsite.sh prod && cadrius-status"
