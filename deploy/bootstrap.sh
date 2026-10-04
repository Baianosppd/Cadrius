#!/usr/bin/env bash
# BOOTSTRAP do VPS Cadrius (Ubuntu 22.04/24.04 ou Debian 12) — IDEMPOTENTE: pode rodar de novo sem estragar nada.
#
#   sudo ./bootstrap.sh \
#       --domain cadrius.ia.br --acme-email voce@cadrius.ia.br \
#       --back-repo https://github.com/Baianosppd/Cadrius.git \
#       --front-repo https://github.com/<org>/<repo-front>.git \
#       --gpg-pubkey ./cadrius-backup-public.asc \
#       [--deploy-pubkey "ssh-ed25519 AAAA... github-actions"] [--lock-ssh] [--acme-staging] [--skip-dns-check]
#
# O que faz: SO + firewall + Docker, estrutura de pastas, segredos aleatórios, Postgres (produção + teste),
# Traefik/HTTPS, Dozzle, backups automáticos (systemd) e primeiro deploy de teste/produção.
set -Eeuo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"; source "$HERE/lib/common.sh"
need_root

DOMAIN="cadrius.ia.br"; ACME_EMAIL=""; BACK_REPO="https://github.com/Baianosppd/Cadrius.git"; FRONT_REPO=""
GPG_PUB=""; DEPLOY_PUB=""; LOCK_SSH=0; ACME_STAGING=0; SKIP_DNS=0; SKIP_DEPLOY=0
while [ $# -gt 0 ]; do case "$1" in
  --domain) DOMAIN="$2"; shift 2 ;;
  --acme-email) ACME_EMAIL="$2"; shift 2 ;;
  --back-repo) BACK_REPO="$2"; shift 2 ;;
  --front-repo) FRONT_REPO="$2"; shift 2 ;;
  --gpg-pubkey) GPG_PUB="$2"; shift 2 ;;
  --deploy-pubkey) DEPLOY_PUB="$2"; shift 2 ;;
  --lock-ssh) LOCK_SSH=1; shift ;;
  --acme-staging) ACME_STAGING=1; shift ;;
  --skip-dns-check) SKIP_DNS=1; shift ;;
  --skip-deploy) SKIP_DEPLOY=1; shift ;;
  *) die "opção desconhecida: $1" ;;
esac; done
[ -n "$ACME_EMAIL" ] || die "Informe --acme-email (aviso de expiração do certificado)."
[ -n "$FRONT_REPO" ] || die "Informe --front-repo (URL do repositório do front-end)."
[ -f "${GPG_PUB:-/nonexistent}" ] || die "Informe --gpg-pubkey <arquivo .asc> (gere com deploy/backup/make-keypair.sh na SUA máquina)."

ROOT="$CADRIUS_ROOT"; CRED="$ETC_DIR/credenciais.txt"
PROD_HOST_APP="app.$DOMAIN"; PROD_HOST_API="api.$DOMAIN"
STG_HOST_APP="app-teste.$DOMAIN"; STG_HOST_API="api-teste.$DOMAIN"

# ---------------------------------------------------------------- 1. Sistema
log "1/10 sistema operacional"
export DEBIAN_FRONTEND=noninteractive
timedatectl set-timezone America/Sao_Paulo || true
apt-get update -qq && apt-get -y -qq upgrade
apt-get -y -qq install ca-certificates curl gnupg git ufw fail2ban unattended-upgrades apache2-utils \
  rclone postgresql-client jq dnsutils util-linux coreutils >/dev/null
ok "pacotes instalados"

if ! swapon --show | grep -q .; then
  mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  if [ "$mem_mb" -lt 6000 ]; then
    log "criando swap de 2 GB (RAM ${mem_mb} MB)"
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    echo 'vm.swappiness=10' >/etc/sysctl.d/99-cadrius.conf; sysctl -p /etc/sysctl.d/99-cadrius.conf >/dev/null
  fi
fi

# ---------------------------------------------------------------- 2. Docker
log "2/10 Docker"
if ! command -v docker >/dev/null 2>&1; then
  . /etc/os-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc && chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -qq && apt-get -y -qq install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
cat >/etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" }, "live-restore": true }
EOF
systemctl enable --now docker && systemctl restart docker
ok "Docker $(docker --version | cut -d' ' -f3 | tr -d ,)"

