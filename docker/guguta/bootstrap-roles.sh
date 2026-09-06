#!/bin/bash
# Guguță role bootstrap — runs once at first PostgreSQL container init.
# Creates the runtime roles if absent and sets their dev passwords.
# Staging/production override GUGUTA_PG_API_PASSWORD / GUGUTA_PG_WORKER_PASSWORD
# in .env; migration 0001 also creates the roles idempotently for non-compose
# environments (tests), so this script stays optional.
set -euo pipefail

API_PASSWORD="${GUGUTA_PG_API_PASSWORD:-guguta_dev_api}"
WORKER_PASSWORD="${GUGUTA_PG_WORKER_PASSWORD:-guguta_dev_worker}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guguta_api') THEN
            CREATE ROLE guguta_api LOGIN;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guguta_worker') THEN
            CREATE ROLE guguta_worker LOGIN;
        END IF;
    END
    \$\$;
    ALTER ROLE guguta_api WITH PASSWORD '$API_PASSWORD';
    ALTER ROLE guguta_worker WITH PASSWORD '$WORKER_PASSWORD';
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
EOSQL

echo "guguta: runtime roles bootstrapped (api, worker)"
