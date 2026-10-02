#!/bin/bash
# app-db: your app's database as an HTTP API (app-db/), which the gateway
# serves at /app-db/. It logs in to Postgres as the role app, migrates the
# app's schema, and asks every caller for APP_DB_API_KEY.
source "$(dirname "$0")/lib.sh"
log_as app-db
wait_for_db
cd /opt/app-db

# The password goes in PGPASSWORD rather than the URL, so that it needs no
# percent-encoding.
export DATABASE_URL="postgresql://app@${DB_HOST}:${DB_PORT}/${DB_NAME}"
export PGPASSWORD=$APP_DB_PASSWORD
export APP_DB_API_KEY

# The gateway's log already has every request: uvicorn's own would add a line
# for each health check as well.
exec .venv/bin/uvicorn api:app --host 127.0.0.1 --port "$APP_DB_API_PORT" \
    --root-path /app-db --no-server-header --no-access-log
