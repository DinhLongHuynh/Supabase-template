#!/bin/bash
# schema: the schema app, where your app keeps its tables, reached through
# the REST API with the role app's key (utils/app-key.sh). Creates the role
# and the schema if needed, applies each file of config/app-schema/ that the
# database hasn't had yet, in name order, then exits.
#
# It runs at every start, so a new file reaches a database that already
# exists: to change the tables, add a file with the next number and rebuild.
# Never edit one that a database has had. Each file runs in one transaction,
# as app, and is recorded in app.schema_migrations.
source "$(dirname "$0")/lib.sh"
log_as schema
set -euo pipefail
wait_for_db

MIGRATIONS=/etc/app-schema/migrations

# As supabase_admin over the socket, which needs no password (pg_hba.conf).
sql() {
    PGOPTIONS="-c client_min_messages=warning" \
        psql -X -q -v ON_ERROR_STOP=1 -h /var/run/postgresql -U supabase_admin -d "$DB_NAME" "$@"
}

sql <<'SQL'
do $$
begin
    if not exists (select from pg_roles where rolname = 'app') then
        create role app nologin;
    end if;
end
$$;
create schema if not exists app authorization app;
-- PostgREST logs in as authenticator, then takes the role that the request's
-- key names: app, for your app's key.
grant app to authenticator;
-- Studio's Table Editor and SQL editor connect as postgres.
grant app to postgres;
create table if not exists app.schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);
SQL

for file in "$MIGRATIONS"/*.sql; do
    version=$(basename "$file" .sql)
    applied=$(sql -tA -c "select 1 from app.schema_migrations where version = '$version'")
    [ -z "$applied" ] || continue
    echo "Applying $version"
    sql --single-transaction \
        -c "set role app" -c "set search_path = app" \
        -f "$file" \
        -c "reset role" \
        -c "insert into app.schema_migrations (version) values ('$version')"
done
echo "The schema app is up to date"