# ---------------------------------------------------------------- 3. Usuário deploy + SSH
log "3/10 usuário 'deploy' e SSH"
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys; chmod 600 /home/deploy/.ssh/authorized_keys; chown deploy:deploy /home/deploy/.ssh/authorized_keys
[ -n "$DEPLOY_PUB" ] && { grep -qF "$DEPLOY_PUB" /home/deploy/.ssh/authorized_keys || echo "$DEPLOY_PUB" >>/home/deploy/.ssh/authorized_keys; ok "chave do deploy adicionada"; }
# sudo sem senha SOMENTE para os scripts de deploy
cat >/etc/sudoers.d/cadrius-deploy <<EOF
deploy ALL=(root) NOPASSWD: $ROOT/infra/deploy/scripts/deploy.sh, $ROOT/infra/deploy/scripts/status.sh, $ROOT/infra/deploy/scripts/create-admin.sh, $ROOT/infra/deploy/backup/backup.sh
EOF
chmod 440 /etc/sudoers.d/cadrius-deploy; visudo -cf /etc/sudoers.d/cadrius-deploy >/dev/null

if [ "$LOCK_SSH" = 1 ]; then
  if [ -s /home/deploy/.ssh/authorized_keys ] || [ -s /root/.ssh/authorized_keys ]; then
    cat >/etc/ssh/sshd_config.d/99-cadrius.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 4
X11Forwarding no
EOF
    sshd -t && systemctl reload ssh 2>/dev/null || systemctl reload sshd
    warn "SSH agora só aceita chave. ABRA OUTRO TERMINAL e teste o login ANTES de fechar este."
  else
    warn "--lock-ssh ignorado: nenhuma chave SSH instalada (você ficaria trancado para fora)."
  fi
fi

# ---------------------------------------------------------------- 4. Firewall e fail2ban
log "4/10 firewall (UFW), fail2ban e atualizações automáticas"
ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
# Docker publica portas por fora do UFW; por isso só o Traefik publica portas (80/443) — Postgres/Redis NÃO.
systemctl enable --now fail2ban >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
ok "portas abertas: 22, 80, 443"

# ---------------------------------------------------------------- 5. Pastas e código
log "5/10 pastas e repositórios"
install -d -m 755 "$ROOT" "$ROOT/prod" "$ROOT/staging"
install -d -m 700 "$ETC_DIR" "$BACKUP_ROOT" /var/lib/cadrius
clone_or_update() { # url dir branch
  if [ -d "$2/.git" ]; then git -C "$2" fetch --prune origin >/dev/null 2>&1 || warn "fetch falhou em $2"
  else git clone "$1" "$2" || die "Não consegui clonar $1. Repositório privado? Gere uma deploy key:
   ssh-keygen -t ed25519 -f /root/.ssh/cadrius_deploy -N '' ; cat /root/.ssh/cadrius_deploy.pub
   → GitHub > Settings > Deploy keys (somente leitura) e use a URL SSH (git@github.com:org/repo.git)."
  fi
}
clone_or_update "$BACK_REPO" "$ROOT/infra"
git -C "$ROOT/infra" checkout -q main 2>/dev/null || true
git -C "$ROOT/infra" reset -q --hard origin/main 2>/dev/null || warn "branch main ainda não existe: usando o checkout atual para o kit de deploy"
# Se o kit ainda não está na main (CAD-104 em revisão), use o diretório de onde o bootstrap foi executado
if [ ! -f "$ROOT/infra/deploy/scripts/deploy.sh" ]; then
  warn "kit deploy/ não encontrado em origin/main — copiando de $HERE/.."
  rsync -a --exclude .git "$HERE/" "$ROOT/infra/deploy/" 2>/dev/null || { mkdir -p "$ROOT/infra/deploy"; cp -a "$HERE/." "$ROOT/infra/deploy/"; }
fi
for e in prod staging; do
  clone_or_update "$BACK_REPO" "$ROOT/$e/backend"
  clone_or_update "$FRONT_REPO" "$ROOT/$e/frontend"
