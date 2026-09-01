-- app/db/seed/bootstrap_roles.sql
--
-- Creates the two-role split Spec 8.2 requires and grants the runtime role
-- (ems_app) default privileges on every table and sequence a future
-- migration creates. Without ALTER DEFAULT PRIVILEGES, only the tables that
-- exist at the moment this script runs would be reachable — every table
-- Alembic creates afterwards would have no grants at all, and the API would
-- fail with "permission denied" on first use.
--
-- Run once per environment/database, connected as a superuser (locally: the
-- Postgres superuser on your machine; via docker-compose: the `postgres`
-- bootstrap user in POSTGRES_USER):
--
--     psql -d ems_pro -f app/db/seed/bootstrap_roles.sql
--
-- Then re-run just the GRANT/REVOKE section (everything after role creation)
-- as a release step after every deploy — a grant that exists only in
-- someone's shell history is a production outage waiting for the next
-- environment (Spec 8.2). Safe to re-run in full at any time; every
-- statement is idempotent.
--
-- CRITICAL (Spec 8.2): a table's owner bypasses its own RLS policies by
-- default. If the API ever connects as ems_owner (the table owner), every
-- RLS policy written from WP-04 onward is silently inert and the isolation
-- suite will pass while protecting nothing. The API and Alembic must use
-- DIFFERENT roles: DATABASE_URL = ems_app, ALEMBIC_DATABASE_URL = ems_owner.
--
-- Passwords below are LOCAL DEV PLACEHOLDERS ONLY, matching the convention
-- already used by docker-compose.yml's bootstrap superuser. Staging and
-- production use the hosting platform's secret store (Spec 9.10, 17.1) —
-- never these literal values.

-- psql does NOT stop on error by default — without this, a failed statement
-- (e.g. REASSIGN OWNED BY failing because the connecting role isn't
-- actually a superuser) prints an ERROR line and keeps going, silently
-- leaving the database in a half-bootstrapped state. Caught running this
-- exact script during WP-02 verification.
\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ems_owner') THEN
        -- Owns the schema, runs Alembic. CREATEDB so it can provision the
        -- test database (ems_pro_test) and scratch databases without a
        -- separate superuser being available (WP-01 hit exactly this wall).
        CREATE ROLE ems_owner LOGIN PASSWORD 'ems_owner_dev_only' CREATEDB;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ems_app') THEN
        -- What the API connects as. MUST NOT be superuser, MUST NOT have
        -- BYPASSRLS, and MUST NOT own the tables (Spec 8.2).
        CREATE ROLE ems_app LOGIN PASSWORD 'ems_app_dev_only'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- Migrate existing objects: WP-01's companies/users/refresh_tokens were
-- created under the earlier single-role setup (ems_user) before this split
-- existed. Reassign them to ems_owner so ems_app is never the owner of
-- anything and FORCE ROW LEVEL SECURITY actually binds once WP-04 adds it.
-- No-op (and safe) if ems_user doesn't exist in this environment.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ems_user') THEN
        EXECUTE 'REASSIGN OWNED BY ems_user TO ems_owner';
    END IF;
END
$$;

ALTER SCHEMA public OWNER TO ems_owner;

DO $$
BEGIN
    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE %I TO ems_owner', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO ems_app', current_database());
END
$$;

GRANT CREATE, USAGE ON SCHEMA public TO ems_owner;
GRANT USAGE ON SCHEMA public TO ems_app;

-- Covers every table/sequence that exists right now (post-reassignment).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ems_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ems_app;

-- Covers every table/sequence a future `alembic upgrade head` (run as
-- ems_owner) creates from this point on. This is the statement WP-01's
-- audit specifically warned would be missing (Spec 8.2) — verified below in
-- WP-02's Step 2 by creating a scratch table as ems_owner and confirming
-- ems_app can read/write it with no manual GRANT in between.
ALTER DEFAULT PRIVILEGES FOR ROLE ems_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ems_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ems_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ems_app;

-- audit_logs and payroll_items are append-only (Spec 6.5, 8.2): the
-- application role gets SELECT/INSERT only, never UPDATE or DELETE. An audit
-- log the application can rewrite is not an audit log. Both tables arrive in
-- later work packages (WP-11, WP-19) — these REVOKEs are harmless no-ops
-- until then, kept here so the rule isn't forgotten when those tables land.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'audit_logs') THEN
        EXECUTE 'REVOKE UPDATE, DELETE ON audit_logs FROM ems_app';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'payroll_items') THEN
        EXECUTE 'REVOKE UPDATE, DELETE ON payroll_items FROM ems_app';
    END IF;
END
$$;
