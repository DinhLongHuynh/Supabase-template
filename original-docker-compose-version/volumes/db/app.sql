-- The login and schema of your own application. Runs once, as
-- supabase_admin, when the database is first created.
--
-- The tables live in their own schema, not in public: PostgREST serves public
-- to anyone holding the anon key, and your tables may hold private data
-- (password hashes, tokens, ...). The app logs in as the role app, which can
-- only reach this schema. Rename app to suit your project.
\set app_password `echo "$APP_DB_PASSWORD"`

create role app with login password :'app_password';
create schema app authorization app;
alter role app set search_path = app;

-- Studio's Table Editor and SQL editor connect as postgres.
grant app to postgres;