done
chmod +x "$ROOT"/infra/deploy/scripts/*.sh "$ROOT"/infra/deploy/backup/*.sh "$ROOT"/infra/deploy/infra/*.sh "$ROOT"/infra/deploy/bootstrap.sh 2>/dev/null || true
git config --system --add safe.directory '*'
chown -R deploy:deploy "$ROOT"

# ---------------------------------------------------------------- 6. Segredos
log "6/10 segredos"
INFRA_ENV="$ROOT/infra/.env"
urlenc() { jq -rn --arg s "$1" '$s|@uri'; }
touch "$CRED"; chmod 600 "$CRED"

if [ ! -f "$INFRA_ENV" ]; then
  mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  sb=$((mem_mb/4)); ec=$((mem_mb*3/8)); [ "$sb" -gt 4096 ] && sb=4096
  dz_pass="$(rand_alnum 20)"; dz_hash="$(htpasswd -nbB admin "$dz_pass" | sed 's/\$/$$/g')"
  cp "$ROOT/infra/deploy/infra/.env.example" "$INFRA_ENV"
  sed -i -e "s|^ROOT_DOMAIN=.*|ROOT_DOMAIN=$DOMAIN|" -e "s|^ACME_EMAIL=.*|ACME_EMAIL=$ACME_EMAIL|" \
         -e "s|^POSTGRES_SUPERUSER_PASSWORD=.*|POSTGRES_SUPERUSER_PASSWORD=$(rand_alnum 40)|" \
         -e "s|^PG_SHARED_BUFFERS=.*|PG_SHARED_BUFFERS=${sb}MB|" -e "s|^PG_EFFECTIVE_CACHE_SIZE=.*|PG_EFFECTIVE_CACHE_SIZE=${ec}MB|" \
         -e "s|^PG_MEM_LIMIT=.*|PG_MEM_LIMIT=$((mem_mb/2))M|" "$INFRA_ENV"
  # hash contém '$' e '|': grava por linha para não quebrar o sed
  grep -v '^DOZZLE_BASIC_AUTH=' "$INFRA_ENV" >"$INFRA_ENV.tmp"; echo "DOZZLE_BASIC_AUTH=$dz_hash" >>"$INFRA_ENV.tmp"; mv "$INFRA_ENV.tmp" "$INFRA_ENV"
  { echo "Dozzle (https://logs.$DOMAIN)  usuário: admin  senha: $dz_pass"; } >>"$CRED"
fi
[ "$ACME_STAGING" = 1 ] && sed -i 's|^ACME_CASERVER=.*|ACME_CASERVER=https://acme-staging-v02.api.letsencrypt.org/directory|' "$INFRA_ENV"
chmod 600 "$INFRA_ENV"

make_env() { # prod|staging
  local e="$1" f="$ROOT/$1/.env" app api dbu dbn
  [ -f "$f" ] && { ok "$f já existe (mantido)"; return; }
  if [ "$e" = prod ]; then app="$PROD_HOST_APP"; api="$PROD_HOST_API"; dbu=cadrius_prod; dbn=cadrius_prod
  else app="$STG_HOST_APP"; api="$STG_HOST_API"; dbu=cadrius_staging; dbn=cadrius_staging; fi
  local dbpw; dbpw="$(rand_alnum 40)"
  render_template "$ROOT/infra/deploy/app/env.backend.template" "$f" \
    "ENV=$e" "APP_HOST=$app" "API_HOST=$api" "DB_USER=$dbu" "DB_NAME=$dbn" "DB_PASSWORD_URLENC=$(urlenc "$dbpw")" \
    "DJANGO_ENV=$([ "$e" = prod ] && echo production || echo staging)" \
    "DJANGO_SECRET_KEY=$(rand_django)" "ENCRYPTION_KEY=$(rand_fernet)" "BLIND_INDEX_KEY=$(rand_alnum 48)" "REDIS_PASSWORD=$(rand_alnum 32)" "EVOLUTION_KEY=$(rand_alnum 40)"
  echo "DB_PASSWORD_RAW=$dbpw" >>"$f"   # usado só pelo provision-db.sh
  chmod 600 "$f"; chown deploy:deploy "$f"
  ok "$f criado"
}
make_env prod; make_env staging
BK_PW="$(env_get "$ETC_DIR/backup.env" BACKUP_DB_PASSWORD 2>/dev/null || true)"; [ -n "$BK_PW" ] || BK_PW="$(rand_alnum 40)"

# ---------------------------------------------------------------- 7. GPG + backup.env
log "7/10 chave pública de backup"
GNUPGHOME_SYS=/root/.gnupg; install -d -m 700 "$GNUPGHOME_SYS"
FPR="$(gpg --batch --with-colons --import-options show-only --import "$GPG_PUB" 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')"
[ -n "$FPR" ] || die "Não consegui ler a chave pública $GPG_PUB"
gpg --batch --quiet --import "$GPG_PUB"
if [ ! -f "$ETC_DIR/backup.env" ]; then
  cp "$ROOT/infra/deploy/backup/backup.env.example" "$ETC_DIR/backup.env"
fi
sed -i -e "s|^BACKUP_GPG_RECIPIENT=.*|BACKUP_GPG_RECIPIENT=$FPR|" -e "s|^BACKUP_DB_PASSWORD=.*|BACKUP_DB_PASSWORD=$BK_PW|" "$ETC_DIR/backup.env"
chmod 600 "$ETC_DIR/backup.env"
ok "backups serão cifrados para a chave $FPR (a privada NÃO está neste servidor)"

# ---------------------------------------------------------------- 8. Infra (Traefik + Postgres + Dozzle)
log "8/10 infraestrutura compartilhada"
docker network inspect proxy_net >/dev/null 2>&1 || docker network create proxy_net >/dev/null
docker network inspect db_net >/dev/null 2>&1 || docker network create --internal db_net >/dev/null
(cd "$ROOT/infra/deploy/infra" && docker compose --project-name cadrius-infra --env-file "$INFRA_ENV" up -d)
log "aguardando o PostgreSQL"
for i in $(seq 1 40); do docker exec cadrius_postgres pg_isready -U postgres >/dev/null 2>&1 && break; sleep 3; done
docker exec cadrius_postgres pg_isready -U postgres >/dev/null || die "PostgreSQL não ficou pronto (docker logs cadrius_postgres)"

PROD_DB_PASSWORD="$(env_get "$ROOT/prod/.env" DB_PASSWORD_RAW)" STG_DB_PASSWORD="$(env_get "$ROOT/staging/.env" DB_PASSWORD_RAW)" \
  BACKUP_DB_PASSWORD="$(env_get "$ETC_DIR/backup.env" BACKUP_DB_PASSWORD)" "$ROOT/infra/deploy/infra/provision-db.sh"
ok "bancos cadrius_prod e cadrius_staging prontos (papéis de menor privilégio + usuário de backup somente-leitura)"

# ---------------------------------------------------------------- 9. Backups automáticos
log "9/10 backups automáticos (systemd)"
cp "$ROOT"/infra/deploy/backup/systemd/*.service "$ROOT"/infra/deploy/backup/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cadrius-backup-prod.timer cadrius-backup-staging.timer cadrius-verify-restore.timer cadrius-verify-offsite.timer >/dev/null
ok "timers: prod a cada 6 h, teste diário, teste de restauração semanal"
printf '#!/bin/sh\nexec %s/infra/deploy/scripts/status.sh "$@"\n' "$ROOT" >/usr/local/bin/cadrius-status && chmod +x /usr/local/bin/cadrius-status

# ---------------------------------------------------------------- 10. DNS + deploy
log "10/10 DNS e primeiro deploy"
PUB_IP="$(curl -fsS -4 https://api.ipify.org 2>/dev/null || curl -fsS -4 https://ifconfig.me 2>/dev/null || echo '')"
dns_ok=1
for h in "$PROD_HOST_APP" "$PROD_HOST_API" "$STG_HOST_APP" "$STG_HOST_API" "logs.$DOMAIN"; do
  ip="$(dig +short +time=3 +tries=1 A "$h" 2>/dev/null | tail -1 || true)"
  if [ -n "$PUB_IP" ] && [ "$ip" = "$PUB_IP" ]; then ok "DNS $h → $ip"
  else warn "DNS $h → '${ip:-sem registro}' (esperado $PUB_IP)"; dns_ok=0; fi
done
if [ "$dns_ok" = 0 ] && [ "$SKIP_DNS" = 0 ]; then
  warn "DNS incorreto: o Let's Encrypt FALHARIA e poderia bloquear o domínio por excesso de tentativas."
  warn "Corrija os registros A (veja deploy/README.md) e rode:  sudo $ROOT/infra/deploy/scripts/deploy.sh staging && ... prod"
  SKIP_DEPLOY=1
fi
if [ "$SKIP_DEPLOY" = 0 ]; then
  "$ROOT/infra/deploy/scripts/deploy.sh" staging
  "$ROOT/infra/deploy/scripts/deploy.sh" prod
fi

echo
ok "BOOTSTRAP CONCLUÍDO"
echo "Credenciais geradas (somente root): $CRED"
echo "Edite as chaves de terceiros (OpenAI, Stripe, Sentry...) em $ROOT/{prod,staging}/.env e rode deploy.sh de novo."
echo "Verificação geral:  sudo cadrius-status"
