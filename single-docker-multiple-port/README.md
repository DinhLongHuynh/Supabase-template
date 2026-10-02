# Self-hosted Supabase: Template for one Docker image (several exposed ports)

## Overview

This packs Supabase's whole self-hosted stack (Postgres, Studio, the API
gateway and 8 more services) into a **single Docker image**.

Use it when the hosting platform runs one container per app, can't run Docker
Compose, **but can publish several ports**, raw TCP included. Your app then
connects with a `postgres://` URL.

```mermaid
flowchart LR
    client(["Your app / browser"])
    tools(["psql / your app's<br/>Postgres driver"])

    subgraph container ["One container, supervised by supervisord"]
        gw["Envoy gateway :9876"]
        subgraph local ["127.0.0.1 only"]
            studio["Studio :3000"]
            auth["Auth :9999"]
            rest["PostgREST :3001"]
            storage["Storage :5000"]
            imgproxy["imgproxy :5001"]
            meta["postgres-meta :8080"]
            functions["Edge runtime :9000"]
        end
        realtime["Realtime :4000<br/>(not published)"]
        pooler["Supavisor<br/>:5433 session, :6543 transaction"]
        db[("Postgres :5432")]
    end
    data[/"volume<br/>/home/supabase/data"/]

    client -->|"HTTP :9876"| gw
    tools -->|"postgres:// :5432"| db
    tools -->|"postgres:// :5433, :6543"| pooler
    gw --> studio & auth & rest & realtime & storage & functions & meta
    studio -->|"SQL, tables"| meta
    storage --> imgproxy
    auth & rest & realtime & storage & meta & pooler --> db
    db & storage --- data
```

Realtime, Supavisor and Postgres listen on every interface of the container
(the others on 127.0.0.1), but only the ports below are published.

Published ports:

| Port | What | Protocol |
|---|---|---|
| **9876** | Envoy gateway: Studio and every API | HTTP |
| **5432** | Postgres itself | Postgres (TCP) |
| **5433** | Supavisor, session mode (5432 in compose; Postgres has 5432 here) | Postgres (TCP) |
| **6543** | Supavisor, transaction mode | Postgres (TCP) |

---

## Quick Start

You need Docker Desktop and `openssl`.

### Step 1: Config setting
```bash
cd single-docker-multiple-port
cp .env.example .env
sh utils/generate-keys.sh --update-env
```

### Step 2: Build image
```bash
docker build -t supabase-multi-port:v1 .
```

### Step 3: Run container
```bash
docker run -d --name supabase \
    --env-file .env \
    -p 9876:9876 -p 5432:5432 -p 5433:5433 -p 6543:6543 \
    -v supabase-data:/home/supabase/data \
    supabase-multi-port:v1
```

### Step 4: Healthy check 
Wait for "healthy" (about 20s locally; longer on the very first start).

```bash
docker ps --filter name=supabase
docker exec supabase ./healthcheck.sh     # lists any service that isn't up yet
```

