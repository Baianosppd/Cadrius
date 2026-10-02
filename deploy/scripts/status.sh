#!/usr/bin/env bash
# Visão rápida do servidor: contêineres, saúde das aplicações, disco, último backup e certificados.
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; source "$HERE/../lib/common.sh"
ROOT_DOMAIN="$(env_get "$CADRIUS_ROOT/infra/.env" ROOT_DOMAIN 2>/dev/null || echo cadrius.ia.br)"
echo "== Contêineres"; docker ps --format 'table {{.Names}}\t{{.Status}}'
echo; echo "== Saúde (via HTTPS)"
for h in "api.$ROOT_DOMAIN" "api-teste.$ROOT_DOMAIN"; do
  code="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "https://$h/readyz/" || echo ---)"; echo "  https://$h/readyz/  -> $code"
done
for h in "app.$ROOT_DOMAIN" "app-teste.$ROOT_DOMAIN"; do
  code="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "https://$h/" || echo ---)"; echo "  https://$h/  -> $code"
done
echo; echo "== Disco"; df -h / /srv 2>/dev/null | awk 'NR==1 || !seen[$1]++'
echo; echo "== Backups"; cat /var/lib/cadrius/backup.status 2>/dev/null || echo "  (nenhum backup registrado ainda)"
echo; echo "== Timers"; systemctl list-timers 'cadrius-*' --no-pager 2>/dev/null | head -8
