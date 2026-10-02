#!/usr/bin/env bash
# Provisiona (IDEMPOTENTE) papéis e bancos: produção, teste e usuário somente-leitura de backup.
# Pode rodar quantas vezes quiser: cria o que falta e SINCRONIZA as senhas com os arquivos .env.
#
# Uso (como root/deploy, após o Postgres estar saudável):
#   PROD_DB_PASSWORD=... STG_DB_PASSWORD=... BACKUP_DB_PASSWORD=... ./provision-db.sh
# Modo local para testes (sem Docker):  CADRIUS_PG_MODE=local PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=...
set -Eeuo pipefail

: "${PROD_DB_PASSWORD:?}" "${STG_DB_PASSWORD:?}" "${BACKUP_DB_PASSWORD:?}"
PG_CONTAINER="${PG_CONTAINER:-cadrius_postgres}"

psql_admin() {
  if [ "${CADRIUS_PG_MODE:-docker}" = "local" ]; then
    psql -X -v ON_ERROR_STOP=1 -d postgres "$@"
  else
    docker exec -i "$PG_CONTAINER" psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"
  fi
}

# role  senha  banco(opcional)
ensure_role_and_db() {
  local role="$1" pw="$2" db="${3:-}"
  psql_admin -v role="$role" -v pw="$pw" -v db="$db" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role', :'pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'role', :'pw') \gexec
SELECT CASE WHEN :'db' <> '' THEN format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0', :'db', :'role') END
 WHERE :'db' <> '' AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SELECT CASE WHEN :'db' <> '' THEN format('ALTER DATABASE %I OWNER TO %I', :'db', :'role') END WHERE :'db' <> '' \gexec
SELECT CASE WHEN :'db' <> '' THEN format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db') END WHERE :'db' <> '' \gexec
SELECT format('ALTER ROLE %I SET statement_timeout = ''60s''', :'role') WHERE :'db' <> '' \gexec
SELECT format('ALTER ROLE %I SET idle_in_transaction_session_timeout = ''60s''', :'role') WHERE :'db' <> '' \gexec
SQL
}

echo ">> papéis e bancos"
ensure_role_and_db cadrius_prod     "$PROD_DB_PASSWORD" cadrius_prod
ensure_role_and_db cadrius_staging  "$STG_DB_PASSWORD"  cadrius_staging
ensure_role_and_db cadrius_backup   "$BACKUP_DB_PASSWORD"

# O usuário de backup só LÊ (pg_read_all_data, PG14+) e só nos dois bancos; cada app só acessa o próprio banco.
psql_admin <<'SQL'
GRANT pg_read_all_data TO cadrius_backup;
GRANT CONNECT ON DATABASE cadrius_prod, cadrius_staging TO cadrius_backup;
REVOKE CONNECT ON DATABASE cadrius_prod FROM cadrius_staging;
REVOKE CONNECT ON DATABASE cadrius_staging FROM cadrius_prod;
SQL
# O statement_timeout de 60s é do app; backups/pg_dump usam o papel dedicado (sem esse limite).
psql_admin -c "ALTER ROLE cadrius_backup RESET statement_timeout"
echo ">> ok: cadrius_prod, cadrius_staging, cadrius_backup"
