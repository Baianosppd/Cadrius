#!/usr/bin/env bash
# Troca a autoridade de certificados do Traefik: "staging" (homologação, sem limites, navegador desconfia)
# ou "real" (Let's Encrypt de produção). Só o Traefik é recriado: PostgreSQL, Dozzle e as aplicações continuam no ar.
#
#   sudo switch-acme.sh real          # certificados de verdade
#   sudo switch-acme.sh staging       # volta para homologação (para testar sem gastar limites)
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/../lib/common.sh"
need_root
MODE="${1:-}"; [[ "$MODE" =~ ^(real|staging)$ ]] || die "Uso: $0 <real|staging>"
INFRA_ENV="$CADRIUS_ROOT/infra/.env"; INFRA_DIR="$CADRIUS_ROOT/infra/deploy/infra"
[ -f "$INFRA_ENV" ] || die "Falta $INFRA_ENV"
case "$MODE" in
  real)    CA="https://acme-v02.api.letsencrypt.org/directory" ;;
  staging) CA="https://acme-staging-v02.api.letsencrypt.org/directory" ;;
esac
DOMAIN="$(env_get "$INFRA_ENV" ROOT_DOMAIN)"; [ -n "$DOMAIN" ] || DOMAIN=cadrius.ia.br
PUB="$(curl -fsS -4 -m 8 https://api.ipify.org 2>/dev/null || true)"

log "conferindo o DNS (o Let's Encrypt precisa enxergar cada nome apontando para $PUB)"
BAD=0
for h in app api app-teste api-teste logs; do
  ip="$(dig +short +time=3 +tries=1 A "$h.$DOMAIN" 2>/dev/null | tail -1 || true)"
  if [ "$ip" = "$PUB" ]; then ok "$h.$DOMAIN → $ip"; else warn "$h.$DOMAIN → '${ip:-sem registro}' (esperado $PUB)"; BAD=1; fi
done
for h in "$DOMAIN" "www.$DOMAIN"; do
  ip="$(dig +short +time=3 +tries=1 A "$h" 2>/dev/null | tail -1 || true)"
  [ "$ip" = "$PUB" ] && ok "$h → $ip" || warn "$h sem DNS correto: só o redirecionamento para o app fica sem HTTPS (não afeta o resto)"
done
if [ "$BAD" = 1 ] && [ "$MODE" = real ]; then
  die "Há nomes principais com DNS errado. Corrija no painel da Locaweb e rode de novo (o Let's Encrypt bloqueia por excesso de falhas)."
fi

if grep -q '^ACME_CASERVER=' "$INFRA_ENV"; then sed -i "s|^ACME_CASERVER=.*|ACME_CASERVER=$CA|" "$INFRA_ENV"; else echo "ACME_CASERVER=$CA" >>"$INFRA_ENV"; fi
log "ACME_CASERVER → $CA"

cd "$INFRA_DIR"
DC=(docker compose --project-name cadrius-infra --env-file "$INFRA_ENV")
"${DC[@]}" stop traefik >/dev/null
"${DC[@]}" rm -f traefik >/dev/null
# os certificados já emitidos pela outra autoridade precisam ser descartados, senão o Traefik os reaproveita
docker volume rm cadrius_traefik_acme >/dev/null 2>&1 || warn "volume traefik_acme não encontrado (ok se for a primeira vez)"
"${DC[@]}" up -d traefik
ok "Traefik recriado com a autoridade '$MODE'"

log "aguardando a emissão (até 2 min)"
for host in app-teste.$DOMAIN api.$DOMAIN app.$DOMAIN api-teste.$DOMAIN logs.$DOMAIN; do
  for i in $(seq 1 24); do
    iss="$(echo | openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null || true)"
    if [ -n "$iss" ] && ! echo "$iss" | grep -qi 'TRAEFIK DEFAULT'; then break; fi
    sleep 5
  done
  case "$iss" in
    *STAGING*|*Fake*) warn "$host → $iss";;
    "") warn "$host → sem resposta TLS (o ambiente pode não estar no ar ainda: rode o deploy dele e repita a checagem)";;
    *TRAEFIK*) warn "$host → certificado padrão do Traefik (ainda não emitido; veja: docker logs cadrius_traefik --tail 30)";;
    *) ok "$host → $iss";;
  esac
done
echo
echo "Confira os logs do Traefik se algum nome não emitiu:  docker logs cadrius_traefik --tail 40 | grep -iE 'acme|error|certificate'"
