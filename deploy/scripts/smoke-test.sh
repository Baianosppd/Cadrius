#!/usr/bin/env bash
# TESTE DE FUMAÇA de um ambiente: DNS, TLS, saúde, cabeçalhos de segurança, rotas públicas e protegidas,
# CORS, permissões por papel e (opcional) login. Não altera nada.
#
#   smoke-test.sh <prod|staging> [--insecure]
#     --insecure        aceita certificado de homologação (Let's Encrypt staging)
#   SMOKE_USER / SMOKE_PASS   usuário para as rotas autenticadas (em staging: owner@teste.cadrius.ia.br)
#   API_BASE / APP_BASE       sobrescrevem as URLs (testes locais, ex.: API_BASE=http://127.0.0.1:8000)
#   SMOKE_ROLE=staff          informa que o usuário é da equipe (espera 200 em /security/*)
set -uo pipefail
ENV_NAME="${1:-}"; [[ "$ENV_NAME" =~ ^(prod|staging)$ ]] || { echo "Uso: $0 <prod|staging> [--insecure]"; exit 2; }
INSECURE=""; [ "${2:-}" = "--insecure" ] && INSECURE="-k"
c_red=$'\e[31m'; c_grn=$'\e[32m'; c_yel=$'\e[33m'; c_off=$'\e[0m'

DOMAIN="$(grep -E '^ROOT_DOMAIN=' /opt/cadrius/infra/.env 2>/dev/null | cut -d= -f2 || true)"; DOMAIN="${DOMAIN:-cadrius.ia.br}"
if [ "$ENV_NAME" = prod ]; then APP_HOST="app.$DOMAIN"; API_HOST="api.$DOMAIN"; else APP_HOST="app-teste.$DOMAIN"; API_HOST="api-teste.$DOMAIN"; fi
API="${API_BASE:-https://$API_HOST}"; APP="${APP_BASE:-https://$APP_HOST}"; LOGS="https://logs.$DOMAIN"
REMOTE=1; [ -n "${API_BASE:-}" ] && REMOTE=0     # checagens de DNS/TLS só quando falamos com o domínio real
PASS=0; FAIL=0; WARN=0

ok()   { PASS=$((PASS+1)); printf ' %s✔%s %s\n' "$c_grn" "$c_off" "$*"; }
bad()  { FAIL=$((FAIL+1)); printf ' %s✘%s %s\n' "$c_red" "$c_off" "$*"; }
note() { WARN=$((WARN+1)); printf ' %s!%s %s\n' "$c_yel" "$c_off" "$*"; }
h()    { printf '\n== %s\n' "$*"; }
code() { curl -sS $INSECURE -o /dev/null -m 15 -w '%{http_code}' "$@" 2>/dev/null || echo 000; }
body() { curl -sS $INSECURE -m 15 "$@" 2>/dev/null || true; }
hdrs() { curl -sS $INSECURE -m 15 -D - -o /dev/null "$@" 2>/dev/null | tr -d '\r' || true; }
expect_code() { # descrição esperado url [args...]
  local d="$1" e="$2" u="$3"; shift 3; local got; got="$(code "$@" "$u")"
  [ "$got" = "$e" ] && ok "$d → $got" || bad "$d → esperado $e, veio $got"; }
