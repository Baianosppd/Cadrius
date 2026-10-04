#!/usr/bin/env bash
# Troca a imagem do PostgreSQL compartilhado por uma com pgvector (mesma versão 15) e habilita a extensão SÓ em staging (CAD-159).
#
#   upgrade-postgres-pgvector.sh            faz a troca (backup antes) e cria a extensão em cadrius_staging
#   upgrade-postgres-pgvector.sh --prod     também habilita em cadrius_prod (só depois de validar o staging)
#   upgrade-postgres-pgvector.sh --rollback remove a extensão do staging e volta para postgres:15-alpine
#
# ATENÇÃO: o Postgres é UM só para prod e staging → a troca reinicia o banco dos DOIS (~10–30 s de indisponibilidade).
# Rode em janela tranquila. Os dados (volume pgdata) não são tocados; o cluster usa locale C.UTF-8, então a ordenação de índices não muda.
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/../lib/common.sh"
need_root
INFRA="$CADRIUS_ROOT/infra"; ENVF="$INFRA/.env"; COMPOSE=(docker compose --project-name cadrius-infra --env-file "$ENVF" -f "$INFRA/deploy/infra/docker-compose.yml")
NEW_IMAGE="${PGVECTOR_IMAGE:-pgvector/pgvector:pg15}"; OLD_IMAGE="postgres:15-alpine"
MODE="${1:-}"

psql_db() { docker exec -i cadrius_postgres psql -X -v ON_ERROR_STOP=1 -U postgres -d "$1" "${@:2}"; }
set_image() { grep -v '^POSTGRES_IMAGE=' "$ENVF" >"$ENVF.tmp" || true; echo "POSTGRES_IMAGE=$1" >>"$ENVF.tmp"; mv "$ENVF.tmp" "$ENVF"; chmod 600 "$ENVF"; }
wait_healthy() {
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' cadrius_postgres 2>/dev/null)" = healthy ] && return 0; sleep 2; done
  die "Postgres não ficou saudável em 2 min. Veja: docker logs cadrius_postgres"
}

if [ "$MODE" = "--rollback" ]; then
  log "Rollback: removendo a extensão e voltando para $OLD_IMAGE"
  for db in cadrius_staging cadrius_prod; do psql_db "$db" -c "DROP EXTENSION IF EXISTS vector" || warn "não consegui remover de $db (há colunas vector? remova-as antes)"; done
  set_image "$OLD_IMAGE"; "${COMPOSE[@]}" up -d postgres; wait_healthy; ok "Rollback concluído."; exit 0
fi

log "1/6 backup completo antes da troca"
"$INFRA/deploy/backup/backup.sh" all pre-deploy
log "2/6 baixando $NEW_IMAGE"
docker pull "$NEW_IMAGE"
log "3/6 trocando a imagem do Postgres (reinicia o banco de prod e staging)"
set_image "$NEW_IMAGE"
"${COMPOSE[@]}" up -d postgres
wait_healthy
ver="$(psql_db postgres -At -c 'show server_version')"; log "Postgres em execução: $ver"
[[ "$ver" == 15.* ]] || die "versão inesperada ($ver): esperado 15.x. Rollback: $0 --rollback"
log "4/6 conferindo que a extensão está disponível"
psql_db postgres -At -c "select name||' '||default_version from pg_available_extensions where name='vector'" | grep -q vector \
  || die "pgvector indisponível nesta imagem. Rollback: $0 --rollback"
log "5/6 habilitando no banco de STAGING"
psql_db cadrius_staging -c "CREATE EXTENSION IF NOT EXISTS vector"
[ "$MODE" = "--prod" ] && { log "habilitando também em PRODUÇÃO"; psql_db cadrius_prod -c "CREATE EXTENSION IF NOT EXISTS vector"; }
log "6/6 teste funcional"
psql_db cadrius_staging -At -c "select '[1,2,3]'::vector <-> '[1,2,4]'::vector" | grep -qx 1 || die "consulta vetorial falhou"
DOMAIN="$(grep -E '^ROOT_DOMAIN=' "$ENVF" | cut -d= -f2 || true)"; DOMAIN="${DOMAIN:-cadrius.ia.br}"
for host in "api-teste.$DOMAIN" "api.$DOMAIN"; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' -m 10 "https://$host/readyz/" || true)"; log "readyz $host → $code"
done
ok "pgvector habilitado em staging. Rode: smoke-test.sh staging --insecure/normal e confira o app. Rollback: $0 --rollback"
