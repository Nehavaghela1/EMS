# EMS Pro

Multi-tenant HRMS + Payroll + Projects SaaS platform.
FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 (sync) · Alembic · Redis · Celery · React + TypeScript.

## The specification

**`docs/EMS_PRO_DEV_SPEC.md` is the single source of truth.** Read the relevant sections before writing code. If the code and the spec disagree, the spec wins — or the spec is amended first, then the code.

Do not invent a schema, route, or convention that the spec already defines. If something is genuinely missing, propose adding it to the spec before implementing it.

## Where you are in the build

Work packages are defined in **Section 19**. Work one at a time, in order.

- Current work package: **WP-01 (reconcile existing code — Section 20)**
- Do not start the next package until the current one's exit gate passes.

## Structure — every module has exactly these five files

```
app/modules/<name>/
  models.py      SQLAlchemy tables only        — no logic
  schemas.py     Pydantic request/response     — no logic
  repository.py  database queries only         — no business rules, no HTTP
  service.py     business rules only           — no SQL, no HTTP
  router.py      HTTP routes only              — no business rules, no SQL
```

Modules: `identity · hr · time_leave · performance · payroll · projects · platform`
Reference implementation: `app/modules/identity/`

## Rules that are never relaxed

1. Every tenant table inherits `TenantBase` **and** gets an RLS policy in the same migration (Spec §8). The only deliberate exceptions are `users`, `refresh_tokens` and `audit_logs`, which are scoped in the repository layer for reasons the spec states — do not "fix" them.
2. Every new tenant table gets an isolation test in the same change (Spec §8.6, §15).
3. `company_id` comes from the verified JWT claim only — never from a body, path, query, or header.
4. Money is `Decimal` with explicit `ROUND_HALF_UP`. Never `float` (Spec §11.1).
5. No statutory rate, tax slab, or business threshold as a literal in Python. They live in tables (Spec §12).
6. UUID primary keys. `TIMESTAMPTZ` timestamps, always UTC, via `app/core/time.py::utcnow()`.
7. Services raise `AppError` subclasses, never `HTTPException` (Spec §6.6).
8. Services own transaction boundaries; repositories never commit (Spec §6.7).
9. Another tenant's resource returns **404, not 403** (Spec §10.1).
10. Never log or return passwords, tokens, Aadhaar, PAN, or bank details.
11. Tests are written in the same work package as the feature, never afterwards.
12. Never touch `.env`. Never `git push`. Never `alembic downgrade`.

## Commands

```bash
docker compose up -d                              # Postgres + Redis
alembic upgrade head                              # migrations (as ems_owner)
uvicorn app.main:app --reload                     # API → localhost:8000/docs
celery -A app.workers.celery_app worker -l info   # worker
celery -A app.workers.celery_app beat -l info     # scheduler — ONE instance only
cd frontend && npm run dev                        # frontend → localhost:5173

ruff check . && ruff format --check .             # lint
mypy app/                                         # types
pytest -v --cov=app                               # tests
```

## Slash commands

- `/wp <number>` — start a work package from Spec §19
- `/new-module <name>` — scaffold a module per Spec §4.1
- `/verify` — run the full verification gate and report PASS/FAIL

## Accuracy note

Indian statutory payroll rates in Spec §12 come from the project's research document and are **not independently verified**. Every rate must be confirmed against its official source (EPFO, ESIC, State PT authority, Income Tax Department) before it computes anyone's real pay, and the `source_note` column recorded. Never present an unverified rate as current law.
