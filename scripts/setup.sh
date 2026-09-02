#!/usr/bin/env bash
#
# scripts/setup.sh — one command from a running Postgres + Redis to a
# working database: create it if it doesn't exist, bootstrap the
# ems_owner/ems_app role split, run every migration, seed reference data.
# In that order, every time (Spec 8.2/19's WP-15 gate).
#
# Idempotent — safe to re-run at any point. Every step it calls already is:
# bootstrap_roles.sql uses CREATE ROLE ... IF NOT EXISTS and re-runnable
# GRANTs; alembic upgrade head no-ops once at head; industry_presets seeding
# upserts by name.
#
# CI (.github/workflows/ci.yml) calls this exact script instead of keeping
# its own copy of the sequence — a sequence living in two places is how it
# diverged and broke CI before (docs/RECONCILIATION.md).
#
# Reads its configuration from the environment. Locally:
#
#     cp .env.example .env        # working local defaults, no edits needed
#     set -a; source .env; set +a
#     scripts/setup.sh
#
# Required: ALEMBIC_DATABASE_URL (this script migrates and seeds through
# it). Optional: PG_BOOTSTRAP_USER (default: your OS username, matching
# Homebrew/Postgres.app's own default local superuser) and
# PG_BOOTSTRAP_PASSWORD (default: none — trust/peer auth) — the role used
# ONLY to create the database if it's missing and to run
# bootstrap_roles.sql the very first time. That must be a real superuser
# (bootstrap_roles.sql's own header explains why) — ems_owner isn't one
# yet the first time this runs locally, only in CI, where the Postgres
# service container's own POSTGRES_USER already makes it one.

set -euo pipefail

fail() {
  echo "setup.sh: $1" >&2
  exit 1
}

command -v psql >/dev/null 2>&1 || fail "psql not found — install the PostgreSQL client tools first."
command -v createdb >/dev/null 2>&1 || fail "createdb not found — install the PostgreSQL client tools first."
command -v alembic >/dev/null 2>&1 || fail "alembic not found on PATH — run 'pip install -e \".[dev]\"' first (inside your virtualenv)."
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH."

: "${ALEMBIC_DATABASE_URL:?ALEMBIC_DATABASE_URL is not set. Copy .env.example to .env, then: set -a; source .env; set +a}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse host/port/dbname out of ALEMBIC_DATABASE_URL — works regardless of
# the +driver suffix (postgresql:// or postgresql+psycopg2://).
PG_TARGET="$(python3 - "$ALEMBIC_DATABASE_URL" <<'PYEOF'
import sys
from urllib.parse import urlsplit

u = urlsplit(sys.argv[1].replace("+psycopg2", ""))
print(f"{u.hostname or 'localhost'} {u.port or 5432} {u.path.lstrip('/')}")
PYEOF
)"
read -r PG_HOST PG_PORT PG_DB <<<"$PG_TARGET"
[ -n "$PG_DB" ] || fail "Could not parse a database name out of ALEMBIC_DATABASE_URL."

PG_BOOTSTRAP_USER="${PG_BOOTSTRAP_USER:-$(whoami)}"
PG_BOOTSTRAP_PASSWORD="${PG_BOOTSTRAP_PASSWORD:-}"
PG_APP_PASSWORD="${PG_APP_PASSWORD:-ems_app_dev_only}"

echo "==> Checking Postgres is reachable at ${PG_HOST}:${PG_PORT}..."
pg_isready -h "$PG_HOST" -p "$PG_PORT" >/dev/null 2>&1 \
  || fail "Postgres is not reachable at ${PG_HOST}:${PG_PORT}. Start it first (docker compose up -d, or brew services start postgresql@16)."

echo "==> Checking Redis is reachable..."
python3 -c "
import sys
import redis
try:
    redis.Redis.from_url('${REDIS_URL:-redis://localhost:6379/0}', socket_connect_timeout=2).ping()
except Exception as exc:
    print(f'Redis is not reachable: {exc}', file=sys.stderr)
    sys.exit(1)
" || fail "Redis is not reachable. Start it first (docker compose up -d, or brew services start redis)."

echo "==> Creating database '${PG_DB}' if it doesn't already exist..."
EXISTS="$(PGPASSWORD="$PG_BOOTSTRAP_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_BOOTSTRAP_USER" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname = '${PG_DB}'" 2>/dev/null || true)"
if [ "$EXISTS" != "1" ]; then
  PGPASSWORD="$PG_BOOTSTRAP_PASSWORD" createdb -h "$PG_HOST" -p "$PG_PORT" -U "$PG_BOOTSTRAP_USER" "$PG_DB" \
    || fail "Could not create database '${PG_DB}' as '${PG_BOOTSTRAP_USER}'. Set PG_BOOTSTRAP_USER to a real Postgres superuser on your machine and re-run."
  echo "    created."
else
  echo "    already exists."
fi

echo "==> Bootstrapping ems_owner/ems_app roles and grants..."
PGPASSWORD="$PG_BOOTSTRAP_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_BOOTSTRAP_USER" -d "$PG_DB" \
  -v ON_ERROR_STOP=1 -f "$REPO_ROOT/app/db/seed/bootstrap_roles.sql" \
  || fail "bootstrap_roles.sql failed — see the error above."

echo "==> Running migrations (alembic upgrade head)..."
(cd "$REPO_ROOT" && alembic upgrade head) || fail "alembic upgrade head failed — see the error above."

echo "==> Seeding reference data (industry_presets)..."
# Always targets the database this script just migrated, as ems_app (the
# runtime role) — not whatever DATABASE_URL happens to be set to in the
# caller's environment. In CI, DATABASE_URL deliberately names a database
# that is never created (see ci.yml's own comment); this keeps seeding
# correct there too, with no special-casing.
DATABASE_URL="postgresql+psycopg2://ems_app:${PG_APP_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}" \
  python3 -m app.db.seed.industry_presets \
  || fail "Seeding industry_presets failed — see the error above."

echo "==> Done. Database '${PG_DB}' is bootstrapped, migrated, and seeded."