json() { python3 -c "import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
print($1)" 2>/dev/null; }

echo "Ambiente: $ENV_NAME   app=$APP   api=$API"

if [ "$REMOTE" = 1 ]; then
  h "DNS"
  PUB="$(curl -fsS -4 -m 8 https://api.ipify.org 2>/dev/null || true)"
  for host in "$APP_HOST" "$API_HOST" "logs.$DOMAIN"; do
    ip="$(dig +short +time=3 +tries=1 A "$host" 2>/dev/null | tail -1)"
    if [ -z "$ip" ]; then bad "DNS $host sem registro"
    elif [ -n "$PUB" ] && [ "$ip" != "$PUB" ]; then bad "DNS $host → $ip (este servidor é $PUB)"
    else ok "DNS $host → $ip"; fi
  done

  h "TLS e redirecionamento"
  for host in "$APP_HOST" "$API_HOST" "logs.$DOMAIN"; do
    info="$(echo | openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null | openssl x509 -noout -issuer -enddate 2>/dev/null)"
    if [ -z "$info" ]; then bad "TLS $host: não consegui ler o certificado"; continue; fi
    issuer="$(echo "$info" | grep -i '^issuer' | sed 's/^issuer= *//')"; end="$(echo "$info" | grep notAfter | cut -d= -f2)"
    days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
    if echo "$issuer" | grep -qiE 'STAGING|Fake|TRAEFIK DEFAULT'; then
      [ "$ENV_NAME" = prod ] && bad "TLS $host: certificado NÃO confiável ($issuer)" || note "TLS $host: certificado de homologação/padrão ($issuer)"
    else ok "TLS $host: $issuer, vence em ${days} dias"; [ "$days" -lt 15 ] && bad "TLS $host vence em ${days} dias"; fi
  done
  loc="$(curl -sS -o /dev/null -m 10 -w '%{http_code} %{redirect_url}' "http://$API_HOST/readyz/" 2>/dev/null)"
  case "$loc" in 30[18]\ https://*) ok "http → https ($loc)";; *) bad "http não redireciona para https ($loc)";; esac
fi

h "Saúde do back-end"
expect_code "GET /healthz/" 200 "$API/healthz/"
r="$(body "$API/readyz/")"; st="$(echo "$r" | json "d.get('status')")"
[ "$st" = ok ] && ok "GET /readyz/ → status ok ($(echo "$r" | json "d.get('checks')"))" || bad "GET /readyz/ → $r"

h "Cabeçalhos de segurança (API)"
H="$(hdrs "$API/healthz/")"
echo "$H" | grep -qi '^x-content-type-options: nosniff' && ok "X-Content-Type-Options" || bad "falta X-Content-Type-Options"
echo "$H" | grep -qi '^strict-transport-security' && ok "HSTS" || { [ "$REMOTE" = 1 ] && bad "falta Strict-Transport-Security" || note "HSTS ausente (esperado em HTTP local)"; }
echo "$H" | grep -qiE '^(server|x-powered-by): .*(uvicorn|django|python)/?[0-9]' && note "o servidor expõe versão: $(echo "$H" | grep -iE '^(server|x-powered-by)')" || ok "sem versão de software exposta"

if [ -n "${APP_BASE:-}" ] || [ "$REMOTE" = 1 ]; then
  h "Front-end"
  expect_code "GET / (app)" 200 "$APP/"
  body "$APP/" | grep -q 'id="root"' && ok "index.html do React" || bad "index.html sem #root"
  expect_code "GET /rota-inexistente (fallback da SPA)" 200 "$APP/dashboard"
  expect_code "GET /healthz (nginx)" 200 "$APP/healthz"
  HA="$(hdrs "$APP/")"
  echo "$HA" | grep -qi '^content-security-policy:' && ok "CSP presente" || bad "front sem Content-Security-Policy"
  echo "$HA" | grep -qi "^content-security-policy:.*connect-src[^;]*$API_HOST" && ok "CSP libera só a API do ambiente" || note "CSP não cita $API_HOST em connect-src"
  echo "$HA" | grep -qi '^x-frame-options: deny' && ok "X-Frame-Options: DENY" || bad "front sem X-Frame-Options"
  echo "$HA" | grep -qi '^cache-control: .*no-store' && ok "index.html sem cache" || note "index.html pode ficar em cache"
fi

h "Rotas públicas"
expect_code "GET /api/v1/legal/documents/" 200 "$API/api/v1/legal/documents/"
n="$(body "$API/api/v1/legal/documents/" | json "len(d)")"; [ "${n:-0}" -ge 3 ] && ok "documentos legais publicados ($n)" || bad "documentos legais ausentes (rode: manage.py shell / migrações do app privacy)"
expect_code "GET /api/v1/legal/subprocessors/" 200 "$API/api/v1/legal/subprocessors/"
expect_code "GET /api/billing/plans/" 200 "$API/api/billing/plans/"
np="$(body "$API/api/billing/plans/" | json "len(d)")"; [ "${np:-0}" -ge 1 ] && ok "planos cadastrados ($np)" || bad "nenhum plano ativo (o cadastro falharia)"

h "Rotas protegidas exigem login (sem token → 401)"
for p in auth/user/ dashboard/stats/ tasks/ activities/ notifications/unread-count/ connections/ workflows/ documentos/ \
         audit/summary/ audit/events/ ai/policy/ privacy/requests/ security/overview/ teams/members/; do
  expect_code "GET /api/v1/$p" 401 "$API/api/v1/$p"
done
expect_code "GET /admin/login/" 200 "$API/admin/login/"
sc="$(code "$API/security-center/")"; case "$sc" in 301|302|403) ok "/security-center/ sem login → $sc";; *) bad "/security-center/ sem login → $sc (deveria bloquear)";; esac

h "CORS"
O="${APP}"
a="$(curl -sS $INSECURE -m 15 -D - -o /dev/null -X OPTIONS -H "Origin: $O" -H 'Access-Control-Request-Method: GET' -H 'Access-Control-Request-Headers: authorization' "$API/api/v1/auth/user/" 2>/dev/null | tr -d '\r' | grep -i '^access-control-allow-origin' || true)"
echo "$a" | grep -qi "$O" && ok "origem do app permitida" || bad "CORS não libera $O (login do front falharia): '$a'"
e="$(curl -sS $INSECURE -m 15 -D - -o /dev/null -X OPTIONS -H 'Origin: https://evil.example' -H 'Access-Control-Request-Method: GET' "$API/api/v1/auth/user/" 2>/dev/null | tr -d '\r' | grep -i '^access-control-allow-origin' || true)"
[ -z "$e" ] && ok "origem estranha NÃO é liberada" || bad "CORS aberto demais: $e"

