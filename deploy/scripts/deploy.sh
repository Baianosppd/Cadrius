#!/usr/bin/env bash
# Deploy de UM ambiente (prod|staging): atualiza código (back + front), faz backup pré-deploy (prod),
# constrói, sobe, valida /readyz e FAZ ROLLBACK automático se falhar.
#
# Uso:  deploy.sh <prod|staging> [sha-do-commit-para-registrar-no-Sentry]
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/../lib/common.sh"

ENV_NAME="${1:-}"; [[ "$ENV_NAME" =~ ^(prod|staging)$ ]] || die "Uso: $0 <prod|staging> [sha]"
SHA="${2:-}"
ENV_DIR="$CADRIUS_ROOT/$ENV_NAME"
[ -f "$ENV_DIR/.env" ] || die "Falta $ENV_DIR/.env (rode o bootstrap.sh)."
# Autocorreção (CAD-152): a chave dos índices de busca dos dados pessoais cifrados precisa existir; ambientes antigos não a têm.
if ! grep -qE '^BLIND_INDEX_KEY=.+' "$ENV_DIR/.env"; then
  warn "BLIND_INDEX_KEY ausente — gerando em $ENV_DIR/.env (guarde: o backup diário de segredos já inclui este arquivo)"
  grep -v '^BLIND_INDEX_KEY=' "$ENV_DIR/.env" >"$ENV_DIR/.env.tmp" || true
  echo "BLIND_INDEX_KEY=$(rand_alnum 48)" >>"$ENV_DIR/.env.tmp"; cat "$ENV_DIR/.env.tmp" >"$ENV_DIR/.env"; rm -f "$ENV_DIR/.env.tmp"
fi
# Autocorreção: o healthcheck do contêiner chama 127.0.0.1; sem ele em ALLOWED_HOSTS o /readyz responde 400.
if ! grep -qE '^ALLOWED_HOSTS=.*127\.0\.0\.1' "$ENV_DIR/.env"; then
  warn "ALLOWED_HOSTS sem 127.0.0.1 — corrigindo em $ENV_DIR/.env"
  sed -i -E 's|^(ALLOWED_HOSTS=.*)$|\1,127.0.0.1,localhost|' "$ENV_DIR/.env"
fi

# Branches: prod = main; staging = develop (back) / Develop (front)
case "$ENV_NAME" in
  prod)    BACK_BRANCH="${BACK_BRANCH:-main}";    FRONT_BRANCH="${FRONT_BRANCH:-main}" ;;
  staging) BACK_BRANCH="${BACK_BRANCH:-develop}"; FRONT_BRANCH="${FRONT_BRANCH:-Develop}" ;;
esac

exec 9>"/tmp/cadrius-deploy-$ENV_NAME.lock"; flock -n 9 || die "Já existe um deploy de $ENV_NAME em andamento."

compose() { (cd "$ENV_DIR" && docker compose --project-name "cadrius-$ENV_NAME" "$@"); }
sync_repo() { # dir branch
  local dir="$1" br="$2"
  git -C "$dir" fetch --prune origin "$br"
  git -C "$dir" checkout -q "$br" 2>/dev/null || git -C "$dir" checkout -q -B "$br" "origin/$br"
  git -C "$dir" reset --hard "origin/$br"
}
health() { # espera o web ficar saudável (healthcheck do compose = /readyz)
  local i st
  for i in $(seq 1 40); do
    st="$(docker inspect -f '{{.State.Health.Status}}' "$(compose ps -q web)" 2>/dev/null || echo starting)"
    [ "$st" = "healthy" ] && return 0
    sleep 5
  done
  return 1
}

PREV_BACK="$(git -C "$ENV_DIR/backend" rev-parse HEAD 2>/dev/null || echo '')"
PREV_FRONT="$(git -C "$ENV_DIR/frontend" rev-parse HEAD 2>/dev/null || echo '')"

log "[$ENV_NAME] atualizando código (back: $BACK_BRANCH, front: $FRONT_BRANCH)"
sync_repo "$ENV_DIR/backend" "$BACK_BRANCH"
sync_repo "$ENV_DIR/frontend" "$FRONT_BRANCH"
# O front agora traz o próprio Dockerfile de produção (target "prod" + nginx/). Se for uma versão antiga, usa o do kit.
if ! grep -q "AS prod" "$ENV_DIR/frontend/Dockerfile" 2>/dev/null; then
  warn "front sem Dockerfile de produção — usando o do kit (deploy/frontend)"
  cp "$CADRIUS_ROOT/infra/deploy/frontend/Dockerfile" "$ENV_DIR/frontend/Dockerfile"
  mkdir -p "$ENV_DIR/frontend/nginx"
  cp "$CADRIUS_ROOT/infra/deploy/frontend/nginx/"* "$ENV_DIR/frontend/nginx/"
fi
cp "$CADRIUS_ROOT/infra/deploy/app/docker-compose.yml" "$ENV_DIR/docker-compose.yml"

NEW_BACK="$(git -C "$ENV_DIR/backend" rev-parse --short HEAD)"
sed -i "s|^APP_VERSION=.*|APP_VERSION=${SHA:-$NEW_BACK}|" "$ENV_DIR/.env"

if [ "$ENV_NAME" = "prod" ] && docker ps --format '{{.Names}}' | grep -q '^cadrius_postgres$'; then
  log "backup pré-deploy do banco de produção"
  "$CADRIUS_ROOT/infra/deploy/backup/backup.sh" prod pre-deploy || warn "backup pré-deploy falhou — continue só se tiver outro backup recente"
fi

rollback() {
  warn "FALHA no deploy de $ENV_NAME — voltando ao commit anterior"
  [ -n "$PREV_BACK" ]  && git -C "$ENV_DIR/backend"  reset --hard "$PREV_BACK"
  [ -n "$PREV_FRONT" ] && git -C "$ENV_DIR/frontend" reset --hard "$PREV_FRONT"
  compose up -d --build --remove-orphans || true
  exit 1
}

log "[$ENV_NAME] construindo e subindo"
compose up -d --build --remove-orphans || rollback
log "[$ENV_NAME] aguardando /readyz (migrações + banco + cache)"
health || { compose logs --tail=60 web || true; rollback; }
ok "[$ENV_NAME] saudável"

# Rotinas agendadas (idempotente) e, em staging, base sintética (só cria se não existir)
compose exec -T web python manage.py setup_security_schedules >/dev/null && ok "rotinas de segurança/privacidade agendadas"
if [ "$ENV_NAME" = "staging" ]; then
  compose exec -T web python manage.py seed_staging || warn "seed_staging falhou"
fi
docker image prune -f >/dev/null 2>&1 || true
ok "deploy de $ENV_NAME concluído (back $NEW_BACK)"
