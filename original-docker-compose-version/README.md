# Self-hosted Supabase: the original docker-compose template

## Overview

Supabase's own self-hosting bundle (the `docker/` folder
of [supabase/supabase](https://github.com/supabase/supabase/tree/self-hosted/v0.8.2/docker)).

**Use it when your host runs Docker Compose**, such as a VM, a bare-metal
server or your laptop. 

Each Supabase service runs in its own container on one Docker network, where
the containers find each other by service name (`db`, `auth`, `rest`, …). An
Envoy's API gateway is the single HTTP entry point, and Postgres
connections from outside go through the Supavisor connection pooler.

```mermaid
flowchart LR
    client(["Your app / browser"])
    tools(["psql / your app's<br/>Postgres driver"])

    subgraph net ["Docker network (one container per service)"]
        gw["api-gw (Envoy)<br/>:8000"]
        studio["studio"]
        auth["auth (GoTrue)"]
        rest["rest (PostgREST)"]
        realtime["realtime"]
        storage["storage"]
        imgproxy["imgproxy"]
        meta["meta (postgres-meta)"]
        functions["functions (edge runtime)"]
        pooler["supavisor<br/>:5432 / :6543"]
        db[("db (Postgres)")]
    end

    client -->|"HTTP :8000"| gw
    tools -->|"postgres:// :5432, :6543"| pooler
    gw -->|"/"| studio
    gw -->|"/auth/v1"| auth
    gw -->|"/rest/v1, /graphql/v1"| rest
    gw -->|"/realtime/v1"| realtime
    gw -->|"/storage/v1"| storage
    gw -->|"/functions/v1"| functions
    gw -->|"/pg"| meta
    studio --> meta
    storage --> rest
    storage --> imgproxy
    auth & rest & realtime & storage & meta & pooler --> db
```

## Quick Start

### Step 1: Config setting
```bash
cd original-docker-compose-version

cp .env.example .env
sh utils/generate-keys.sh --update-env
```

### Step 2: Your app's own role and schema 
```bash
# Docker Desktop, since the overlay also moves the data to a named volume).
# Set APP_DB_PASSWORD in .env (the line is already there, empty):

sed -i.bak "s/^APP_DB_PASSWORD=.*/APP_DB_PASSWORD=$(openssl rand -hex 24)/" .env && rm .env.bak
sh run.sh config add app        # COMPOSE_FILE=docker-compose.yml:docker-compose.app.yml
```

### Step 3. Start everything, and wait until every service is healthy.
```bash
sh run.sh start
sh run.sh status
```

Then:

```bash
# Load the values the commands below use (don't source .env: some values contain spaces).
export $(grep -E '^(SERVICE_ROLE_KEY|POSTGRES_PASSWORD|APP_DB_PASSWORD|POOLER_TENANT_ID)=' .env | xargs)
```

- **Studio:** <http://localhost:8000>. Log in with `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` from `.env`.
- **REST API:** `curl http://localhost:8000/rest/v1/ -H "apikey: $SERVICE_ROLE_KEY"` returns the API's description. (The root needs the service key; a table such as `/rest/v1/<table>` needs only the anon key.)
- **Postgres, through the pooler:**

  ```bash
  psql "postgres://postgres.$POOLER_TENANT_ID:$POSTGRES_PASSWORD@localhost:5432/postgres"   # session mode
  psql "postgres://app.$POOLER_TENANT_ID:$APP_DB_PASSWORD@localhost:6543/postgres"          # your app's role, transaction mode
  ```

  The user name is `<role>.<POOLER_TENANT_ID>` (`your-tenant-id` by default).

### Step 4: Stop
To stop: `sh run.sh stop`.

---

## Details

### Services and ports

| Service | Image | Reached at |
|---|---|---|
| api-gw (Envoy) | `envoyproxy/envoy` | **host :8000** (`API_GW_HTTP_PORT`) |
| studio | `supabase/studio` | gateway `/` (dashboard login) |
| auth (GoTrue) | `supabase/gotrue` | gateway `/auth/v1/` |
| rest (PostgREST) | `postgrest/postgrest` | gateway `/rest/v1/`, `/graphql/v1` |
| realtime | `supabase/realtime` | gateway `/realtime/v1/` (WebSocket) |
| storage | `supabase/storage-api` | gateway `/storage/v1/` |
| imgproxy | `darthsim/imgproxy` | storage only |
| meta (postgres-meta) | `supabase/postgres-meta` | gateway `/pg/` (service key) |
| functions (edge runtime) | `supabase/edge-runtime` | gateway `/functions/v1/` |
| supavisor (pooler) | `supabase/supavisor` | **host :5432** (session), **:6543** (transaction) |
| db (Postgres 17) | `supabase/postgres` | the services inside; not published |

### Other overlays (upstream)

Layer them with `sh run.sh config add <name>`:

| Name | What it does |
|---|---|
| `kong` | Kong instead of Envoy as the gateway (deprecated upstream). |
| `caddy`, `nginx` | A TLS reverse proxy on 80/443 for `PROXY_DOMAIN`, with Let's Encrypt. It removes the gateway's host port 8000, so everything is reached at `https://PROXY_DOMAIN`. |
| `logs` | Analytics (Logflare) and Vector, for Studio's Logs page. |
| `rustfs`, `s3` | RustFS, or MinIO (deprecated upstream), as Storage's S3 backend. |
| `pgbouncer` | PgBouncer instead of Supavisor: transaction mode only, on host :6543 only, and the user name is the plain role (`app`, not `app.<tenant>`). |
| `pg15` | Stay on Postgres 15 (deprecated upstream). |

The pooler's host ports come from `POSTGRES_PORT` (5432) and
`POOLER_PROXY_PORT_TRANSACTION` (6543) in `.env`.

### Where the data lives

| Data | Where |
|---|---|
| Postgres | `./volumes/db/data` (bind mount), or the named volume `supabase_db-data` with the app overlay |
| Postgres's config and pgsodium's root key | the named volume `supabase_db-config`: back it up together with the data, since the key decrypts what Vault stores |
| Storage files | `./volumes/storage`, or the volume `supabase_rustfs-data` / `supabase_minio-data` with the `rustfs` / `s3` overlay |
| Studio snippets | `./volumes/snippets` |
| Edge functions | `./volumes/functions` (`main/` is the router, `hello/` an example) |

### Passwords are set only on the first start

Postgres runs the init scripts in `volumes/db/` (and `app.sql`) only when its
data folder is empty. After that, changing `POSTGRES_PASSWORD` or
`APP_DB_PASSWORD` in `.env` doesn't change the database:

- **Supabase's roles:** with the stack running, run `sh utils/db-passwd.sh`. It sets a *new random* password on all of Supabase's roles, writes it to `POSTGRES_PASSWORD` in `.env`, and resets Supavisor's schema. Then run `sh run.sh recreate`.
- **Your app's role:** run `alter role app password '…'` in Studio's SQL editor, and put the same value in `APP_DB_PASSWORD`.

### Wiping everything

```bash
sh reset.sh                          # containers, the db-config and deno-cache volumes, ./volumes/db/data and
                                     # ./volumes/storage; .env is moved to .env.old and replaced by .env.example
docker volume rm supabase_db-data    # with the app overlay: reset.sh doesn't load it, so it keeps this volume
```

### Updating Supabase

`update.sh` 3-way merges a newer upstream release onto this folder. It needs
`git` and `jq`. It keeps your `.env` values and never touches the files
upstream doesn't have, such as `docker-compose.app.yml`, `volumes/db/app.sql`
and `CLAUDE.md`. It needs to know which release the folder started from,
recorded in `.supabase-version` (git-ignored, so create it once):

```bash
printf 'ref=self-hosted/v0.8.2\n' > .supabase-version
sh update.sh --dry-run    # what would change
sh update.sh              # update to the latest release
```

- `README.md`, `.env.example` and `.gitignore` differ from upstream, so `update.sh` merges them too. When upstream changes the same lines, it reports a conflict and stops without recording the new version. Keep this folder's lines, then run it again.
- It also reports `APP_DB_PASSWORD` as gone from the new `.env.example`. Keep it.

### Documentation

- Self-hosting guide: <https://supabase.com/docs/guides/self-hosting/docker>
- Every setting in `.env`: [`CONFIG.md`](CONFIG.md)