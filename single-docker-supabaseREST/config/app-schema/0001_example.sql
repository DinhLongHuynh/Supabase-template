-- An example table for your app: replace it with your own. services/schema.sh
-- applies each file of this folder once, in name order, as the role app, in
-- the schema app. To change the tables later, add 0002_<what>.sql: never edit
-- a file that a database has had.
--
-- Your app reaches the table through the REST API, with APP_KEY:
--   GET/POST/PATCH/DELETE /rest/v1/items, with the header Accept-Profile: app
--   (Content-Profile: app for writes). See README.md.

create table items (
    id bigint generated always as identity primary key,
    name text not null,
    data jsonb not null default '{}',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index items_by_created_at on items (created_at desc);

-- The role app owns the schema and its tables, so it may do everything with
-- them, and no other API role (anon, authenticated, service_role) may.
--
-- To also let users signed in with Supabase Auth reach their own rows, with
-- the anon key and their session's JWT, grant the role authenticated access
-- and turn on row level security. auth.uid() lives in the schema auth, which
-- the role app can't use, and a file here can't grant that (it runs as app):
-- first add this line to the SQL block of services/schema.sh, which runs as
-- supabase_admin before the files here:
--
--   grant usage on schema auth to app;
--
-- Then, in a new file (0002_own_rows.sql):
--
--   alter table items add column owner uuid default auth.uid();
--   grant usage on schema app to authenticated;
--   grant select, insert, update, delete on items to authenticated;
--   alter table items enable row level security;
--   create policy "own rows" on items for all to authenticated
--       using (owner = auth.uid()) with check (owner = auth.uid());
--
-- Keep owner nullable: APP_KEY names no user, so auth.uid() is null for your
-- app's own inserts (set owner yourself when it should belong to someone).
-- The role app, as the tables' owner, is not limited by the policy.
