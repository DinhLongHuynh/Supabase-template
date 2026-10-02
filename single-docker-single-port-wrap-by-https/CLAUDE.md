# CLAUDE.md: single-docker-single-port-wrap-by-https

The 11 services of Supabase's self-hosted `docker-compose.yml` in **one Docker
image** (supervisord; the services reach each other on `127.0.0.1`), which
publishes **only 9876**, the Envoy gateway, over plain HTTP. The platform's
ingress adds TLS.

Raw `postgres://` can't pass an HTTP-only ingress. The app's data is
therefore served by **`app-db`** (FastAPI on `127.0.0.1:8001`, under
`/app-db/`, with an `X-API-Key` check). The user docs are in `README.md`.

## Map

- `Dockerfile`: one `FROM <official image> AS <name>` per service, a `storage-glibc` stage (`npm rebuild fs-xattr`), a uv stage that builds `app-db`'s venv for Debian's `python3`, then `COPY --from` onto `debian:trixie-slim`. It has `EXPOSE 9876` only.
- `app-db/`: `api.py` (routes and the key check), `store.py` (queries; runs Alembic `upgrade head` at startup or on the first request), `models.py` (the example table `items`), `migrations/`, `tests/` (SQLite).
- `services/app-db.sh`: runs uvicorn with `--root-path /app-db`, logged in as role `app` (`PGPASSWORD=$APP_DB_PASSWORD`).
- `config/envoy/lds.template.yaml`:
  - the `/app-db/` route has basic auth disabled, an allow-all RBAC override, and isn't in the Lua `PROTECTED_ROUTES`, because app-db checks its own key;
  - an exact `/studio` route goes to Studio's `/`;
  - the catch-all `/` goes to Studio, behind the dashboard login.
- `config/envoy/cds.yaml`: the `app-db` cluster, health-checked on `/health`.
- The rest is the multi-port image's, plus app-db's additions: its port (`APP_DB_API_PORT=8001`) in `services/lib.sh`, `[program:app-db]` in `supervisord.conf`, a 12th check in `healthcheck.sh`, `APP_DB_API_KEY` in `utils/generate-keys.sh`, `.env.example` and `start-script.sh` (which also requires `APP_DB_PASSWORD` on every start, not only the first), and app-db's venv and tests in `.dockerignore`. Unchanged: `config/db/` (with `migrations/99-app.sql`), `config/pooler.exs`, the other `services/*.sh`.

## Build, run, test

```bash
cp .env.example .env && sh utils/generate-keys.sh --update-env    # APP_DB_PASSWORD and APP_DB_API_KEY too
docker build -t supabase-single-port .
docker run -d --name supabase --env-file .env -p 9876:9876 -v supabase-data:/home/supabase/data supabase-single-port
docker exec supabase ./healthcheck.sh                              # "All 12 services are up."
curl localhost:9876/app-db/health                                  # {"status":"ok"}
cd app-db && uv sync && uv run pytest                              # API and store tests, on SQLite
```

To run the store tests against Postgres, set `TEST_DATABASE_URL` to a
throwaway database.

## Invariants and gotchas

- **Settings come from the runtime environment.** `~/.env` is loaded only if baked in (`--secret id=dotenv,src=.env --build-arg BAKE_ENV="$(date +%s)"`). `.env` is docker-ignored, so never `COPY` it. The loader reads lines **literally**: no quotes, no `${}`.
- `start-script.sh` requires `APP_DB_PASSWORD` and `APP_DB_API_KEY`. With no key, every keyed route answers 401; it never fails open. `/health`, `/docs`, `/redoc` and `/openapi.json` need no key.
- **Changing app-db's schema:** edit `models.py`, add an Alembic revision in `migrations/versions/`, and update `store.py`, `api.py` and the tests. Never run DDL from the app code.
- The init SQL (`99-app.sql`, which creates role and schema `app`) runs **only when `PGDATA` is empty**.
- PostgREST serves only `public` and `graphql_public`. Keep private tables in schema `app`.
- **HTTP ports live in two places:** `services/lib.sh` and `config/envoy/cds.yaml`. Postgres's and the pooler's are `.env` settings; Envoy admin is in `envoy.yaml`; 9876 is also in `EXPOSE`.
- **Bind addresses:** Postgres, Realtime and Supavisor listen on every interface (their images' defaults); the rest on 127.0.0.1. Postgres trusts every login over 127.0.0.1 (the image's `pg_hba.conf`), so `APP_DB_PASSWORD` isn't checked for app-db's own login.
- **Route order matters** in `lds.template.yaml`, because the first match wins. New routes go before `/api/mcp` and the catch-all `/`.
- **The `/app-db/` route disables basic auth and overrides RBAC** to allow everything. Without that, the global basic-auth filter would ask for the dashboard login, and the global RBAC filter, which allows only Supabase's keys, would deny every request. app-db checks `X-API-Key` itself.
- **All services share one PID namespace.** `services/db.sh` therefore removes a stale `postmaster.pid` and socket lock file before starting Postgres. A running Postgres shows in `/proc/<pid>/comm` as `.postgres-wrapp` (its Nix wrapper).
- **Studio must stay at `/`.** The exact path `/studio` is proxied to Studio's `/` (`prefix_rewrite`), which redirects to `/project/default`.
- **Adding a service:** follow `app-db`. It touches the Dockerfile, `services/<x>.sh`, `supervisord.conf`, `lib.sh`, `cds.yaml`, `lds.template.yaml` (with basic auth off and an RBAC override if it does its own auth) and `healthcheck.sh` (and its "All 12" message).
- Keep it generic: no project names, real domains or secrets. `.env`, `.env.old` and `app-db/.venv` are ignored.