Then, load the values the commands below use (don't source .env: some values contain spaces).

```bash
export $(grep -E '^(ANON_KEY|APP_DB_PASSWORD|POOLER_TENANT_ID)=' .env | xargs)
```

### Step 5: Access the Studio and database
- **Studio:** <http://localhost:9876>. Log in with `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`.
- **APIs:** `http://localhost:9876/rest/v1/<table>`, `/auth/v1/…`, `/storage/v1/…` with the header `apikey: $ANON_KEY`. (The root `/rest/v1/` itself needs the service key.)
- **Your app's database login** (role `app`, schema `app`):

  ```bash
  psql "postgres://app:$APP_DB_PASSWORD@localhost:5432/postgres"                          # direct
  psql "postgres://app.$POOLER_TENANT_ID:$APP_DB_PASSWORD@localhost:5433/postgres"        # pooled, session mode
  psql "postgres://app.$POOLER_TENANT_ID:$APP_DB_PASSWORD@localhost:6543/postgres"        # pooled, transaction mode
  ```

---

## Details

### Files

| File | What it does |
|---|---|
| `Dockerfile` | One stage per service image, at the versions upstream `docker-compose.yml` pins, plus one that rebuilds Storage's native module for glibc. It copies each program onto `debian:trixie-slim`, then creates the user `supabase` (uid 1000) and the data folder. |
| `start-script.sh` | The `CMD`. Checks the required settings, prepares the data folder, then `exec supervisord`. |
| `supervisord.conf` | The 11 programs, their start order (priorities) and how each one is stopped. |
| `services/lib.sh` | Sourced by every script: loads the settings, the **port table**, `log_as` (prefixes log lines), `wait_for_db`. |
| `services/<name>.sh` | One per service: the environment compose gave it, with every other service on `127.0.0.1`. |
| `healthcheck.sh` | The Docker `HEALTHCHECK`: checks each service the way its compose healthcheck did (plus `/health` for postgres-meta, which has none in compose). |
| `config/envoy/` | The gateway's clusters (`cds.yaml`) and routes (`lds.template.yaml`, filled in by `services/gateway.sh`). |
| `config/db/` | Init SQL from upstream `volumes/db/`, plus `migrations/99-app.sql` (your app's role and schema). |
| `config/pooler.exs` | Supavisor's tenant. It is deleted and recreated on every start, so it always matches `.env`. |
| `functions/` | Edge functions: `main/` (the router) and `hello/` (an example). |
| `utils/generate-keys.sh` | Generates every secret into `.env` (not copied into the image). |

### Ports inside the container

Everything shares one network address, so ports that each had their own
container in compose would clash. A few are moved:

| Service | Port | In compose |
|---|---|---|
| **Envoy gateway (published)** | **9876** | 8000 |
| Studio | 3000 | 3000 |
| PostgREST / its admin | **3001** / **3002** | 3000 / 3001 |
| Realtime | 4000 | 4000 |
| Supavisor API | **4001** | 4000 |
| Storage / its admin | 5000 / **5002** (set, but not listening by default) | 5000 / 5001 |
| imgproxy | 5001 | 5001 |
| postgres-meta | 8080 (and 8081) | 8080 |
| Edge runtime | 9000 | 9000 |
| Auth | 9999 | 9999 |
| Envoy admin | 9901 (127.0.0.1) | 9901 |
| Postgres | 5432 | 5432 (not published) |
| Supavisor session / transaction | **5433** / 6543 | 5432 / 6543 |

> [!NOTE]
> The services' HTTP ports are written in two places: `services/lib.sh` and
> `config/envoy/cds.yaml`. Change both together. Postgres's and the pooler's
> ports are `.env` settings (`POSTGRES_PORT`, `POOLER_PROXY_PORT_SESSION`,
> `POOLER_PROXY_PORT_TRANSACTION`), Envoy's admin port is in
> `config/envoy/envoy.yaml`, and the published ports are also in the
> `Dockerfile`'s `EXPOSE`.

### Start order

supervisord starts programs by priority, and stops them in reverse order:

```mermaid
flowchart LR
    db["1: db (Postgres)"] --> mid["2: auth, rest, realtime, storage,<br/>imgproxy, meta, functions, pooler"]
    mid --> studio["3: studio"] --> gw["4: gateway"]
```

A priority only orders the starts. The scripts that need the database also
wait for it with `wait_for_db` (`pg_isready` over TCP). On the very first
start, that also waits for the init scripts to finish. Every program has
`autorestart=true`, and Envoy health-checks its upstreams, so a service that
comes up late is simply retried.

After a crash or a hard stop, `services/db.sh` removes the lock files Postgres
left behind. In one shared container another service may have taken the old
PID, and Postgres would otherwise refuse to start.

### Gateway routes

| Path | Goes to | Needs |
|---|---|---|
| `/auth/v1/verify`, `/auth/v1/callback`, `/auth/v1/authorize`, `/auth/v1/.well-known/jwks.json`, `/auth/v1/sso/saml/{acs,metadata}`, and `/.well-known/oauth-authorization-server` (at the root) | Auth | nothing |
| `/auth/v1/` | Auth | `apikey` (anon or service) |
| `/rest/v1/`, `/graphql/v1` | PostgREST | `apikey` (the root `/rest/v1/` needs the service key) |
| `/realtime/v1/api` | Realtime's HTTP API | `apikey` |
| `/realtime/v1/` | Realtime (WebSocket) | `apikey` |
| `/storage/v1/` | Storage | its own JWT check |
| `/functions/v1/` | Edge runtime | optional JWT check (`FUNCTIONS_VERIFY_JWT`), then the function's own |
| `/pg/` | postgres-meta | service key |
| `/realtime/v1/api/openapi`, `/realtime/v1/api/tenants`, `/mcp`, `/api/mcp` | — | blocked |
| `/` | Studio | dashboard login (basic auth) |

The table is grouped by service. In `config/envoy/lds.template.yaml`, routes
match in file order and the first match wins. Where `apikey` is needed, the
`sb_publishable_…` / `sb_secret_…` keys are accepted too, once you set them
(see Known limitations).

### Persistence volume

Mount persistent storage on **`/home/supabase/data`** (`DATA_DIR`):

| Path | What |
|---|---|
| `data/pgdata` | `PGDATA`: the whole database |
| `data/postgresql-custom` | Postgres's custom config and **pgsodium's root key** (`/etc/postgresql-custom` links here) |
| `data/storage` | Files uploaded to Storage |
| `data/snippets` | Studio's saved SQL snippets |

- Mount the volume on `data/`, not on `pgdata`. Postgres refuses to start unless it owns its data folder, and a mount point may belong to someone else.
- Keep `pgdata` and `postgresql-custom` together: the key in the second decrypts what Vault stores in the first.
- Without a mount, the data goes to an anonymous Docker volume, which a new container won't reuse.

### Your app's role and schema

`config/db/migrations/99-app.sql` runs once, on the first start. It creates the
login role `app` with the password `APP_DB_PASSWORD`, and the schema `app`,
owned by it. It then makes `postgres` a member, so Studio can see your tables.

Your tables stay out of `public`, which PostgREST serves to anyone holding
the (public) anon key. Rename `app` in that file to suit your project.

### Passwords are set only on the first start

The init SQL runs only when `pgdata` is empty. After that, changing
`POSTGRES_PASSWORD` or `APP_DB_PASSWORD` doesn't change the database. Change
it in Postgres as well, for example in Studio's SQL editor:

```sql
alter role app password '…';
```

`POSTGRES_PASSWORD` is the password of several roles: `postgres`,
`supabase_admin`, `authenticator`, `pgbouncer`, `supabase_auth_admin`,
`supabase_functions_admin` and `supabase_storage_admin`. Then recreate the
container with the new `.env` (`docker rm -f supabase`, then `docker run …`
again): `docker restart` keeps the old environment.

### Deploying to a platform

1. Push the image to a registry the platform can pull from.
2. Set the settings from `.env` as environment variables, or bake them in (above).
3. Set `SUPABASE_PUBLIC_URL` and `API_EXTERNAL_URL` to the public address, e.g. `https://your-domain.example.com` and `https://your-domain.example.com/auth/v1`.
4. Publish 9876 for HTTP. Publish 5432/5433/6543 only if the platform supports raw TCP. If it doesn't, use one of the single-port variants.
5. Mount persistent storage on `/home/supabase/data`.

The container runs as a non-root user (uid 1000) and starts with
`./start-script.sh` in its working directory, as many platforms expect.