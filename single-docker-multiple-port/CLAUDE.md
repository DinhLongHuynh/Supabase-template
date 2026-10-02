# CLAUDE.md: single-docker-multiple-port

The 11 services of Supabase's self-hosted `docker-compose.yml` in **one Docker
image**, run by supervisord; the services reach each other on `127.0.0.1`. It
publishes 9876 (the Envoy gateway, over HTTP), plus 5432 (Postgres), 5433 and
6543 (the Supavisor pooler, over TCP). The user docs are in `README.md`.

## Map

- `Dockerfile`: `FROM <official image> AS <name>` per service, then `COPY --from` of each program onto `debian:trixie-slim`. The only compile step is `npm rebuild fs-xattr` (stage `storage-glibc`, `node:<ver>-trixie`), which rebuilds Storage's native module for glibc. The final image has no `.env` unless it is baked (see below).
- `start-script.sh` (the CMD): checks the required variables, prepares `DATA_DIR`, then runs `exec supervisord`.
- `supervisord.conf`: one `[program:x]` per service. Priorities: db 10; the APIs and pooler 20; studio 30; gateway 40.
- `services/lib.sh`: the env loader, the **port table**, `log_as`, `wait_for_db`. `services/<x>.sh`: maps `.env` names to the service's own env, as compose's `environment:` did.
- `config/envoy/`:
  - `cds.yaml`: the clusters, on `127.0.0.1` with **hardcoded ports**.
  - `lds.template.yaml`: the routes. Its `${…}` placeholders are filled by `services/gateway.sh` with `sed`.
- `config/db/`: upstream init SQL, plus `migrations/99-app.sql` (role and schema `app`). `config/pooler.exs` recreates the Supavisor tenant on every start.
- `healthcheck.sh`: one check per service, the way compose's healthchecks did it (meta's `/health` check is new: compose has none).

## Build and run

```bash
cp .env.example .env && sh utils/generate-keys.sh --update-env
docker build -t supabase-multi-port .
docker run -d --name supabase --env-file .env -p 9876:9876 -p 5432:5432 -p 5433:5433 -p 6543:6543 \
    -v supabase-data:/home/supabase/data supabase-multi-port
docker exec supabase ./healthcheck.sh      # "All 11 services are up."
docker logs -f supabase                    # each service's lines are prefixed with [service]
```

Syntax check for the scripts: `for f in *.sh services/*.sh utils/*.sh; do bash -n "$f"; done`.

## Invariants and gotchas

- **Settings come from the runtime environment.** `lib.sh` also loads `~/.env` if it exists (a baked image), and a variable already set to a non-empty value wins. The loader reads lines **literally**: no quotes, no `${VAR}`, no `export` prefix.
- **Baking is opt-in:** `docker build --secret id=dotenv,src=.env --build-arg BAKE_ENV="$(date +%s)"`. `.env` is in `.dockerignore`, so never `COPY` it. Secrets don't count toward the cache key, which is why `BAKE_ENV` must change on every bake.
- **HTTP ports live in two places:** `services/lib.sh` and `config/envoy/cds.yaml`. Change both. Postgres's and the pooler's ports are `.env` settings (`POSTGRES_PORT`, `POOLER_PROXY_PORT_*`, defaults in `services/pooler.sh`); Envoy admin is in `envoy.yaml`; published ports are also in the Dockerfile's `EXPOSE`. Renumbered to avoid clashes: PostgREST 3001/3002, pooler API 4001, storage admin 5002, pooler session 5433. postgres-meta also listens on 8081.
- **Bind addresses:** auth, rest, storage, imgproxy, meta, functions, studio and Envoy admin are on 127.0.0.1. Postgres, Realtime and Supavisor keep their images' defaults (every interface). Postgres trusts every login over 127.0.0.1 (the image's `pg_hba.conf`), so anything in the container can log in as any role.
- The init SQL runs **only when `PGDATA` is empty**, so passwords set later do nothing to the database.
- **All services share one PID namespace.** `services/db.sh` therefore removes a stale `postmaster.pid` and socket lock file before starting Postgres. A running Postgres shows in `/proc/<pid>/comm` as `.postgres-wrapp` (its Nix wrapper), not `postgres`.
- **Studio must stay at `/`**: its prebuilt assets use absolute paths.
- **Adding a service** touches the `Dockerfile` (a stage and `COPY --from`), `services/<x>.sh`, `supervisord.conf`, `lib.sh` (its port), `cds.yaml`, `lds.template.yaml` (route before the catch-all `/`) and `healthcheck.sh` (and its "All 11" message). `app-db` in the sibling folder `../single-docker-single-port-wrap-by-https` is a worked example.
- **Upgrading Supabase:** copy the image tags from upstream `docker-compose.yml` into the `FROM` lines, set `node:<ver>-trixie` to the new Storage image's Node version (meta runs on Studio's Node), then diff each service's `environment:` against its script.
- Keep it generic: no project names, real domains or secrets in files. `.env` and `.env.old` are git- and docker-ignored.
