# CLAUDE.md: single-docker-supabaseREST

The 11 services of Supabase's self-hosted `docker-compose.yml` in **one Docker
image** (supervisord, the services behind the gateway on `127.0.0.1`), which
publishes **only 9876**, the Envoy gateway, over plain HTTP. The platform's
ingress adds TLS.

Raw `postgres://` can't pass an HTTP-only ingress. The app reaches its data
through **PostgREST** (`/rest/v1/`) instead, in the schema `app`, owned by the
nologin role `app`, with a JWT for that role (`APP_KEY`). There is no custom
API code. The user docs are in `README.md`.

## Map

- It is `../single-docker-multiple-port` plus the schema overlay below, with `EXPOSE 9876` only. `config/envoy/`, `config/db/`, `config/pooler.exs`, `functions/` and most `services/*.sh` are identical to it. There is no `99-app.sql` and no `APP_DB_PASSWORD`.
- `services/schema.sh` (supervisord `[program:schema]`, priority 15, one-shot): as `supabase_admin` over the Unix socket (trusted in `pg_hba.conf`), it creates role `app` (nologin) and schema `app`, then runs `grant app to authenticator` and `grant app to postgres`. It then applies each `/etc/app-schema/migrations/*.sql` not yet in `app.schema_migrations`, in name order, one transaction each, as role `app` with `search_path = app`.
- `config/app-schema/`: the numbered SQL files, copied by the Dockerfile to `/etc/app-schema/migrations/`. `0001_example.sql` is an `items` table, plus a commented RLS recipe.
- `services/rest.sh` and `services/studio.sh`: append `app` to `PGRST_DB_SCHEMAS` if it's missing.
- `healthcheck.sh`: the 11 service checks, plus "is the newest migration file recorded?".
- `utils/app-key.sh`: mints `APP_KEY`, an HS256 JWT `{"role":"app","iss":"supabase"}` valid 5 years, signed with `JWT_SECRET` from `.env`. It also prints `SUPABASE_ANON_KEY`.

## Build, run, test

```bash
cp .env.example .env && sh utils/generate-keys.sh --update-env
sh utils/app-key.sh                                                # SUPABASE_ANON_KEY, APP_KEY
docker build -t supabase-rest .
docker run -d --name supabase --env-file .env -p 9876:9876 -v supabase-data:/home/supabase/data supabase-rest
docker exec supabase ./healthcheck.sh                              # "All 11 services are up, and the schema app too."
curl localhost:9876/rest/v1/items -H "apikey: $ANON_KEY" -H "Authorization: Bearer $APP_KEY" -H "Accept-Profile: app"
```

Expected denials, worth checking after a change: on `/rest/v1/`, the anon key
alone, or the service key, gets `permission denied for schema app`; no
`apikey` gets `401` from the gateway; `/graphql/v1` with `APP_KEY` gets
`permission denied for schema graphql_public`. (The service key still reaches
`app` through `/pg/`, postgres-meta, which logs in as `postgres`.)

Syntax check for the scripts: `for f in *.sh services/*.sh utils/*.sh; do bash -n "$f"; done`.

## Invariants and gotchas

- **Client pattern:** `apikey: ANON_KEY` satisfies the gateway's key check, and `Authorization: Bearer APP_KEY` sets PostgREST's role. The gateway leaves `Authorization` untouched only if it starts with exactly `Bearer ` (case-sensitive) and isn't `Bearer sb_…`; anything else becomes `Bearer <apikey>`, so a lowercase `bearer` silently runs as anon. `APP_KEY` can never go in `apikey`, because the gateway accepts only Supabase's own keys there. The schema is picked with `Accept-Profile` / `Content-Profile: app`.
- **`APP_KEY` is server-side only.** CORS on the gateway allows any origin.
- **Schema changes:** add `config/app-schema/000N_<what>.sql`, never edit an applied file, and rebuild. They are applied at the next start, also to an existing database. Don't use `if not exists`-style guards to paper over a changed file.
- Isolation comes from ownership and the missing grants, not from RLS. `app` owns its tables, so RLS doesn't limit it. Don't grant anon, authenticated or service_role anything on `app` unless the user asks for it. Migration files run as `app`, so they can't grant `app` anything outside its schema: such grants (e.g. `grant usage on schema auth to app`, which the RLS recipe in `0001_example.sql` needs) go in the supabase_admin SQL block of `schema.sh`.
- **Bind addresses:** Postgres, Realtime and Supavisor listen on every interface (their images' defaults); the rest on 127.0.0.1. Nothing inside uses the pooler. Postgres trusts every login over 127.0.0.1 (the image's `pg_hba.conf`).
- **Settings come from the runtime environment.** `~/.env` is loaded only if baked in (`--secret id=dotenv,src=.env --build-arg BAKE_ENV="$(date +%s)"`). `.env` is docker-ignored, so never `COPY` it. The loader reads lines **literally**.
- **HTTP ports live in two places:** `services/lib.sh` and `config/envoy/cds.yaml`. Postgres's and the pooler's are `.env` settings; Envoy admin is in `envoy.yaml`; 9876 is also in `EXPOSE`.
- **All services share one PID namespace.** `services/db.sh` therefore removes a stale `postmaster.pid` and socket lock file before starting Postgres. A running Postgres shows in `/proc/<pid>/comm` as `.postgres-wrapp`.
- A new `JWT_SECRET` invalidates `APP_KEY`: run `app-key.sh` again. Re-running `generate-keys.sh` also changes `POSTGRES_PASSWORD`, which an existing database doesn't take.
- Keep it generic: role and schema `app`, tenant `your-tenant-id`, `*.example.com`. No project names, real domains or secrets.
