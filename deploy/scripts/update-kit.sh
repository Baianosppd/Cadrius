#!/usr/bin/env bash
# Atualiza o KIT de deploy do servidor (scripts, compose, timers de backup, atalhos) a partir do git.
# É o que "sobe para o servidor" as mudanças da pasta deploy/. O código das aplicações é atualizado pelo deploy.sh.
#
#   sudo update-kit.sh [branch]        (padrão: main)
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/../lib/common.sh"
need_root
BR="${1:-main}"; INFRA="$CADRIUS_ROOT/infra"
[ -d "$INFRA/.git" ] || die "$INFRA não é um clone git. Clone o repositório do back ali (ver deploy/README.md)."

log "baixando a branch $BR"
git -C "$INFRA" fetch --prune origin "$BR"
# arquivos do kit copiados à mão (não rastreados) atrapalhariam o checkout: só dentro de deploy/ (o .env fica de fora)
git -C "$INFRA" clean -fdq -- deploy
git -C "$INFRA" checkout -q -B "$BR" "origin/$BR"
git -C "$INFRA" reset -q --hard "origin/$BR"
chmod +x "$INFRA"/deploy/scripts/*.sh "$INFRA"/deploy/backup/*.sh "$INFRA"/deploy/infra/*.sh "$INFRA"/deploy/bootstrap.sh 2>/dev/null || true
chown -R deploy:deploy "$INFRA" 2>/dev/null || true

log "timers de backup e atalhos"
cp "$INFRA"/deploy/backup/systemd/*.service "$INFRA"/deploy/backup/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cadrius-backup-prod.timer cadrius-backup-staging.timer cadrius-verify-restore.timer cadrius-verify-offsite.timer >/dev/null
printf '#!/bin/sh\nexec %s/infra/deploy/scripts/status.sh "$@"\n' "$CADRIUS_ROOT" >/usr/local/bin/cadrius-status
chmod +x /usr/local/bin/cadrius-status

ok "kit atualizado para $(git -C "$INFRA" log --oneline -1)"
echo "Agora: BACK_BRANCH=<branch> FRONT_BRANCH=<branch> $INFRA/deploy/scripts/deploy.sh <staging|prod>   (sem as variáveis: develop/Develop para teste, main para produção)"
