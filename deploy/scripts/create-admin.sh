#!/usr/bin/env bash
# Cria o superusuário (staff) para acessar /admin/ e /security-center/ — pede a senha sem ecoar.
# Uso: create-admin.sh <prod|staging> <email>
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/../lib/common.sh"
ENV_NAME="${1:?uso: $0 <prod|staging> <email>}"; EMAIL="${2:?uso: $0 <prod|staging> <email>}"
read -r -s -p "Senha (≥ 12 caracteres): " PW; echo
[ "${#PW}" -ge 12 ] || die "Senha curta."
cd "$CADRIUS_ROOT/$ENV_NAME"
docker compose --project-name "cadrius-$ENV_NAME" exec -T \
  -e DJANGO_SUPERUSER_USERNAME="$EMAIL" -e DJANGO_SUPERUSER_EMAIL="$EMAIL" -e DJANGO_SUPERUSER_PASSWORD="$PW" \
  web python manage.py createsu
