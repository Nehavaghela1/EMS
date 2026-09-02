# EMS

A multi-tenant HRMS, payroll and projects platform for small-to-mid Indian
companies. One deployment serves many companies, each seeing only its own
data — enforced not just in application code but at the PostgreSQL level.

## Stack

FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 (sync) · Alembic · Redis · Celery ·
React 19 + TypeScript + Vite, no CSS framework.

## How to run it

### Prerequisites

- Python 3.12+
- Node 20+
- Docker (for Postgres + Redis) — or your own local Postgres 16 / Redis 7
- A Postgres role that can `CREATE DATABASE` and `CREATE ROLE` locally. On
  macOS with Homebrew/Postgres.app this is normally your OS username with no
  password, which is what `scripts/setup.sh` assumes by default.

### One-time setup

```bash
docker compose up -d                          # Postgres 16 + Redis 7
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                          # every value already works locally

scripts/setup.sh
```

`scripts/setup.sh` is the one command that takes a machine from "Postgres and
Redis are running" to "the app can start": it creates the `ems_pro` database
if it doesn't exist, runs `app/db/seed/bootstrap_roles.sql` (creates the
`ems_owner`/`ems_app` roles — see below), runs `alembic upgrade head`, and
seeds the `industry_presets` reference table. It's idempotent — safe to
re-run — and fails loudly with a specific fix instruction the first time a
prerequisite is missing, rather than half-succeeding. CI runs this exact
script too, not a separate copy of the same steps.

### Demo data (optional but recommended)

```bash
pip install -e ".[demo]"
python3 scripts/seed_demo.py
```

Creates a realistic demo company — 25 employees across 7 departments, 3-4
months of attendance (including late arrivals and absences), leave requests
in every state, a couple of shifts, holidays, and notifications — then
prints login credentials for one HR admin, one manager and one employee.
Safe to re-run (it wipes and rebuilds its own demo company only). This is
deliberately a separate, explicit script: never run by `setup.sh`, never run
by CI.

### Start everything

```bash
uvicorn app.main:app --reload                              # API → localhost:8000/docs
celery -A app.workers.celery_app worker -l info             # background jobs (exports)
celery -A app.workers.celery_app beat -l info                # scheduler — run ONE instance
cd frontend && npm install && npm run dev                    # frontend → localhost:5173
```

Log in at `localhost:5173/login` with the credentials `seed_demo.py` printed.
The frontend talks to `http://localhost:8000/api/v1` by default (see
`frontend/.env.example` to point it elsewhere) — no `.env` file is required
to run it locally.

## Architecture

Every module — `identity`, `hr`, `time_leave`, `performance`, `payroll`,
`projects`, `platform` — has exactly five files, and each has exactly one
job:

```
app/modules/<name>/
  models.py      SQLAlchemy tables only        — no logic
  schemas.py     Pydantic request/response      — no logic
  repository.py  database queries only          — no business rules, no HTTP
  service.py     business rules only             — no SQL, no HTTP
  router.py      HTTP routes only                — no business rules, no SQL
```

Dependencies point one direction only: `router → service → repository →
model`, never backwards, never skipping a layer. The repository doesn't know
what a failed login means; the service doesn't know it's being called over
HTTP; the router doesn't know what a password is. Concretely: the repository
never raises `HTTPException` and never commits a transaction (the service
that called it owns the commit/rollback boundary); the service never writes
raw SQL and raises `AppError` subclasses instead of `HTTPException`, so the
same business logic could be driven from a CLI script with no web framework
in the picture at all.

The project is organized by business domain, not by file type — when you
change how leave approval works, you open `time_leave/`, not five scattered
folders across the codebase.

`app/modules/identity/` is the reference implementation other modules were
built to match.

## Multi-tenancy and row-level security

Every tenant table has a `company_id` column and inherits `TenantBase`,
which pairs it with a PostgreSQL **row-level security (RLS)** policy created
in the same migration. `company_id` is set per-transaction from the caller's
verified JWT claim — never a request body, path, query string, or header —
via `SET LOCAL` inside a SQLAlchemy `after_begin` event, so it's reapplied on
every new transaction a pooled connection picks up.

Two database roles enforce this at different layers:

- **`ems_owner`** — owns the schema, runs Alembic migrations. Table owners
  bypass their own RLS policies by default, which is why every tenant table
  is also declared `FORCE ROW LEVEL SECURITY`: without it, a bug that
  accidentally ran a query as the owner would silently see every tenant's
  data.
- **`ems_app`** — the role the running API and Celery workers actually
  connect as. `NOSUPERUSER NOCREATEDB NOBYPASSRLS`. This is the role RLS is
  actually protecting against.

**Why RLS at all, when the application already filters by `company_id`
everywhere?** Because application code can forget a filter — a missed
`.where(company_id=...)` in a new query is exactly the kind of bug that's
easy to write and easy to miss in review. RLS is the backstop that catches
that day, not a replacement for the application-level filtering. Every
tenant table's RLS policy also gets an isolation test in the same change
that adds the table, asserting that a session bound to company A really
cannot see company B's rows even if the query itself doesn't filter.