if [ "$REMOTE" = 1 ]; then
  h "Monitoramento de logs (Dozzle)"
  expect_code "GET logs.$DOMAIN sem senha" 401 "$LOGS/"
fi

if [ -n "${SMOKE_USER:-}" ] && [ -n "${SMOKE_PASS:-}" ]; then
  h "Rotas autenticadas ($SMOKE_USER)"
  tok="$(curl -sS $INSECURE -m 15 -X POST -H 'Content-Type: application/json' -d "{\"username\":\"$SMOKE_USER\",\"password\":\"$SMOKE_PASS\"}" "$API/api/v1/auth/token/" 2>/dev/null | json "d.get('access','')")"
  if [ -z "$tok" ]; then bad "login falhou (usuário/senha, bloqueio por tentativas ou termos pendentes)"; else
    ok "login → token"
    A=(-H "Authorization: Bearer $tok")
    me="$(body "${A[@]}" "$API/api/v1/auth/user/")"; role="$(echo "$me" | json "d.get('role')")"; staff="$(echo "$me" | json "d.get('is_staff')")"
    [ -n "$role" ] && ok "GET auth/user/ → papel $role, escritório $(echo "$me" | json "(d.get('organization') or {}).get('name')")" || bad "auth/user/ sem papel/escritório"
    org="$(echo "$me" | json "(d.get('organization') or {}).get('name') or ''")"
    if [ -z "$org" ]; then
      note "usuário sem escritório (ex.: equipe Cadrius): rotas do escritório não testadas"
    else
      for p in dashboard/stats/ tasks/ activities/ notifications/unread-count/ connections/ workflows/ documentos/ automations/stats/ \
               sync-history/ ai/policy/ legal/consents/me/ privacy/requests/ teams/members/; do
        expect_code "GET /api/v1/$p" 200 "$API/api/v1/$p" "${A[@]}"
      done
      expect_code "GET /api/billing/plans/current/" 200 "$API/api/billing/plans/current/" "${A[@]}"
      if [ "$role" = OWNER ] || [ "$role" = ADMIN ]; then
        for p in audit/summary/ audit/events/ audit/alerts/ ai/activity/ ai/executions/pending/; do expect_code "GET /api/v1/$p (dono/admin)" 200 "$API/api/v1/$p" "${A[@]}"; done
      else
        for p in audit/summary/ ai/executions/pending/; do expect_code "GET /api/v1/$p (não-gestor deve ser negado)" 403 "$API/api/v1/$p" "${A[@]}"; done
      fi
    fi
    if [ "$staff" = True ] || [ "${SMOKE_ROLE:-}" = staff ]; then
      for p in security/overview/ security/controls/ security/checks/ security/ropa/; do expect_code "GET /api/v1/$p (equipe)" 200 "$API/api/v1/$p" "${A[@]}"; done
      ov="$(body "${A[@]}" "$API/api/v1/security/overview/")"
      echo "$ov" | json "d['audit']['chain_ok']" | grep -q True && ok "cadeia de auditoria ÍNTEGRA ($(echo "$ov" | json "d['audit']['chain_checked']") eventos)" || bad "cadeia de auditoria inconsistente!"
      echo "   conformidade geral: $(echo "$ov" | json "round(d['overall_score'])")%  | verificações com falha: $(echo "$ov" | json "len(d['failing_checks'])")"
    else
      expect_code "GET /api/v1/security/overview/ (não-staff deve ser negado)" 403 "$API/api/v1/security/overview/" "${A[@]}"
    fi
  fi
else
  note "sem SMOKE_USER/SMOKE_PASS: rotas autenticadas não testadas"
fi

if [ -r /var/lib/cadrius/backup.status ]; then
  h "Backups (neste servidor)"
  line="$(grep -E "^$ENV_NAME " /var/lib/cadrius/backup.status | tail -1)"
  if [ -z "$line" ]; then note "nenhum backup de $ENV_NAME registrado ainda"; else
    when="$(echo "$line" | awk '{print $3}')"; age=$(( ( $(date +%s) - $(date -d "$when" +%s) ) / 3600 ))
    echo "$line" | grep -q " ok " && ok "último backup há ${age} h: $(echo "$line" | cut -d' ' -f4-)" || bad "último backup FALHOU: $line"
    echo "$line" | grep -q 'offsite=true' || note "backup sem cópia externa (configure RCLONE_REMOTE)"
    [ "$age" -gt 26 ] && bad "último backup tem mais de 26 h"
  fi
fi

printf '\n%sResultado: %d ok, %d falhas, %d avisos%s\n' "$([ $FAIL -eq 0 ] && echo "$c_grn" || echo "$c_red")" "$PASS" "$FAIL" "$WARN" "$c_off"
[ $FAIL -eq 0 ]