**Three tables are deliberately exempt**, and none of them is an oversight:

- **`users`** must be queryable *before* any tenant context exists — during
  login, activation, and password reset, there's no company context yet to
  set. RLS would return zero rows and break every one of those flows.
  Instead, every `UserRepository` method except the small set of documented
  pre-authentication lookups *requires* `company_id` as a function argument
  — enforced by the method signature, not by developer discipline — and no
  route ever lists users across the table.
- **`refresh_tokens`** is always looked up by the specific user it belongs
  to, never queried cross-tenant, so the same reasoning applies.
- **`audit_logs`** holds both per-company rows and platform-level rows
  (`company_id IS NULL` — a `super_admin` approving a company, for
  instance), and RLS can't express "sometimes there's no tenant." It has no
  RLS policy and is scoped by query pattern instead: nothing in the codebase
  ever queries it without either a specific `company_id` or an explicit
  platform-admin context.

### `audit_logs` is append-only, enforced by the database

Every write anywhere in the system — company approvals, employee changes,
leave decisions, attendance regularization — lands a row in `audit_logs`.
An audit trail that the very role whose actions it records can also edit or
delete isn't a trail. So the guarantee doesn't live in application code at
all: `app/db/seed/bootstrap_roles.sql` runs

```sql
REVOKE UPDATE, DELETE ON audit_logs FROM ems_app;
```

against the running API's own database role. `ems_app` can `SELECT` and
`INSERT`, nothing else — a bug, a compromised API process, or a well-meaning
maintenance script all hit the same wall a malicious insider would. The one
place this had to be worked around deliberately (never bypassed) is
`scripts/seed_demo.py`'s wipe-and-rebuild step, which needs to delete its
*own* demo company's audit rows between runs — it does that by opening a
short-lived, narrowly-scoped session as `ems_owner` (the table's actual
owner) for exactly that one operation, rather than weakening the grant.

## What's built

- **Identity** — company registration and `super_admin` approval, JWT
  login/refresh/logout, password reset, employee activation-by-invite,
  role-based access (`super_admin` / `hr_admin` / `manager` / `employee`).
- **HR** — departments, employee CRUD, deactivation/reactivation (never a
  hard delete), invite resend.
- **Time & leave** — check-in/check-out, HR-regularized attendance, shifts
  and shift assignment, holidays, configurable leave types, leave
  application/approval/rejection/cancellation with a stored balance ledger.
- **Platform** — a role-scoped dashboard, the append-only audit log above,
  in-app notifications, async CSV export via Celery.
- **Frontend** — auth pages, an admin console for company approval, HR
  pages for employees/departments, and the time & leave pages, all against
  the same backend.

## Deliberately out of scope

**Payroll, performance and projects are specified but not implemented** —
`app/modules/{payroll,performance,projects}/` currently contain only an
`__init__.py`. This isn't an oversight; it's the boundary of this build.
Two things are worth knowing if you read the spec expecting them:

- Money throughout the spec is `Decimal` with explicit `ROUND_HALF_UP`
  rounding, never `float` — this project treats a payslip that doesn't
  balance exactly (`earnings − deductions + reimbursements == net`) as a
  bug, not a rounding artifact.
- Indian statutory rates (EPF, ESI, professional tax, TDS slabs) are
  specified to live in database tables with a `source_note` per row, never
  as literals in Python — and the spec is explicit that the rates in its own
  research section are **not independently verified** against EPFO/ESIC/tax
  department sources. Building the payroll engine on unverified rates would
  produce numbers that look authoritative and aren't; that verification work
  hasn't happened, which is the other reason this module waited.

KYC/work-experience employee tabs (the spec's WP-08) and resignation/FnF
workflows are similarly specified but not built.

## Tests

```bash
pytest -v --cov=app
```

`tests/unit` and `tests/integration` cover business rules and API behavior;
`tests/isolation` is entirely RLS isolation tests — one tenant's session
attempting (and failing) to see or write another tenant's rows, for every
table that carries a policy. Integration and isolation tests connect as
`ems_app`, the same role the running API uses, so grants and RLS are
actually exercised rather than bypassed by a superuser test connection.

```bash
ruff check . && ruff format --check .    # lint
mypy app/                                # types
cd frontend && npm run build              # frontend typecheck + production build
```

## API reference

`localhost:8000/docs` (Swagger) or `/redoc` once the server is running. A
Postman collection covering every route, grouped by module, is in
[`docs/postman_collection.json`](docs/postman_collection.json) with a
matching [`docs/postman_environment.json`](docs/postman_environment.json) —
its description includes a suggested first run-through
(register → approve → login → create employee).

## Schema

[`docs/ERD.md`](docs/ERD.md) — every table and relationship as a Mermaid
diagram (renders directly on GitHub).

## Specification

[`docs/EMS_PRO_DEV_SPEC.md`](docs/EMS_PRO_DEV_SPEC.md) is the source of
truth this was built against; [`docs/RECONCILIATION.md`](docs/RECONCILIATION.md)
tracks the few places the running code and the spec were deliberately
reconciled.
