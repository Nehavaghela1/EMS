# EMS Pro — Master Development Specification

**Project:** EMS Pro — Multi-Tenant HRMS + Payroll + Projects SaaS
**Owner:** Neha (solo developer)
**Backend:** Python 3.12 · FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 (sync) · Alembic · Redis · Celery
**Frontend:** React 18 · TypeScript · Vite · Tailwind CSS · shadcn/ui
**Spec version:** 1.0 · August 2026
**Status:** This document is the single source of truth. If code and this document disagree, the document wins — or the document gets amended first, then the code.

---

## 0. How to use this document

### 0.1 Who reads this

This document has two readers, and it is written for both.

**Claude Code (the build agent)** reads this as the complete, binding specification. It contains every architectural decision, every table, every route, every convention, and the exact order of work. Claude Code should not invent design decisions that are already made here, and should not skip verification gates.

**Neha (the developer)** reads this to understand what is being built and to check the agent's work. Every section has a short *Why* note explaining the reasoning, because approving code you don't understand is not review.

### 0.2 The rules for the build agent

These are non-negotiable operating rules for any AI agent working on this repository.

1. **Read this document before writing code.** Not a summary of it — the relevant sections in full.
2. **Never invent a schema, route, or convention that this document already defines.** If something is genuinely missing, add it to this document first (as a proposal, flagged), then implement it.
3. **One work package at a time.** Work packages are defined in Section 19. Do not start the next one until the current one's exit gate passes.
4. **Every work package ends with a verification gate that actually runs.** "It should work" is not a gate. `pytest` passing is a gate. A curl/Swagger round-trip returning the expected payload is a gate.
5. **Never hardcode a statutory rate, tax slab, or business threshold in application code.** These live in database tables or config. Section 12 explains why this is a correctness requirement, not a style preference.
6. **Never commit secrets.** `.env` is git-ignored; `.env.example` is committed with placeholder values only.
7. **Never use `float` for money.** `Decimal` only, with explicit rounding. Section 11.1.
8. **Every tenant-scoped query must be safe even if the application code forgets to filter.** That is what Row-Level Security is for (Section 8). Application-level `company_id` filtering is the second layer, not the only layer.
9. **Write the test in the same work package as the feature.** Not "later". Section 15.
10. **If a requirement in this document appears wrong or unsafe, say so before implementing it.** Do not silently "improve" a spec decision; raise it.

### 0.3 Accuracy notice — read this before building payroll

Section 12 contains India statutory payroll components (EPF, ESI, Professional Tax, TDS, LWF) with rates and thresholds. **These figures originate from the project's own earlier research document, not from an independent verification against government sources performed while writing this specification.** Statutory rates, wage ceilings, and tax slabs are set by government notification and change — sometimes mid-year.

Therefore:

- Treat Section 12 as a **correct structural model** of how Indian payroll composes, not as verified current law.
- Every rate must be **confirmed against the current official source** (EPFO, ESIC, the relevant State Professional Tax authority, and the Income Tax Department) before it is used to compute a real person's salary.
- This is why the architecture stores every rate in a database table (`statutory_configs`, `pt_slabs`, `tax_slabs`) rather than in Python. Updating a rate must be a data change, never a code deploy.

The same applies with more force to the deferred US / UK / Germany / Australia payroll rules (Section 23): none of those figures are verified, and each country's rules must be re-checked against that country's official source at the time it is actually built.

### 0.4 Document map

| Section | Covers | When the agent reads it |
|---|---|---|
| 1 | Product definition, users, roles | Once, at the start |
| 2 | The nine engineering rules | Once, then apply everywhere |
| 3 | Technology stack and pinned choices | When installing anything |
| 4 | Repository and folder structure | Before creating any file |
| 5 | Architecture — the four layers, request lifecycle | Before writing any module |
| 6 | Coding standards and conventions | Continuously |
| 7 | Complete database schema | Before writing models/migrations |
| 8 | Multi-tenancy and Row-Level Security | WP-04, then every table added after |
| 9 | Security specification | WP-03, WP-04, WP-08, WP-28 |
| 10 | Complete API contract | Before writing any router |
| 11 | Business logic specifications | Before payroll, leave, attendance, FnF |
| 12 | India statutory payroll (MVP scope) | Payroll milestone only |
| 13 | Background jobs (Celery) | When a task must not block a request |
| 14 | Frontend specification | Every frontend work package |
| 15 | Testing strategy | Every work package |
| 16 | Observability — logging, errors, health | WP-02, then WP-28 |
| 17 | Configuration and environments | WP-02 |
| 18 | CI/CD and deployment | WP-02, then WP-29 |
| 19 | **Build sequence — work packages and gates** | **Every day. This is the working section.** |
| 20 | Reconciliation of existing code | First, before any new feature |
| 21 | Documentation deliverables | Ongoing, finalized at the end |
| 22 | Assignment compliance matrix | Before submitting |
| 23 | Deferred scope | When asked "what about X" |
| 24 | Decision log | When a decision needs explaining |

---

## 1. Product definition

### 1.1 What EMS Pro is

EMS Pro is a multi-tenant SaaS platform where many separate companies use one deployment, and no company can ever see another company's data. Each company gets HR management, payroll, performance reviews, and project tracking in one system, so data flows between them without re-entry.

The core value of building all of it together is that the modules feed each other:

```
Employee joins (HR)
  → gets a salary structure (Payroll)
  → is assigned to a project (Projects)
  → logs time on tasks (Projects)
  → time feeds attendance (HR)
  → attendance feeds the monthly payroll run (Payroll)
  → performance is reviewed (Performance)
  → rating triggers a salary revision (Payroll)
  → employee resigns (HR)
  → tasks are reassigned (Projects)
  → full-and-final settlement is computed (Payroll)
```

Every one of those arrows is a real foreign key or a real service call in this design. None of them is a manual export-and-reimport.

### 1.2 Two scopes — read this carefully

There are two distinct scopes in this project, and confusing them is the most likely way to miss a deadline.

**Scope A — Assignment scope (must ship first, complete and polished).**
The Python Developer Assignment requires, at minimum: User Authentication, Dashboard, Department Management, Employee Management, Attendance Management, Leave Management — with full CRUD, validation, search, filtering, sorting, pagination, a working frontend, unit tests, migrations, and documentation. This is a complete, evaluable product on its own.

**Scope B — EMS Pro full product.**
Payroll, Performance Management, Projects & Tasks, and Platform services (documents, announcements, notifications, global search) extend Scope A into the full SaaS vision.

**The build order in Section 19 finishes Scope A entirely — including tests, frontend, and documentation — before starting Scope B.** A complete small system beats an incomplete large one in every evaluation that has ever existed.

### 1.3 User roles

Four roles. Role plus `company_id` together determine what a user can access.

| Role | Scope | Can do |
|---|---|---|
| `super_admin` | Platform-wide | Approve/reject company registrations, view any company, manage global tax slabs. The only role that crosses tenant boundaries. |
| `hr_admin` | One company | Everything within their company: employees, departments, attendance, leave approval, payroll, settings, audit logs |
| `manager` | One company, own team | Approve their team's leave, review their team's performance, manage projects they lead |
| `employee` | One company, own records | Own profile, own KYC, own attendance, own leave, own payslip, assigned tasks |

**Rule:** `super_admin` is the *only* role permitted to read across companies, and every such access is written to `audit_logs`. Section 8.5 specifies how this is enforced without weakening RLS for everyone else.

### 1.4 Definition of done for the product

The system is done when all of the following are true and demonstrable:

- Two companies exist; an automated test proves company A's authenticated user receives zero rows of company B's data on every tenant-scoped endpoint.
- An employee can be invited, activate their own account, mark attendance, and apply for leave that correctly respects the company holiday calendar and leave policy.
- A payroll run for a multi-employee company produces payslips whose component breakdown matches values calculated by hand for at least three different salary levels.
- A full performance cycle can be created, goals set, and both self and manager ratings submitted.
- A project can be created, tasks assigned and completed, and a report produced from logged time.
- The system is deployed, backed up (with one restore actually tested), error-tracked, and has survived a modest load test.

---

## 2. The nine engineering rules

Every architectural choice in this document is an application of one of these. When a decision is unclear, resolve it by asking which rule applies.

| # | Rule | What it means | How it is enforced |
|---|---|---|---|
| 1 | **Database-level tenant isolation** | Company A cannot see company B's data even if the application code has a bug | PostgreSQL Row-Level Security on every tenant table, *plus* explicit `company_id` filtering in application code as a second layer. Section 8. |
| 2 | **Opaque primary keys** | IDs must not leak record counts, creation order, or volume across tenants | UUID primary keys on every table. No auto-increment integers anywhere. Section 6.4. |
| 3 | **Security from day one** | Security is part of the schema, not a later patch | Argon2id password hashing, 15-minute access tokens, rotating one-time refresh tokens stored only as hashes, AES-256 encryption on KYC identifiers. Section 9. |
| 4 | **Modular monolith** | One deployable codebase, organized by business domain | `app/modules/{identity,hr,time_leave,performance,payroll,projects,platform}/` — not `models/`, `routes/`, `services/` folders. Section 4. |
| 5 | **Strict layering** | Business logic never touches HTTP or SQL directly | Router → Service → Repository → Model. Four layers, one direction. Section 5.2. |
| 6 | **Contract-first API** | Frontend types are generated from the backend, never hand-written twice | FastAPI emits OpenAPI → `openapi-typescript` generates frontend types. Section 14.5. |
| 7 | **Configuration over code** | Rates, slabs, policies and thresholds are data | `statutory_configs`, `pt_slabs`, `tax_slabs`, `leave_types`, `industry_presets` are tables. Changing a rate is a data change. Sections 7, 12. |
| 8 | **Reversible schema changes** | Every schema change is tracked and reversible | Alembic from the first migration. No hand-written `ALTER TABLE` against a live database, ever. Section 7.1. |
| 9 | **Testing is architecture, not cleanup** | The isolation test suite is a structural component | CI blocks merge if the cross-tenant isolation suite fails. Every work package includes its own tests. Section 15. |

---

## 3. Technology stack

Every choice below is fixed for this build. Do not substitute without amending this section and recording the reason in Section 24.

### 3.1 Backend

| Concern | Choice | Why this, and what it replaces |
|---|---|---|
| Language | Python 3.12+ | Assignment requirement; modern typing syntax (`str \| None`) used throughout |
| Web framework | FastAPI | Automatic OpenAPI/Swagger docs, Pydantic request validation at the edge, dependency injection |
| ORM | SQLAlchemy 2.0, **synchronous** | Simpler mental model for a first production build: no event loop, no `async`/`await` propagation, far simpler test setup. Revisit async only when measured concurrent load justifies it. |
| DB driver | `psycopg[binary]` (psycopg 3) | Current generation driver, maintained. `psycopg2-binary` also works; pick one and pin it. |
| Database | PostgreSQL 16 | Row-Level Security (rule 1 is impossible without it), JSONB, mature |
| Migrations | Alembic | Autogenerates from models, version-controlled, reversible |
| Validation | Pydantic v2 | Request/response schemas, and `pydantic-settings` for `.env` loading |
| Email validation | `email-validator` (or the `pydantic[email]` extra) | Required by Pydantic's `EmailStr`, used on every request/response schema with an email field. Not pulled in automatically by `pydantic` alone — pin it explicitly. |
| Password hashing | Argon2id via **`argon2-cffi`** (`PasswordHasher`), used directly | Memory-hard, GPU-resistant, actively maintained. **Do not use `passlib`** — its last release (1.7.4, 2020) imports the standard-library `crypt` module, which was removed in Python 3.13. Depending on it would put a hard interpreter ceiling on the whole project, for a wrapper around the library below it. |
| JWT | **`PyJWT`** | Actively maintained. **Do not use `python-jose`** — it has published security advisories; check the current advisory list yourself before using any JWT library. |
| Rate limiting | `slowapi` with Redis storage | Blocks credential-stuffing on `/auth/login` |
| Cache / broker | Redis 7 | Rate-limit counters, dashboard cache, OTP storage with TTL, Celery broker |
| Background jobs | Celery | Payroll runs, CSV/PDF generation, email — anything that must not block an HTTP response |
| Email | SendGrid (free tier) | Activation links, password reset OTP, payslip notifications. In development, write emails to console/file instead. |
| File storage | AWS S3 or Cloudinary | KYC documents, receipts, generated letters — always via time-limited signed URLs, never a public bucket |
| Testing | `pytest` + `httpx` | Unit tests (no DB) and integration tests (real test DB, rollback per test) |
| Lint + format | **`ruff`** (`ruff check` + `ruff format`) | One fast tool replacing flake8 + isort + black. Configured in `pyproject.toml`. |
| Type checking | `mypy` (advisory, not blocking) | Catches whole classes of bugs; do not let it block progress early on |
| Error tracking | Sentry | Real backend and frontend errors, with stack traces, from real users |

### 3.2 Frontend

| Concern | Choice | Why |
|---|---|---|
| Framework | React 18 + TypeScript | Assignment permits any; TS gives compile-time safety against API shape drift |
| Build tool | Vite | Fast dev server, simple config |
| Routing | React Router v6 | Standard, well documented |
| Styling | Tailwind CSS | Utility-first; no separate CSS files to keep in sync |
| Components | shadcn/ui (Radix + Tailwind) | Accessible primitives that live in your own codebase — no black-box dependency |
| Server state | TanStack Query + Axios | Caching, loading and error states, refetch. **Start with plain Axios calls; adopt TanStack Query once the basic flow is comfortable.** |
| Forms | React Hook Form + Zod | Zod schemas mirror backend Pydantic schemas |
| API types | `openapi-typescript` | Generated from the live backend OpenAPI spec — rule 6 |

The assignment states explicitly that advanced UI/UX is **not** required. The frontend must be clean, functional and prove end-to-end API integration. Do not spend build time on animation, theming, or design polish before Scope A is complete.

### 3.3 Infrastructure

| Concern | Choice |
|---|---|
| Local development | Docker Compose (PostgreSQL + Redis), API and worker run on the host for fast reload |
| Containerization | Docker (multi-stage build for production) |
| CI | GitHub Actions — lint, type-check, `pytest` on every push |
| Hosting (launch) | Railway or Render — managed Postgres + Redis, simple staging environment |
| Hosting (scale) | AWS ECS / GCP Cloud Run — only when VPC, compliance, or fine-grained scaling is actually needed |

---

## 4. Repository structure

Organized by **business domain**, not by file type. Everything about payroll lives in one folder, rather than being scattered across `models/`, `schemas/`, and `routes/`.

*Why: when you change how payroll works, you open one directory. When a folder is per-file-type, one feature change touches five distant folders and it becomes easy to forget one.*

```
ems-pro/
├── .github/workflows/ci.yml        # lint + type-check + pytest on every push
├── .claude/
│   ├── settings.json               # permissions + hooks (Section 18.4)
│   └── commands/                   # reusable slash commands (Section 18.5)
├── docker-compose.yml              # PostgreSQL + Redis for local dev
├── Dockerfile                      # production API image (multi-stage)
├── pyproject.toml                  # dependencies, ruff config, pytest config
├── alembic.ini
├── alembic/
│   ├── env.py                      # imports app.db.base:Base as target_metadata
│   └── versions/                   # every migration, committed
├── .env.example                    # committed, placeholder values only
├── .env                            # git-ignored, real values
├── CLAUDE.md                       # short project context for the agent
├── README.md                       # setup, run, deploy, API docs link, assumptions
├── docs/
│   ├── EMS_PRO_DEV_SPEC.md         # this document
│   ├── ERD.md                      # entity relationship diagram (mermaid)
│   ├── RECONCILIATION.md           # WP-01 audit of the existing code (Section 20)
│   ├── SECURITY_AUDIT.md           # WP-28 self-audit output
│   └── postman_collection.json     # exported API collection
│
├── app/
│   ├── main.py                     # FastAPI assembly: middleware, routers, exception handlers, lifespan
│   │
│   ├── core/
│   │   ├── config.py               # pydantic-settings Settings, single `settings` instance
│   │   ├── security.py             # hashing, JWT encode/decode, refresh-token generation
│   │   ├── encryption.py           # AES-256-GCM encrypt/decrypt for KYC fields
│   │   ├── dependencies.py         # get_current_user, require_role, get_tenant_db
│   │   ├── exceptions.py           # AppError hierarchy + FastAPI exception handlers
│   │   ├── pagination.py           # PageParams, Page[T] envelope
│   │   ├── rate_limit.py           # slowapi limiter instance
│   │   ├── middleware.py           # request-id correlation, security headers
│   │   ├── time.py                 # utcnow() — the single time source (6.3)
│   │   └── logging.py              # structured JSON logging config
│   │
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase, TimeStampedBase, TenantBase
│   │   ├── session.py              # engine, SessionLocal, get_db
│   │   ├── rls.py                  # set_tenant_context() helper
│   │   └── seed/                   # industry presets, PT slabs, tax slabs, demo data
│   │
│   ├── modules/
│   │   ├── identity/               # companies, users, auth, refresh tokens
│   │   ├── hr/                     # employees, departments, KYC, work experience, documents
│   │   ├── time_leave/             # attendance, shifts, holidays, leave types/policies/requests
│   │   ├── performance/            # cycles, goals, reviews, summaries
│   │   ├── payroll/                # structures, components, statutory config, runs, payslips, reimbursements
│   │   ├── projects/               # projects, members, tasks, comments, time entries, milestones
│   │   └── platform/               # dashboard, announcements, notifications, audit log, search, files
│   │
│   └── workers/
│       ├── celery_app.py           # Celery instance and config
│       └── tasks/                  # payroll_tasks.py, export_tasks.py, email_tasks.py
│
├── tests/
│   ├── conftest.py                 # fixtures: test DB, client, auth headers per role
│   ├── unit/                       # pure logic, no database (payroll engine, leave math)
│   ├── integration/                # real DB, real routes
│   └── isolation/                  # MANDATORY cross-tenant isolation suite
│
└── frontend/
    ├── src/
    │   ├── app/                    # router, providers, auth context, axios instance
    │   ├── modules/                # hr/, time_leave/, payroll/, performance/, projects/
    │   ├── shared/
    │   │   ├── ui/                 # shadcn components
    │   │   ├── components/         # DataTable, PageHeader, ConfirmDialog, JobStatus
    │   │   ├── api/                # generated types (openapi-typescript) + api client
    │   │   └── hooks/
    │   └── main.tsx
    ├── .env.example
    └── package.json
```

### 4.1 Every module has exactly these files

**This is the single most important convention in the codebase.** Every one of the seven modules follows it identically. Once one module is understood, all seven are understood.

```
app/modules/<module_name>/
├── __init__.py
├── models.py        # SQLAlchemy tables ONLY. No logic.
├── schemas.py       # Pydantic request/response shapes ONLY. No logic.
├── repository.py    # Database queries ONLY. No business rules, no HTTP.
├── service.py       # Business rules ONLY. No SQL, no HTTP objects.
├── router.py        # HTTP routes ONLY. No business rules, no SQL.
└── constants.py     # Enums and module constants (optional, when it earns its place)
```

Large modules may split a file into a package — `service/` containing `payroll_service.py` and `payslip_engine.py` — but the layer boundaries stay exactly the same.

---

## 5. Architecture

### 5.1 The request lifecycle

Follow this end to end once; every route in the system works this way.

```
HTTP request
   ↓
[ CORS middleware ]                       — is this origin allowed?
   ↓
[ Rate limit middleware ]                 — has this IP exceeded its budget?
   ↓
[ Request-ID / logging middleware ]       — attach a correlation id to every log line
   ↓
[ Route handler in router.py ]
   ├─ FastAPI validates the body against the Pydantic schema  → 422 automatically if wrong
   ├─ Depends(get_current_user)            — verify JWT, load user
   ├─ Depends(require_role(...))           — is this role allowed here?
   └─ Depends(get_tenant_db)               — open session, bind tenant via set_config (8.4)
   ↓
[ Service ]                               — business rules; raises AppError subclasses
   ↓
[ Repository ]                            — SQLAlchemy queries; returns model instances
   ↓
[ PostgreSQL ]                            — RLS policies filter rows by tenant, independently
   ↓
[ Service returns domain objects ]
   ↓
[ Router returns them; FastAPI serializes via response_model ]
   ↓
[ Exception handlers convert AppError → consistent JSON error envelope ]
   ↓
HTTP response
```

### 5.2 The four layers and their contracts

Dependencies point in one direction only: **router → service → repository → model.** Never backwards, never skipping in the wrong direction.

**`models.py` — the table definition**
- Contains: SQLAlchemy `Mapped[...]` columns, relationships, table args, indexes, constraints
- Must not contain: business logic, validation rules, computed business values
- Knows about: nothing else in the module

**`schemas.py` — the wire format**
- Contains: Pydantic `BaseModel` classes for requests and responses, field validators for *format* (email shape, string length, date ordering)
- Must not contain: database access, business rules that need other records
- Response schemas set `model_config = ConfigDict(from_attributes=True)` so they read directly from ORM objects
- **Never** expose `hashed_password`, raw refresh tokens, or unmasked encrypted fields in any response schema

**`repository.py` — the data access layer**
- Contains: every SQLAlchemy query for this module. `get_by_id`, `get_by_email`, `list_paginated`, `create`, `update`, `soft_delete`
- Must not contain: `HTTPException`, business rules, decisions about *whether* something is allowed
- Takes a `Session` in `__init__`. Returns model instances or `None`. Never returns HTTP objects.
- Does not commit — the service owns transaction boundaries (Section 6.7)

**`service.py` — the business rules**
- Contains: all decisions. "Is this email already taken?" "Can this employee apply for leave on this date?" "What is the net salary?"
- Must not contain: raw SQL, `db.query(...)` — it calls repositories
- Raises `AppError` subclasses from `core/exceptions.py`, never `HTTPException` directly
- This is the layer that unit tests target, because it can be tested with fake repositories and no database

**`router.py` — the HTTP surface**
- Contains: `@router.get/post/put/delete`, path/query parameters, `response_model`, status codes, dependency declarations
- Must not contain: business rules, SQL, calculations
- Ideal route body is one to three lines: build the service, call one method, return the result

**The test:** if you deleted `router.py` and drove the services from a command-line script instead, everything should still work. If it doesn't, business logic has leaked into the router.

### 5.3 Worked example — `POST /api/v1/auth/login`

```python
# router.py — HTTP only
@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)):
    result, raw_refresh = AuthService(db).login(payload, device_info=request.headers.get("user-agent"))
    set_refresh_cookie(response, raw_refresh)   # httpOnly cookie — never in the JSON body (9.2)
    return result
```

```python
# service.py — business rules only
def login(self, payload: LoginRequest, device_info: str | None) -> tuple[TokenResponse, str]:
    # May return more than one row: the same email can exist at two companies (7.2).
    # Includes inactive users, so we can tell "wrong password" from "not activated".
    candidates = self.users.find_by_email(payload.email, payload.company_code)

    matched = [u for u in candidates if verify_password(payload.password, u.hashed_password)]
    if not candidates:
        # Verify against a fixed hash anyway, so response time does not reveal
        # whether the email exists (9.3). DUMMY_HASH is a constant Argon2id hash.
        verify_password(payload.password, DUMMY_HASH)

    if not matched:
        for u in candidates:
            self.users.increment_failed_attempts(u)   # repository stages it…
        self.db.commit()                              # …the SERVICE commits it (6.7)
        raise InvalidCredentialsError()               # deliberately generic — 9.3

    if len(matched) > 1:
        # Same email AND same password at two companies. Only someone who already
        # proved the password reaches this branch, so the company names leak nothing.
        raise CompanyRequiredError(companies=[u.company.name for u in matched])

    user = matched[0]

    # Both checks come after a proven password, for the same reason (9.3).
    if user.locked_until and user.locked_until > utcnow():
        raise AccountLockedError(until=user.locked_until)   # 423, not 401 (9.4)
    if not user.is_active:
        raise AccountInactiveError()                        # invited-not-activated, or deactivated

    self.users.reset_failed_attempts(user)
    access = create_access_token(sub=str(user.id), company_id=str(user.company_id), role=user.role)
    raw_refresh = generate_refresh_token()
    self.tokens.create(user_id=user.id, token_hash=hash_token(raw_refresh),
                       expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                       device_info=device_info)
    self.db.commit()
    # The raw refresh token leaves the service exactly once, to be written as an
    # httpOnly cookie by the router. It is never a field on a response schema.
    return TokenResponse(access_token=access, token_type="bearer"), raw_refresh
```

```python
# repository.py — queries only
def get_by_email(self, email: str) -> User | None:
    return self.db.scalar(
        select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
    )
```

Note what each layer does *not* know. The repository does not know what a failed login means. The service does not know it is being called over HTTP. The router does not know what a password is.

---

## 6. Coding standards

### 6.1 Naming

| Thing | Convention | Example |
|---|---|---|
| Python module / package | `snake_case` | `time_leave`, `payslip_engine.py` |
| Class | `PascalCase` | `EmployeeService`, `LeaveRequest` |
| Function / variable | `snake_case` | `calculate_net_salary`, `working_days` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_LOGIN_ATTEMPTS` |
| Database table | `snake_case`, **plural** | `employees`, `payroll_items`, `leave_types` |
| Database column | `snake_case`, singular | `first_name`, `company_id`, `is_active` |
| Foreign key column | `<singular_table>_id` | `company_id`, `department_id`, `reporting_manager_id` |
| Boolean column | `is_` / `has_` / `must_` prefix | `is_active`, `has_resigned`, `must_change_password` |
| Timestamp column | `_at` suffix | `created_at`, `approved_at`, `deleted_at` |
| Date column | `_date` suffix | `hire_date`, `start_date` |
| Index | `ix_<table>_<columns>` | `ix_employees_company_id_email` |
| Unique constraint | `uq_<table>_<columns>` | `uq_employees_company_id_employee_code` |
| API route path | `kebab-case`, plural nouns | `/api/v1/work-experience`, `/api/v1/employees` |
| React component | `PascalCase.tsx` | `EmployeeTable.tsx` |
| TS variable/function | `camelCase` | `fetchEmployees` |

### 6.2 Typing

Full type hints on every function signature. Modern syntax throughout.

```python
def get_by_id(self, employee_id: UUID) -> Employee | None: ...
def list_active(self, company_id: UUID) -> list[Employee]: ...
```

Not `Optional[Employee]`, not `List[Employee]`. `X | None` and `list[X]`.

### 6.3 Timestamps and time zones

- **Every timestamp column is `TIMESTAMP WITH TIME ZONE`.** No exceptions.
- **Everything is stored in UTC.** Conversion to local time is a display concern, done in the frontend.
- Use `datetime.now(timezone.utc)`, never the deprecated `datetime.utcnow()`.
- Define one helper, `app/core/time.py::utcnow()`, and use it everywhere so the whole system can be time-mocked in tests.

*Why: mixing naive and aware datetimes produces comparison errors that only appear in production, usually around a DST boundary, usually in payroll.*

### 6.4 Primary keys

Every table's primary key is a UUID stored as PostgreSQL `UUID`, generated in Python.

```python
id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

**Decision: UUID v4 for this build.** UUID v7 is time-ordered and gives better B-tree index locality on large tables, which is a real advantage at scale. It is available through the third-party `uuid6` package on PyPI, and some newer Python versions ship it in the standard library — verify `uuid.uuid7` actually exists in your interpreter before depending on it rather than assuming. Because the column type is identical either way, switching the default generator later is a one-line change with no migration. Do not spend time on it now.

### 6.5 Soft delete

Tables that participate in history — employees, payroll, audit trails — are never hard-deleted.

- Every such table has `deleted_at: TIMESTAMPTZ NULL`.
- Repositories filter `deleted_at IS NULL` by default; an explicit `include_deleted=True` argument opts out.
- `payroll_items` and `audit_logs` are strictly **append-only**: no `UPDATE` or `DELETE` path exists in the application, and the database role has no such grant (8.2).
- `payroll_runs` is **insert-plus-status-only**: after insert, the only writable columns are `status`, the five `total_*` columns (`total_employees`, `total_gross`, `total_deductions`, `total_net`, `total_employer_cost`), `approved_by`, `approved_at` and `error_message`. Legal status transitions are `draft → processing → pending_approval → approved → paid`, plus `processing → failed`. No other column is ever updated, and a run is never deleted.

*Why: deleting an employee who has been paid destroys the record of a real financial transaction. Legally and practically, that data must survive.*

### 6.6 Error handling

One error hierarchy, one response shape, no bare `HTTPException` in services.

```python
# app/core/exceptions.py
class AppError(Exception):
    status_code: int = 400
    code: str = "app_error"
    def __init__(self, message: str, *, details: dict | None = None): ...

class NotFoundError(AppError):      status_code, code = 404, "not_found"
class ValidationError(AppError):    status_code, code = 422, "validation_error"
class ConflictError(AppError):      status_code, code = 409, "conflict"
class ForbiddenError(AppError):     status_code, code = 403, "forbidden"
class UnauthorizedError(AppError):  status_code, code = 401, "unauthorized"
class RateLimitedError(AppError):   status_code, code = 429, "rate_limited"
```

Every error response has the same envelope:

```json
{
  "error": {
    "code": "conflict",
    "message": "An employee with this email already exists in your company.",
    "details": {"field": "email"},
    "request_id": "0f3c9a2e-6b1d-4a9e-9d7b-2f0c1a5e8b44"
  }
}
```

Rules:
- Messages are written for a human user, not a developer. "Employee not found" — not "NoneType has no attribute id".
- Never leak internals: no stack traces, no SQL, no table names in a 4xx message.
- Every 5xx is logged with the full stack trace and reported to Sentry with the same `request_id`.
- Register handlers in `main.py` for `AppError`, `RequestValidationError`, `IntegrityError`, and a catch-all `Exception`.

### 6.7 Transactions

**The service layer owns transaction boundaries.** Repositories add to the session and flush when they need a generated id; they never commit.

```python
# service — the whole operation succeeds or none of it does
def approve_company(self, company_id: UUID, admin: User) -> Company:
    company = self.companies.get_or_404(company_id)
    company.status = CompanyStatus.active
    self.departments.bulk_create_from_preset(company)
    self.leave_types.create_defaults(company)
    hr_user = self.users.create_hr_admin(company)
    self.audit.log("COMPANY_APPROVED", actor=admin, company_id=company_id)
    self.db.commit()        # ← one commit, at the end
    return company
```

If department seeding fails, the company is not left half-approved.

### 6.8 Logging

Structured JSON to stdout. Never `print()`.

```python
logger.info("payroll_run_completed", extra={
    "request_id": ctx.request_id, "company_id": str(company_id),
    "run_id": str(run.id), "employee_count": 42, "duration_ms": 1830,
})
```

**Never log:** passwords, raw tokens, Aadhaar, PAN, bank account numbers, full salary figures tied to a named individual. Log identifiers, not secrets.

### 6.9 API versioning

Every route is mounted under `/api/v1`. This is set once, in `main.py`, via the router prefix — individual routers declare only their own segment (`/auth`, `/employees`).

*Why: when a breaking change is needed, `/api/v2` can be introduced alongside without breaking existing clients. Retrofitting a version prefix later means touching every route and every frontend call.*

### 6.10 Git

- Branch per work package: `feat/wp-07-employees`, `fix/leave-overlap-check`
- Conventional commit messages: `feat(hr): add employee invite-activation flow`
- One logical change per commit; the message says *why*, not just *what*
- `main` stays green — CI must pass before merge
- Never commit `.env`, `__pycache__/`, `venv/`, `node_modules/`, `*.pyc`, `.DS_Store`

The assignment is explicitly evaluated on Git usage and commit history. Commits are part of the deliverable.

---

## 7. Complete database schema

40 tables across 7 modules. Every table below is authoritative — column names, types, and constraints are as specified here.

### 7.1 Universal rules for every table

| Rule | Detail |
|---|---|
| Primary key | `id UUID PRIMARY KEY` — generated in Python with `uuid.uuid4` |
| Timestamps | `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` with `onupdate` |
| Soft delete | `deleted_at TIMESTAMPTZ NULL` on every table except append-only ones |
| Tenant column | `company_id UUID NOT NULL REFERENCES companies(id)` on every tenant-scoped table |
| RLS | Enabled **and forced** on every table whose "RLS" column below says Yes |
| Index | Every foreign key gets an index. Every column used in a `WHERE` clause on a large table gets an index. |
| Migrations | Every change goes through Alembic. Never `ALTER TABLE` by hand against a database that has data in it. |
| Money | `NUMERIC(14, 2)` — never `FLOAT`, never `REAL`, never `DOUBLE PRECISION` |
| Percentages/rates | `NUMERIC(6, 3)` — e.g. `12.000` for 12% |
| Enums | PostgreSQL native `ENUM` via SQLAlchemy `Enum(PyEnum)`, backed by a Python `str, enum.Enum`. **Alembic autogenerate does not reliably emit `CREATE TYPE`, and never detects an added enum value — enum changes are hand-written into the migration**, the same way RLS policies are (8.3). |

Two shared base classes in `app/db/base.py`:

```python
class TimeStampedBase(Base):
    """id + created_at + updated_at + deleted_at. Non-tenant tables inherit this."""
    __abstract__ = True

class TenantBase(TimeStampedBase):
    """Everything above PLUS company_id. Tenant-scoped tables inherit this."""
    __abstract__ = True
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
```

**If a model inherits `TenantBase`, it must also have an RLS policy.** These two things go together, always. Section 8.

---

### 7.2 Identity & Tenancy (4 tables)

#### `companies` — RLS: **No** (platform-level table)

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(255) NOT NULL | |
| code | VARCHAR(20) UNIQUE NOT NULL | Auto-generated slug, e.g. `ACME-4F2K`. Used in employee codes. |
| email | VARCHAR(255) UNIQUE NOT NULL | Primary contact, lowercased |
| phone | VARCHAR(20) NULL | |
| industry | VARCHAR(100) NULL | Drives department presets on approval |
| country | VARCHAR(2) NOT NULL DEFAULT 'IN' | ISO 3166-1 alpha-2 |
| currency | VARCHAR(3) NOT NULL DEFAULT 'INR' | ISO 4217 |
| gst_number | VARCHAR(20) NULL | |
| pan_number | VARCHAR(10) NULL | Company PAN, not an individual's |
| address, city, state, pincode | VARCHAR | |
| website | VARCHAR(255) NULL | |
| logo_url | TEXT NULL | Signed URL or S3 key |
| status | ENUM(`pending`,`active`,`suspended`,`rejected`) NOT NULL DEFAULT `pending` | |
| rejection_reason | TEXT NULL | |
| approved_at | TIMESTAMPTZ NULL | |
| approved_by | UUID NULL FK users(id) | Added by a later migration with `use_alter=True` — see the cycle note below |
| last_employee_seq | INTEGER NOT NULL DEFAULT 0 | Employee-code counter, incremented under a row lock (11.2) |

Indexes: `ix_companies_status`, unique on `code`, unique on `lower(email)`.

> **Migration ordering.** `users.company_id → companies.id` and `companies.approved_by → users.id` form a foreign-key cycle. Create `companies` **without** `approved_by` first, then `users`, then add `approved_by` in a follow-up migration (SQLAlchemy `use_alter=True`). Creating them in the other order makes `alembic upgrade head` fail on an empty database — which is exactly what CI checks.

#### `users` — RLS: **No** — see the note below

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| company_id | UUID NOT NULL FK companies(id) | |
| email | VARCHAR(255) NOT NULL | **Unique per company, not globally** — see note |
| username | VARCHAR(100) NULL | Unique per company when set |
| hashed_password | TEXT NOT NULL | Argon2id output |
| role | ENUM(`employee`,`manager`,`hr_admin`,`super_admin`) NOT NULL DEFAULT `employee` | |
| is_active | BOOLEAN NOT NULL DEFAULT false | Becomes true on activation |
| must_change_password | BOOLEAN NOT NULL DEFAULT false | |
| last_login_at | TIMESTAMPTZ NULL | |
| failed_attempts | INTEGER NOT NULL DEFAULT 0 | |
| locked_until | TIMESTAMPTZ NULL | Set by the lockout policy, Section 9.4 |

Constraints: `uq_users_company_id_email` on `(company_id, lower(email))` — case-insensitive, consistent with `companies.email`'s `unique on lower(email)` (7.2 above). `uq_users_company_id_username` on `(company_id, lower(username))`, same treatment, applied only where `username` is set.
Indexes: `ix_users_company_id`, `ix_users_email`.

> **Why `users` is not RLS-protected, and what replaces it.** Login, activation and password reset all have to find a user *before* any tenant context exists — there is no verified `company_id` yet, and under an unset context an RLS policy correctly returns zero rows (8.3), which would make login permanently fail. Rather than punch a hole in the policy or add a `SECURITY DEFINER` lookup function, `users` is scoped in the application layer, exactly like `refresh_tokens`:
>
> - Every `UserRepository` method except the three documented pre-authentication lookups (`find_active_by_email`, `get_by_activation_token`, `get_for_password_reset`) **requires a `company_id` argument** and filters on it. This is enforced by the method signatures, not by discipline.
> - Those three lookups are the only cross-company queries in the system outside the super-admin path, they return a single row, and none of them is reachable without the corresponding secret (password, activation token, OTP).
> - **No route ever returns a list of users.** Person-shaped listings come from `employees`, which is RLS-protected.
> - `tests/isolation/` covers this explicitly: a test asserts that every `UserRepository` method other than those three raises when called without a `company_id`.
>
> **`get_current_user` sets the tenant context from the verified JWT claim before it loads anything**, so every authenticated request downstream is under RLS from its first query (8.4).

> **Design note — email uniqueness.** Email is unique *within a company*, not across the platform. This lets the same person exist as an employee at two different companies with the same email, which is a normal SaaS requirement. It means login must resolve a company: either the user supplies their company code, or the API looks up all matching users and requires disambiguation when more than one is found. **Decision: login accepts `email` + `password` + optional `company_code`. If exactly one active user matches the email, log in. If more than one matches, return `409 conflict` with `code: "company_required"` and the list of company names, and the client re-submits with `company_code`.** Document this in the README as a design decision.

#### `refresh_tokens` — RLS: **No** (keyed by user, never queried across tenants)

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID NOT NULL FK users(id) ON DELETE CASCADE | |
| token_hash | TEXT NOT NULL | SHA-256 of the raw token. **The raw token is never stored.** |
| expires_at | TIMESTAMPTZ NOT NULL | |
| is_revoked | BOOLEAN NOT NULL DEFAULT false | |
| revoked_at | TIMESTAMPTZ NULL | |
| replaced_by_id | UUID NULL FK refresh_tokens(id) | Rotation chain — enables reuse detection |
| device_info | TEXT NULL | User-Agent string, truncated |
| ip_address | INET NULL | |

Indexes: unique on `token_hash`, `ix_refresh_tokens_user_id`.

#### `company_settings` — RLS: **Yes** — one row per company

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps | | `company_id` is UNIQUE — exactly one row per company |
| weekend_days | SMALLINT[] NOT NULL DEFAULT '{6,7}' | **The single authority on the working week.** ISO weekday numbers (Mon=1). `'{7}'` is a six-day week; `'{6,7}'` is five days. Nothing else encodes this — a separate `working_week_days` integer would be the same fact stored twice, free to disagree with this one. |
| half_day_hours_threshold | NUMERIC(4,2) NOT NULL DEFAULT 4 | Below this, a day is `half_day` (11.5) |
| full_day_hours | NUMERIC(4,2) NOT NULL DEFAULT 8 | |
| leave_year_type | ENUM(`calendar`,`financial`) NOT NULL DEFAULT `financial` | Which year `leave_balances.year` counts |
| leave_year_start_month | SMALLINT NOT NULL DEFAULT 4 | 4 = April, for an Indian financial year |
| payroll_working_days_basis | ENUM(`calendar_days`,`working_days`,`fixed_30`) NOT NULL DEFAULT `working_days` | The `working_days` input to the payslip engine (11.6) |

Seeded with defaults when a company is approved.

> **Why this is a table and not environment variables.** These are per-tenant policy, and every one of them changes a calculation. Putting `WORKING_DAYS_PER_WEEK` in `.env` would apply one company's working week to every company on the platform — a direct violation of engineering rule 7 and a wrong payslip for anyone who differs.

---

### 7.3 Core HR (5 tables)

#### `departments` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps | | |
| name | VARCHAR(150) NOT NULL | Unique per company |
| description | TEXT NULL | |
| head_employee_id | UUID NULL FK employees(id) | |

Constraint: `uq_departments_company_id_name`.
Delete is **blocked** when any active employee references the department — return `409 conflict` with the count.

#### `employees` — RLS: **Yes** — the central table

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps, deleted_at | | |
| user_id | UUID NULL UNIQUE FK users(id) | Null until the employee activates their account |
| employee_code | VARCHAR(30) NOT NULL | Unique per company, e.g. `ACME-0042` |
| first_name | VARCHAR(100) NOT NULL | |
| last_name | VARCHAR(100) NULL | |
| email | VARCHAR(255) NOT NULL | Work email, unique per company |
| personal_email | VARCHAR(255) NULL | |
| phone | VARCHAR(20) NULL | |
| department_id | UUID NULL FK departments(id) | |
| position | VARCHAR(150) NULL | Job title |
| level | VARCHAR(10) NULL | `L1`..`L5`, drives default salary structure |
| reporting_manager_id | UUID NULL FK employees(id) | Self-reference; must be same company |
| employment_type | ENUM(`full_time`,`part_time`,`contract`,`intern`) DEFAULT `full_time` | |
| hire_date | DATE NOT NULL | |
| probation_end_date | DATE NULL | |
| notice_period_days | INTEGER NOT NULL DEFAULT 30 | |
| is_active | BOOLEAN NOT NULL DEFAULT true | |
| invitation_status | ENUM(`not_sent`,`sent`,`activated`,`expired`) DEFAULT `not_sent` | |
| activation_token_hash | TEXT NULL | Hashed, like refresh tokens |
| activation_expires_at | TIMESTAMPTZ NULL | |
| resignation_status | ENUM(`none`,`submitted`,`approved`,`rejected`) DEFAULT `none` | |
| resignation_date | DATE NULL | |
| last_working_date | DATE NULL | |
| notice_waived | BOOLEAN NOT NULL DEFAULT false | Set when the resignation is approved — decides whether shortfall is recovered (11.8) |
| notice_recovery_days | INTEGER NOT NULL DEFAULT 0 | Shortfall days actually charged |

Constraints: `uq_employees_company_id_employee_code`, `uq_employees_company_id_email`.
Indexes: `ix_employees_company_id_department_id`, `ix_employees_company_id_is_active`, `ix_employees_reporting_manager_id`.
Check: `reporting_manager_id <> id`.

#### `employee_kyc` — RLS: **Yes** — contains encrypted PII

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps | | |
| employee_id | UUID NOT NULL UNIQUE FK employees(id) | One KYC record per employee |
| gender | VARCHAR(20) NULL | |
| date_of_birth | DATE NULL | |
| address, city, state, pincode | VARCHAR | |
| aadhaar_encrypted | BYTEA NULL | **AES-256-GCM ciphertext. Never plaintext.** |
| aadhaar_last4 | VARCHAR(4) NULL | For display without decrypting |
| pan_encrypted | BYTEA NULL | |
| pan_last4 | VARCHAR(4) NULL | |
| bank_account_encrypted | BYTEA NULL | |
| bank_account_last4 | VARCHAR(4) NULL | |
| bank_ifsc | VARCHAR(15) NULL | Not secret, stored plain |
| bank_name | VARCHAR(150) NULL | |
| emergency_contact_name | VARCHAR(150) NULL | |
| emergency_contact_phone | VARCHAR(20) NULL | |
| emergency_contact_relation | VARCHAR(50) NULL | |
| is_kyc_complete | BOOLEAN NOT NULL DEFAULT false | |
| aadhaar_verified, pan_verified | BOOLEAN DEFAULT false | |
| verified_by | UUID NULL FK users(id) | |
| verified_at | TIMESTAMPTZ NULL | |

**Access rule:** `GET /kyc/{employee_id}` returns masked values (`XXXX XXXX 1234`) by default. Full decryption requires `hr_admin` role **and** an explicit `?reveal=true` query parameter, and every reveal writes an `audit_logs` row. See Section 9.6.

#### `work_experiences` — RLS: **Yes**

| Column | Type |
|---|---|
| id, company_id, timestamps | |
| employee_id | UUID NOT NULL FK employees(id) |
| previous_company | VARCHAR(255) NOT NULL |
| position | VARCHAR(150) NULL |
| start_date, end_date | DATE |
| reason_for_leaving | TEXT NULL |
| is_verified | BOOLEAN DEFAULT false |
| verified_by | UUID NULL FK users(id) |

Check: `end_date IS NULL OR end_date >= start_date`.

#### `documents` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps | | |
| employee_id | UUID NULL FK employees(id) | Null for company-level documents |
| file_object_id | UUID NOT NULL FK file_objects(id) | The actual stored file |
| type | ENUM(`offer_letter`,`experience_letter`,`appraisal_letter`,`kyc_proof`,`payslip`,`other`) | |
| title | VARCHAR(255) NOT NULL | |
| uploaded_by | UUID NOT NULL FK users(id) | |

---

### 7.4 Time & Leave (7 tables)

#### `attendance` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| id, company_id, timestamps | | |
| employee_id | UUID NOT NULL FK employees(id) | |
| date | DATE NOT NULL | |
| check_in | TIMESTAMPTZ NULL | |
| check_out | TIMESTAMPTZ NULL | |
| status | ENUM(`present`,`absent`,`half_day`,`wfh`,`on_leave`,`holiday`,`weekend`) NOT NULL | |
| hours_worked | NUMERIC(5,2) NULL | Computed on check-out |
| source | ENUM(`web`,`mobile`,`system`,`import`) DEFAULT `web` | `system` = auto-marked by leave approval |
| notes | TEXT NULL | |

Constraint: `uq_attendance_employee_id_date` — **one record per employee per day, enforced by the database.**
Index: `ix_attendance_company_id_date`, `ix_attendance_employee_id_date`.

#### `shifts` — RLS: **Yes**

`name VARCHAR(100)`, `start_time TIME`, `end_time TIME`, `break_minutes INTEGER DEFAULT 60`, `night_allowance NUMERIC(14,2) DEFAULT 0`, `is_active BOOLEAN DEFAULT true`.
A shift whose `end_time < start_time` crosses midnight — the hours calculation must handle this.

#### `employee_shifts` — RLS: **Yes**

`employee_id`, `shift_id`, `effective_from DATE NOT NULL`, `effective_to DATE NULL`.
No two rows for the same employee may have overlapping date ranges — enforce in the service layer and cover with a test.

#### `holidays` — RLS: **Yes**

`name VARCHAR(150)`, `date DATE NOT NULL`, `is_optional BOOLEAN DEFAULT false`, `applies_to_department_id UUID NULL`.
Constraint: `UNIQUE NULLS NOT DISTINCT (company_id, date, applies_to_department_id)` (PostgreSQL 15+). The `NULLS NOT DISTINCT` clause is essential: with the default behaviour, NULL department values compare as distinct, so the same company-wide holiday could be inserted twice on the same date — and a double-counted holiday silently reduces every leave application spanning it (11.3).

#### `leave_types` — RLS: **Yes** — configurable per company, never hardcoded

| Column | Type | Notes |
|---|---|---|
| name | VARCHAR(50) NOT NULL | `annual`, `sick`, `casual`, `maternity`, `paternity`, `comp_off`, or custom |
| code | VARCHAR(20) NOT NULL | Stable identifier, unique per company |
| annual_allowance | NUMERIC(5,1) NOT NULL DEFAULT 0 | Days per year; supports half-days |
| carry_forward_limit | NUMERIC(5,1) NOT NULL DEFAULT 0 | Max days carried to next year |
| max_consecutive_days | INTEGER NULL | |
| requires_approval | BOOLEAN DEFAULT true | |
| is_paid | BOOLEAN DEFAULT true | Unpaid types create LOP in payroll |
| is_encashable | BOOLEAN DEFAULT false | Used in full-and-final settlement |
| is_active | BOOLEAN DEFAULT true | |

Seeded on company approval from a default set. **Do not put leave type names in a Python enum** — that would make them un-configurable, breaking rule 7.

#### `leaves` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| employee_id | UUID NOT NULL FK | |
| leave_type_id | UUID NOT NULL FK leave_types(id) | |
| start_date, end_date | DATE NOT NULL | |
| total_days | NUMERIC(5,1) NOT NULL | Computed excluding weekends and holidays — Section 11.3 |
| is_half_day | BOOLEAN DEFAULT false | |
| reason | TEXT NOT NULL | |
| status | ENUM(`pending`,`approved`,`rejected`,`cancelled`) DEFAULT `pending` | |
| approved_by | UUID NULL FK users(id) | |
| approved_at | TIMESTAMPTZ NULL | |
| rejection_reason | TEXT NULL | |

Check: `end_date >= start_date`.
Index: `ix_leaves_company_id_status`, `ix_leaves_employee_id_start_date`.

#### `leave_balances` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| employee_id, leave_type_id | UUID NOT NULL FK | |
| year | INTEGER NOT NULL | Calendar or financial year, per company setting |
| opening_balance | NUMERIC(5,1) DEFAULT 0 | Carried forward from last year |
| allocated | NUMERIC(5,1) NOT NULL | From `leave_types.annual_allowance` at allocation time |
| used | NUMERIC(5,1) DEFAULT 0 | |
| encashed | NUMERIC(5,1) DEFAULT 0 | |

Constraint: `uq_leave_balances_employee_type_year`.

*Why a table rather than computing on the fly: carry-forward, mid-year policy changes, and encashment at exit all need a stored, auditable opening position. A pure computation cannot answer "what was this employee's balance last March" after a policy change.*

---

### 7.5 Performance (4 tables)

#### `performance_cycles` — RLS: **Yes**
`name`, `cycle_type ENUM(annual, half_yearly, quarterly)`, `start_date`, `end_date`, `status ENUM(draft, active, closed)`, `self_review_deadline DATE`, `manager_review_deadline DATE`.

#### `performance_goals` — RLS: **Yes**
`employee_id`, `cycle_id`, `title VARCHAR(255)`, `description TEXT`, `weightage NUMERIC(5,2)`, `target_value TEXT`, `status ENUM(draft, in_progress, completed)`, `self_rating NUMERIC(3,1)`, `self_comments TEXT`.
Rule: the sum of `weightage` for one employee in one cycle must equal 100 before self-review can be submitted.

#### `performance_reviews` — RLS: **Yes**
`goal_id`, `reviewer_id FK users(id)`, `reviewer_role ENUM(self, manager, peer)`, `rating NUMERIC(3,1)`, `comments TEXT`, `submitted_at`.
Constraint: `uq_performance_reviews_goal_reviewer_role`.

#### `performance_summaries` — RLS: **Yes**
`employee_id`, `cycle_id`, `final_rating NUMERIC(3,1)`, `overall_comments TEXT`, `salary_revision_recommended BOOLEAN`, `recommended_increment_percent NUMERIC(5,2)`, `reviewed_by`, `finalized_at`.
Constraint: `uq_performance_summaries_employee_cycle`.

---

### 7.6 Payroll (9 tables)

#### `salary_structures` — RLS: **Yes**
`name VARCHAR(150)` (e.g. "India Standard L3"), `country VARCHAR(2) DEFAULT 'IN'`, `level VARCHAR(10) NULL`, `is_active BOOLEAN DEFAULT true`.

#### `salary_components` — RLS: **Yes**

| Column | Type | Notes |
|---|---|---|
| structure_id | UUID NOT NULL FK salary_structures(id) ON DELETE CASCADE | |
| name | VARCHAR(100) NOT NULL | `Basic`, `HRA`, `EPF` |
| code | VARCHAR(30) NOT NULL | Stable key used by the engine: `BASIC`, `HRA`, `EPF_EE` |
| type | ENUM(`earning`,`deduction`,`employer_contribution`) NOT NULL | |
| calculation_type | ENUM(`percentage`,`fixed`,`balance`,`statutory`) NOT NULL | `balance` = whatever remains of CTC |
| value | NUMERIC(14,3) NULL | Percent or fixed amount depending on `calculation_type` |
| percentage_of | ENUM(`ctc`,`basic`) NULL | Base for a percentage **earning**. `gross` is deliberately not an option: gross is not known until the `balance` component resolves, so a gross-based earning is self-referential (11.6b). Statutory deductions that are a percentage of gross — ESI — are computed by the engine, not from this column. |
| is_taxable | BOOLEAN NOT NULL DEFAULT true | |
| is_statutory | BOOLEAN NOT NULL DEFAULT false | Statutory components are computed by the engine, not from `value` |
| display_order | INTEGER NOT NULL DEFAULT 0 | Payslip ordering |

Constraint: `uq_salary_components_structure_code`.

> Carries `company_id` and its own policy even though it is a child of `salary_structures`. It holds a company's compensation design and is reachable by UUID through routes 78–81 — the redundancy costs one column and buys the guarantee in rule 1.

#### `employee_salaries` — RLS: **Yes**

`employee_id`, `structure_id`, `ctc NUMERIC(14,2) NOT NULL`, `effective_from DATE NOT NULL`, `effective_to DATE NULL`, `revision_reason VARCHAR(255)`, `created_by`.
**Append a new row for every revision; never update an old one.** The row where `effective_from <= payroll_date AND (effective_to IS NULL OR effective_to >= payroll_date)` is the one in force.
No two rows for the same employee may overlap — enforce in the service and test it.

#### `statutory_configs` — RLS: **Yes** — per-company statutory switches and rates

`country VARCHAR(2)`, `pf_enabled BOOLEAN`, `pf_employee_rate NUMERIC(6,3)`, `pf_employer_rate NUMERIC(6,3)`, `pf_wage_ceiling NUMERIC(14,2)`, `pf_restrict_to_ceiling BOOLEAN`, `esi_enabled BOOLEAN`, `esi_employee_rate NUMERIC(6,3)`, `esi_employer_rate NUMERIC(6,3)`, `esi_wage_ceiling NUMERIC(14,2)`, `pt_enabled BOOLEAN`, `pt_state VARCHAR(50)`, `lwf_enabled BOOLEAN`, `lwf_employee_amount NUMERIC(14,2)`, `lwf_months SMALLINT[]` (the months LWF is deducted in — many states deduct twice a year, not monthly), `tds_enabled BOOLEAN`, `default_tax_regime ENUM(old, new)`, `updated_by`.

**No rate in this table may ever appear as a literal in Python code.** Section 12.

#### `pt_slabs` — RLS: **No** (government-defined, platform-managed)
`state VARCHAR(50)`, `income_min NUMERIC(14,2)`, `income_max NUMERIC(14,2) NULL`, `monthly_amount NUMERIC(14,2)`, `special_month SMALLINT NULL` and `special_month_amount NUMERIC(14,2) NULL` (some states levy a different amount in one nominated month), `effective_from DATE`, `effective_to DATE NULL`, `source_note TEXT`.
`source_note` records where the figure came from and when it was verified. Seeded via `app/db/seed/pt_slabs.py`.

#### `tax_slabs` — RLS: **No** (government-defined, platform-managed)
`country VARCHAR(2)`, `financial_year VARCHAR(9)` (e.g. `2026-2027`), `regime ENUM(old, new)`, `min_income`, `max_income NULL`, `rate_percent NUMERIC(6,3)`, `cess_percent NUMERIC(6,3)`, `surcharge_rules JSONB NULL`, `effective_from DATE`, `source_note TEXT`.

#### `payroll_runs` — RLS: **Yes** — insert-plus-status-only (6.5)

| Column | Type | Notes |
|---|---|---|
| month | SMALLINT NOT NULL | 1–12 |
| year | SMALLINT NOT NULL | |
| status | ENUM(`draft`,`processing`,`pending_approval`,`approved`,`paid`,`failed`) | |
| run_type | ENUM(`regular`,`off_cycle`) NOT NULL DEFAULT `regular` | Off-cycle covers full-and-final settlements, arrears and bonuses (11.8) |
| idempotency_key | VARCHAR(100) NOT NULL | **Unique per company — prevents a retried request from double-processing** |
| total_employees | INTEGER | |
| total_gross, total_deductions, total_net, total_employer_cost | NUMERIC(14,2) | |
| run_by, approved_by | UUID FK users(id) | |
| approved_at | TIMESTAMPTZ NULL | |
| error_message | TEXT NULL | |

Constraints: `uq_payroll_runs_company_idempotency_key`, plus a **partial** unique index:

```sql
CREATE UNIQUE INDEX uq_payroll_runs_company_month_year_regular
  ON payroll_runs (company_id, month, year) WHERE run_type = 'regular';
```

It must be partial, not a four-column unique constraint. `UNIQUE(company_id, month, year, run_type)` would still cap off-cycle runs at one per month — so a second resignation settled in the same month, or arrears plus a bonus, would fail with a 409. Regular runs are capped at one per month; off-cycle runs are genuinely unlimited.

#### `payroll_items` — RLS: **Yes** — append-only, one payslip per employee per run

| Column | Type | Notes |
|---|---|---|
| payroll_run_id | UUID NOT NULL FK | |
| employee_id | UUID NOT NULL FK | |
| ctc_snapshot | NUMERIC(14,2) | The CTC in force at run time |
| gross_salary, total_deductions, net_salary, employer_cost | NUMERIC(14,2) NOT NULL | |
| earnings_json | JSONB NOT NULL | `[{"code":"BASIC","name":"Basic","amount":"25000.00"}, ...]` |
| deductions_json | JSONB NOT NULL | Same shape |
| employer_contributions_json | JSONB NOT NULL | PF employer, ESI employer |
| working_days, present_days, absent_days, half_days, paid_leave_days, lop_days | NUMERIC(5,1) | |
| reimbursement_amount | NUMERIC(14,2) DEFAULT 0 | |

Constraint: `uq_payroll_items_run_employee`.

> **Why JSONB snapshots rather than a normalized child table:** a payslip is a historical financial record. If the salary structure is edited next year, last year's payslip must still show exactly what was paid. Storing the computed breakdown as an immutable JSON snapshot guarantees that. The structure tables describe *how to compute future payslips*; the JSONB describes *what was actually paid*.

#### `reimbursements` — RLS: **Yes**
`employee_id`, `type ENUM(travel, food, medical, telephone, other)`, `amount NUMERIC(14,2)`, `expense_date DATE`, `description TEXT`, `file_object_id UUID NULL` (receipt), `status ENUM(pending, approved, rejected, paid)`, `approved_by`, `approved_at`, `rejection_reason`, `added_to_payroll_run_id UUID NULL`.

---

### 7.7 Projects (6 tables)

#### `projects` — RLS: **Yes**
`name VARCHAR(200)`, `code VARCHAR(30)` (unique per company), `description TEXT`, `status ENUM(planning, active, on_hold, completed, cancelled)`, `start_date`, `deadline`, `budget NUMERIC(14,2) NULL`, `manager_id UUID FK employees(id)`, `client_name VARCHAR(200) NULL`.

#### `project_members` — RLS: **Yes**
`project_id`, `employee_id`, `role ENUM(lead, member)`, `joined_at`, `left_at NULL`.
Constraint: `uq_project_members_project_employee`.

#### `tasks` — RLS: **Yes**
`project_id`, `title VARCHAR(255)`, `description TEXT`, `assigned_to UUID NULL FK employees(id)`, `priority ENUM(critical, high, medium, low) DEFAULT medium`, `status ENUM(todo, in_progress, review, done) DEFAULT todo`, `due_date DATE NULL`, `estimated_hours NUMERIC(6,2) NULL`, `completed_at TIMESTAMPTZ NULL`, `created_by`.
Sub-tasks and dependencies are deferred (Section 23) — v1 ships flat tasks.

#### `task_comments` — RLS: **Yes**
`task_id`, `user_id`, `comment TEXT NOT NULL`.

#### `time_entries` — RLS: **Yes**
`task_id`, `employee_id`, `date DATE NOT NULL`, `hours NUMERIC(5,2) NOT NULL`, `description TEXT`, `is_billable BOOLEAN DEFAULT false`, `status ENUM(draft, submitted, approved, rejected)`, `approved_by`, `approved_at`.
Check: `hours > 0 AND hours <= 24`.

#### `milestones` — RLS: **Yes**
`project_id`, `title VARCHAR(200)`, `description TEXT`, `due_date DATE`, `status ENUM(pending, in_progress, completed, missed)`, `completion_percentage SMALLINT DEFAULT 0`, `completed_at`.

---

### 7.8 Platform (5 tables)

#### `announcements` — RLS: **Yes**
`title VARCHAR(255)`, `content TEXT`, `priority ENUM(normal, important, urgent)`, `created_by`, `published_at`, `expires_at NULL`, `target_department_id UUID NULL`.

#### `notifications` — RLS: **Yes**
`user_id`, `type VARCHAR(50)`, `title VARCHAR(255)`, `message TEXT`, `is_read BOOLEAN DEFAULT false`, `read_at NULL`, `action_url VARCHAR(500) NULL`, `entity_type VARCHAR(50) NULL`, `entity_id UUID NULL`.
Index: `ix_notifications_user_id_is_read`.

#### `audit_logs` — RLS: **No** — append-only, no UPDATE or DELETE grants

| Column | Type | Notes |
|---|---|---|
| company_id | UUID NULL | Null for platform-level actions |
| actor_user_id | UUID NULL FK users(id) | |
| actor_email | VARCHAR(255) | Denormalized so the log survives user deletion |
| action | VARCHAR(80) NOT NULL | `EMPLOYEE_CREATED`, `KYC_REVEALED`, `PAYROLL_APPROVED` |
| entity_type | VARCHAR(50) NULL | |
| entity_id | UUID NULL | |
| details | JSONB NULL | **Never contains secrets or full PII** |
| ip_address | INET NULL | |
| user_agent | TEXT NULL | |
| request_id | UUID NULL | Correlates with application logs |

Index: `ix_audit_logs_company_id_created_at`, `ix_audit_logs_action`.

At the database level, grant only `SELECT, INSERT` on this table to the application role. No `UPDATE`, no `DELETE`. An audit log the application can rewrite is not an audit log.

> **Why no RLS here, when everything else has it.** `company_id` is nullable, because platform-level events (a super-admin approving a company, a refresh-token reuse detected before any tenant is known) genuinely have no tenant. The standard policy's `WITH CHECK` evaluates to NULL for a NULL `company_id`, which would make those rows impossible to insert at all — the audit trail would silently lose exactly the events that matter most. Scoping is therefore enforced in `AuditRepository`, whose read methods **require** a `company_id` and whose only unscoped reader is the super-admin path. `tests/isolation/` covers `GET /audit-logs` directly: company B's HR admin must never see one of company A's rows.

#### `industry_presets` — RLS: **No** (global seed data)
`industry_name VARCHAR(100) UNIQUE`, `departments_json JSONB`, `leave_types_json JSONB`.
Seeded once with 12 industries. Applied automatically when a company is approved.

#### `file_objects` — RLS: **Yes**
`storage_key TEXT NOT NULL` (S3 key — **not** a public URL), `original_filename VARCHAR(255)`, `content_type VARCHAR(100)`, `size_bytes BIGINT`, `checksum_sha256 VARCHAR(64)`, `uploaded_by UUID FK users(id)`, `scan_status ENUM(pending, clean, infected) DEFAULT pending`.

*Why one central file table: uploads happen in four places (KYC proofs, reimbursement receipts, HR documents, company logo). One table means one upload path, one signed-URL generator, one size/type validation, one place to add virus scanning later.*

---

### 7.9 Where OTPs live — not in the database

Password-reset OTPs are stored in **Redis** with a TTL, keyed by `pwreset:{email_hash}`, never in a table.

*Why: an OTP that must expire in 10 minutes should be deleted by the datastore automatically. A database column requires a cleanup job that will eventually be forgotten, leaving valid-looking OTP rows behind. Redis TTL removes an entire class of bug.*

Store the **hash** of the OTP, not the OTP itself, and cap verification attempts at 5 per key.

---

## 8. Multi-tenancy and Row-Level Security

This is the section that makes EMS Pro a real SaaS product rather than a single-company app with a `company_id` column. Get it wrong and every other feature is built on sand.

### 8.1 The threat this defends against

Application code filters by `company_id`. Eventually someone writes:

```python
db.query(Employee).filter(Employee.department_id == dept_id).all()   # ← forgot company_id
```

Without RLS, that query returns employees from every company on the platform. With RLS, PostgreSQL refuses to return other tenants' rows regardless of what the application asked for. **RLS is not a replacement for application-level filtering; it is the layer that catches the day application-level filtering is forgotten.**

### 8.2 Database roles

Two roles, and the distinction matters.

```sql
-- Migration/owner role: owns the schema, runs Alembic. Bypasses RLS as table owner.
CREATE ROLE ems_owner LOGIN PASSWORD '...';

-- Application runtime role: what the API connects as. MUST NOT be superuser,
-- MUST NOT have BYPASSRLS, and MUST NOT own the tables.
CREATE ROLE ems_app LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB NOBYPASSRLS;
GRANT CONNECT ON DATABASE ems_pro TO ems_app;
GRANT USAGE ON SCHEMA public TO ems_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ems_app;

-- CRITICAL: the GRANT above only covers tables that exist RIGHT NOW. Every table
-- Alembic creates afterwards — i.e. all 40 — would have no grants at all, and the
-- API would fail with "permission denied" on first use. This fixes that for the future:
ALTER DEFAULT PRIVILEGES FOR ROLE ems_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ems_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ems_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ems_app;

-- audit_logs and payroll_items are append-only:
REVOKE UPDATE, DELETE ON audit_logs, payroll_items FROM ems_app;
```

Run this as a bootstrap script (`app/db/seed/bootstrap_roles.sql`), committed to the repository, and re-run the explicit `GRANT`/`REVOKE` lines as a release step after migrations. A grant that exists only in someone's shell history is a production outage waiting for the next environment.

> **Critical:** a table's owner bypasses its own RLS policies by default. If the API connects as the table owner, every policy you write is silently inert. `FORCE ROW LEVEL SECURITY` (below) closes this for the owner too, but the correct configuration is still a separate, non-owning application role. `DATABASE_URL` in production must use `ems_app`. `ALEMBIC_DATABASE_URL` uses `ems_owner`.

### 8.3 The policy, applied to every tenant table

```sql
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON employees
  USING (
    company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
    OR current_setting('app.is_platform_admin', true) = 'on'
  )
  WITH CHECK (
    company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
    OR current_setting('app.is_platform_admin', true) = 'on'
  );
```

Three details that are easy to get wrong:

1. **`WITH CHECK` as well as `USING`.** `USING` filters what can be read and updated. `WITH CHECK` prevents *writing* a row belonging to another tenant. Without it, a bug could insert a row into company B while authenticated as company A.
2. **The `true` second argument to `current_setting`.** This makes it return `NULL` instead of raising when the setting is unset. Combined with `NULLIF(..., '')`, an unset context yields `NULL`, and `company_id = NULL` is never true — so **an unset tenant context returns zero rows, which is the safe failure mode.**
3. **`FORCE`** ensures the policy applies even to the table owner.

Write this as a reusable Alembic helper so adding a tenant table is one function call:

```python
# alembic helper
def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
               OR current_setting('app.is_platform_admin', true) = 'on')
        WITH CHECK (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'on');
    """)
```

### 8.4 Setting the context on every request

```python
# app/db/rls.py
from sqlalchemy import text
from sqlalchemy.orm import Session

def set_tenant_context(db: Session, company_id: uuid.UUID | None, is_platform_admin: bool) -> None:
    # set_config(..., is_local=true) is the parameterizable equivalent of SET LOCAL.
    # SET LOCAL itself cannot take bind parameters — string-building it would be an injection risk.
    db.execute(
        text("SELECT set_config('app.current_company_id', :cid, true)"),
        {"cid": str(company_id) if company_id else ""},
    )
    db.execute(
        text("SELECT set_config('app.is_platform_admin', :flag, true)"),
        {"flag": "on" if is_platform_admin else "off"},
    )
```

```python
# app/core/dependencies.py
def get_tenant_db(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Session:
    bind_tenant_to_session(
        db,
        company_id=user.company_id,
        is_platform_admin=(user.role == UserRole.super_admin),
    )
    return db
```

**`is_local=true` scopes the setting to the current transaction — which means it is cleared on every commit.** That is exactly the property that makes it safe with a connection pool (a leaked session-level setting would hand the next request the previous tenant's context — the bug that turns a pooled connection into a data breach). But it also means **setting it once in the dependency is not enough**: a service that commits and then reads again (6.7 does precisely this) would find the context gone, get zero rows back, and fail `WITH CHECK` on the next write. That failure is intermittent and looks like a data bug rather than a configuration bug, which makes it expensive to find.

The context must therefore be re-applied at the start of **every** transaction on that session, not once per request:

```python
# app/db/rls.py
from sqlalchemy import event

def bind_tenant_to_session(db: Session, company_id: uuid.UUID | None, is_platform_admin: bool) -> None:
    """Apply the tenant context now, and again automatically after every commit."""
    db.info["tenant"] = (company_id, is_platform_admin)
    set_tenant_context(db, company_id, is_platform_admin)

@event.listens_for(Session, "after_begin")
def _reapply_tenant_context(session, transaction, connection):
    ctx = session.info.get("tenant")
    if ctx is not None:
        set_tenant_context(session, *ctx)
```

**Two more rules that make this safe:**

- The `company_id` comes from the **verified JWT claim**, never from a request body, query parameter, or header. A client must never be able to name the tenant it wants.
- `get_current_user` calls `bind_tenant_to_session` from the JWT claim **before** it loads the user, so even the user lookup runs under the correct context.

**Test this specifically:** inside one request, write a row, commit, then read it back — and assert the row is still visible. Without the `after_begin` listener that test fails, and it is the cheapest possible way to catch the whole class of bug.

**Every tenant-scoped route depends on `get_tenant_db`, not `get_db`.** Public routes (login, register, activate) use `get_db`.

### 8.5 The super-admin path

`super_admin` sets `app.is_platform_admin = 'on'`, which the policy honours. This is a deliberate, single, auditable hole.

Requirements when this hole is used:
- The `super_admin` role is assigned only by direct database action or a seed script — never through an API route.
- Every request where `is_platform_admin` is on writes an `audit_logs` row with the action, the target company, and the actor.
- The cross-tenant isolation suite includes a test asserting that a `hr_admin` token can **never** cause `app.is_platform_admin` to be set.

### 8.6 The mandatory isolation test suite

`tests/isolation/` is not optional and CI must block on it.

The suite's shape:

```python
def test_employees_are_tenant_isolated(client, company_a, company_b):
    # Arrange: create an employee in company A
    emp = create_employee(client, token=company_a.hr_token, name="Alice")

    # Act: authenticate as company B and try every way in
    assert client.get("/api/v1/employees", headers=company_b.hr_headers).json()["items"] == []
    assert client.get(f"/api/v1/employees/{emp['id']}", headers=company_b.hr_headers).status_code == 404
    assert client.put(f"/api/v1/employees/{emp['id']}", json={...},
                      headers=company_b.hr_headers).status_code == 404
    assert client.delete(f"/api/v1/employees/{emp['id']}",
                         headers=company_b.hr_headers).status_code == 404
```

Rules for this suite:
- **404, not 403,** when a resource belongs to another tenant. A 403 confirms the record exists, which leaks information.
- **A test is added for every tenant table in the same work package that creates the table.** The suite grows continuously; it is never written in one push at the end.
- A parametrized test over the list of tenant tables catches a newly added table that was given `TenantBase` but no policy.

---

## 9. Security specification

### 9.1 Password hashing

```python
# app/core/security.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)  # 64 MiB

def hash_password(plain: str) -> str:
    return _hasher.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)

# A fixed hash of a throwaway value, used to keep login timing constant when no
# user matches the email (9.3). Generate once and paste the literal here.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$..."
```

- `argon2-cffi`'s `PasswordHasher` uses Argon2id by default.
- `check_needs_rehash` reports when a stored hash predates a parameter increase, so it can be transparently upgraded on the next successful login. Do that inside the login path.
- **Never** log, return, or store a plaintext password. It exists only inside the request that carries it.

Password policy, enforced in the Pydantic schema so it fails at the edge with a clear message: minimum 10 characters, at least one letter and one digit. Do not impose maximum length below 128 or forbid special characters.

### 9.2 Tokens

| Token | Lifetime | Storage | Revocable |
|---|---|---|---|
| Access token (JWT) | 15 minutes | Client memory (never `localStorage`) | No — short life is the mitigation |
| Refresh token (opaque random) | 7 days | Client: httpOnly cookie. Server: **SHA-256 hash only** | Yes, individually |

The refresh cookie's attributes are not optional and are set exactly like this:

```
Set-Cookie: refresh_token=<raw>; HttpOnly; Secure; SameSite=Lax;
            Path=/api/v1/auth; Max-Age=604800
```

- `HttpOnly` — JavaScript cannot read it, so a script injection cannot steal it.
- `Secure` — HTTPS only. Omit it **only** on `localhost`, driven by `ENVIRONMENT`.
- `SameSite=Lax` — the browser will not attach it to a cross-site POST.
- `Path=/api/v1/auth` — it is never sent to any other endpoint, so it cannot leak through an unrelated request.

**CSRF.** Because `/auth/refresh` is authenticated by a cookie the browser attaches automatically, it is the one endpoint in the system that is CSRF-exposed. `SameSite=Lax` blocks the common case; on top of it, **`/auth/refresh` requires a custom header (`X-Requested-With: ems-pro`)**. A cross-origin form post cannot set a custom header, and a cross-origin `fetch` that tries triggers a preflight that CORS (9.7) refuses. Every other endpoint uses the `Authorization` header, which is never attached automatically, so no CSRF defence is needed there.

Access token claims:

```json
{
  "sub": "<user_uuid>",
  "company_id": "<company_uuid>",
  "role": "hr_admin",
  "employee_id": "<employee_uuid_or_null>",
  "type": "access",
  "iat": 1756600000,
  "exp": 1756600900,
  "jti": "<uuid>"
}
```

Verification rules, all of them mandatory:
- Verify the signature with the **explicitly listed** algorithm: `jwt.decode(token, key, algorithms=["HS256"])`. Never pass the algorithm from the token header — that is the algorithm-confusion attack.
- Reject `type != "access"` — a refresh token must never be usable as an access token.
- Verify `exp`. PyJWT does this by default; do not disable it.
- Load the user from the database on every request and reject if `is_active` is false. A 15-minute window in which a deactivated user still has access is not acceptable for an HR system.

**Refresh rotation, in full:**

1. The browser sends the refresh cookie on `POST /auth/refresh`; the server reads the raw token from it (never from a JSON body).
2. Server hashes it and looks up the row.
3. If not found → `401`.
4. If `is_revoked` is true → **this is a reuse of an already-rotated token, which means the token was stolen.** Revoke *every* refresh token for that user and return `401`. Write an `audit_logs` entry.
5. If expired → `401`.
6. Otherwise: mark the old row revoked, set `replaced_by_id` to the new row, issue a new access + refresh pair.

Step 4 is the reason `replaced_by_id` exists. Without reuse detection, a stolen refresh token grants indefinite access.

### 9.3 Login responses must not leak

- Wrong email and wrong password both return the same message: `"Invalid email or password."`
- Never return "no account with that email" — that turns the login endpoint into an account-enumeration oracle.
- `POST /auth/forgot-password` returns `200` with the same body whether or not the email exists.
- `GET /auth/check-username/{username}` is the one deliberate exception, because a signup form needs it. Rate-limit it hard.

### 9.4 Account lockout

- `failed_attempts` increments on each failure and resets to 0 on success.
- At 5 consecutive failures, set `locked_until = utcnow() + 15 minutes`.
- While locked, return `423 Locked` with the unlock time.
- Rate limiting (below) is a separate, IP-based layer — lockout protects one account, rate limiting protects the endpoint.

### 9.5 Rate limiting

`slowapi` with Redis storage, so limits hold across multiple API processes.

| Endpoint | Limit |
|---|---|
| `POST /auth/login` | 10 / minute / IP |
| `POST /auth/forgot-password` | 3 / hour / IP |
| `POST /auth/refresh` | 30 / minute / IP |
| `GET /auth/check-username/*` | 20 / minute / IP |
| All other authenticated routes | 300 / minute / user |

Behind a proxy, read the client IP from the trusted forwarded header — do not trust `X-Forwarded-For` blindly from an untrusted network.

### 9.6 Encryption of KYC identifiers

Aadhaar, PAN and bank account numbers are encrypted at rest with **AES-256-GCM** (authenticated encryption — it detects tampering, which AES-CBC does not).

```python
# app/core/encryption.py
# Key: 32 random bytes, base64-encoded in ENCRYPTION_KEY. Never committed, never logged.
# Blob layout:  version(1 byte) || nonce(12) || ciphertext || tag(16)
# The version byte is also bound in as GCM associated data, so it cannot be
# altered without failing authentication.
def encrypt_field(plaintext: str) -> bytes: ...
def decrypt_field(blob: bytes) -> str: ...   # reads version, selects the matching key
```

Rules:
- Build and unit-test this utility **in isolation**, before wiring it into any route. Encrypt → decrypt → assert equality, plus assert that a tampered blob raises.
- Store `*_last4` alongside so lists and payslips can display a masked value without decrypting anything.
- Default API responses are masked. Full reveal requires `hr_admin` **and** `?reveal=true`, and writes an audit log row every time.
- Key rotation: the version byte at the head of every blob selects the key, so a future key change can still decrypt old values. `settings.ENCRYPTION_KEYS` is a `{version: key}` map and `ENCRYPTION_KEY_VERSION` names the one used for new writes. Rotation itself is deferred, but the format must support it from the first row written — retrofitting a version byte onto existing ciphertext means decrypting and rewriting every record.

### 9.7 CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,      # explicit list from env, e.g. ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "X-Requested-With"],
)
```

**`allow_origins=["*"]` with `allow_credentials=True` is invalid and browsers reject it.** Always an explicit list, always from configuration, never a wildcard in production.

### 9.8 Security headers

Add a small middleware setting, on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Strict-Transport-Security` in production only.

### 9.9 Input validation

- Pydantic validates every request body at the edge. Anything that reaches a service has already been shape-checked.
- Query parameters are typed and constrained (`Query(ge=1, le=100)`), never raw strings passed into a query.
- **All database access goes through SQLAlchemy's expression language or bound parameters.** No f-strings or `%` formatting building SQL, ever — including in the RLS helper, which is why `set_config` with bind parameters is used rather than `SET LOCAL`.
- File uploads: validate content type against an allowlist, cap size (10 MB default), generate a new server-side filename, never trust the client's filename.

### 9.10 Secrets

- `.env` is git-ignored. `.env.example` is committed with placeholders only.
- `SECRET_KEY` and `ENCRYPTION_KEY` are generated with `secrets.token_urlsafe(64)` / 32 random bytes — never a memorable string, never reused between environments.
- Production secrets live in the hosting platform's secret store, not in a file.
- If a secret is ever committed, rotating it is mandatory — deleting the commit is not sufficient, because the value is in the Git history and possibly in someone's clone.

---

## 10. Complete API contract

**136 routes across 7 modules.** Every route is prefixed with `/api/v1`. Access column key:

| Key | Meaning | Enforced by |
|---|---|---|
| `Public` | No authentication | — |
| `Auth` | Any authenticated user | `get_current_user` |
| `Own` | The record's own employee/user | Service check against `current_user.employee_id` |
| `Mgr` | A manager, for their own reports only | Service check against `employees.reporting_manager_id` |
| `HR` | `hr_admin` | `require_role` |
| `SA` | `super_admin` | `require_role` |
| `Members` | A member of that project | **Service check against `project_members` — a row-level relationship, not a role.** `require_role` cannot express this. |
| `Assignee` | The employee a task is assigned to | **Service check against `tasks.assigned_to`** — same mechanism |

`Members` and `Assignee` are the two access levels that are *not* role-based. They are checked in the service layer against a membership row, and a caller who is not a member gets **404, not 403** (10.1) — the same information-leak rule as cross-tenant access.

### 10.1 Universal request/response conventions

**Pagination — every list endpoint.**

Request: `?page=1&limit=20` (`limit` max 100, default 20).

Response envelope, identical everywhere:

```json
{
  "items": [ ... ],
  "page": 1,
  "limit": 20,
  "total": 137,
  "pages": 7,
  "has_next": true
}
```

**Search, filter, sort — every list endpoint.**

| Parameter | Behaviour |
|---|---|
| `q` | Case-insensitive partial match across that resource's designated searchable columns (defined per endpoint below) |
| `sort` | Column name, `-` prefix for descending: `?sort=-hire_date`. **Only columns on an explicit allowlist per endpoint** — never interpolate a raw client string into `ORDER BY` |
| Resource filters | Explicit typed query parameters, e.g. `?department_id=...&is_active=true&status=pending` |
| `date_from` / `date_to` | On date-bearing resources |

The assignment explicitly requires search, filtering, sorting and pagination. Implement them as one shared helper in `app/core/pagination.py` and reuse it — not as bespoke code in each router.

**Standard status codes.**

| Code | Used when |
|---|---|
| 200 | Successful read or update |
| 201 | Resource created (response body is the created resource) |
| 202 | Accepted — a background job was queued (body contains `job_id`) |
| 204 | Successful delete with no body |
| 400 | Business rule violated |
| 401 | Missing, invalid, or expired token |
| 403 | Authenticated but this role may not do this |
| 404 | Not found — **also returned for another tenant's resource** |
| 409 | Conflict — duplicate, or state transition not allowed |
| 422 | Request body failed schema validation (FastAPI default) |
| 423 | Account locked |
| 429 | Rate limit exceeded |
| 500 | Unhandled — logged with a stack trace and reported to Sentry |

**Idempotency.** `POST /payroll/runs` requires an `Idempotency-Key` header. Any other endpoint that triggers money movement or an external side effect must adopt the same pattern. Section 11.9.

---

### 10.2 Identity & Auth — 18 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 1 | POST | `/auth/login` | Public | `email` + `password` (+ optional `company_code`) → access token in the body, refresh token as an **httpOnly cookie** (9.2). Rate-limited, lockout-aware. **409 `company_required`** when the email matches users at more than one company. |
| 2 | POST | `/auth/refresh` | Public + token | Rotate refresh token → new pair. Reuse of a revoked token revokes the whole family (9.2). |
| 3 | POST | `/auth/logout` | Auth | Revoke the presented refresh token |
| 4 | POST | `/auth/logout-all` | Auth | Revoke every refresh token for this user (all devices) |
| 5 | GET | `/auth/me` | Auth | Current user + linked employee summary + permissions |
| 6 | POST | `/auth/change-password` | Auth | Current + new password; revokes all other sessions |
| 7 | POST | `/auth/forgot-password` | Public | Emails an OTP; **always returns 200** (9.3) |
| 8 | POST | `/auth/reset-password` | Public | OTP + new password |
| 9 | GET | `/auth/check-username/{username}` | Public | Availability check; heavily rate-limited |
| 10 | GET | `/auth/activate/{token}` | Public | Preview an invitation before accepting (name, company, expiry) |
| 11 | POST | `/auth/activate` | Public | Token + username + password → activates the employee's user account |
| 12 | POST | `/companies/register` | Public | Company self-registration → status `pending` |
| 13 | GET | `/companies` | SA | List companies. Filters: `status`, `q`, `country`. Sort allowlist: `name`, `created_at`, `status` |
| 14 | GET | `/companies/{id}` | SA | Company detail with counts |
| 15 | POST | `/companies/{id}/approve` | SA | Approve → seeds departments + leave types from industry preset, creates the HR admin user, sends credentials. One transaction (6.7). |
| 16 | POST | `/companies/{id}/reject` | SA | Reject with a required reason |
| 17 | GET | `/companies/me` | Auth | The caller's own company profile |
| 18 | PUT | `/companies/me` | HR | Update own company profile |

### 10.3 Core HR — 24 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 19 | GET | `/employees` | HR, Mgr | List. `q` searches `first_name`, `last_name`, `email`, `employee_code`. Filters: `department_id`, `is_active`, `level`, `employment_type`, `reporting_manager_id`. Sort allowlist: `first_name`, `hire_date`, `employee_code`, `created_at`. Managers see only their own reports. |
| 20 | POST | `/employees` | HR | Create employee, generate `employee_code`, issue an activation token, queue the invite email |
| 21 | GET | `/employees/me` | Auth | The caller's own employee record |
| 22 | GET | `/employees/{id}` | Own, Mgr, HR | Full detail incl. department, manager, KYC status |
| 23 | PUT | `/employees/{id}` | Own, HR | Employees may edit only contact fields; department, level, manager and dates are HR-only |
| 24 | DELETE | `/employees/{id}` | HR | **Soft** deactivate employee + linked user. Never a hard delete (6.5). |
| 25 | POST | `/employees/{id}/toggle-active` | HR | Reactivate |
| 26 | POST | `/employees/{id}/resend-invite` | HR | New activation token, re-queue email |
| 27 | POST | `/employees/{id}/resign` | Own, HR | Submit resignation with a proposed last working date |
| 28 | POST | `/employees/{id}/approve-resignation` | HR | Approve; notice period waived or charged |
| 29 | POST | `/employees/{id}/reject-resignation` | HR | Reject with reason |
| 30 | GET | `/employees/{id}/fnf-settlement` | Own, HR | Full-and-final **calculation only** (11.8). Paying it is a separate action: an off-cycle payroll run (route 91 with `run_type: off_cycle`). |
| 31 | GET | `/departments` | Auth | List with live employee counts |
| 32 | POST | `/departments` | HR | Create |
| 33 | GET | `/departments/{id}` | Auth | Detail |
| 34 | PUT | `/departments/{id}` | HR | Update |
| 35 | DELETE | `/departments/{id}` | HR | **409** if any active employee is assigned |
| 36 | POST | `/kyc` | Own, HR | Create or update own KYC; encrypts Aadhaar/PAN/bank (9.6) |
| 37 | GET | `/kyc/{employee_id}` | Own, HR | Masked by default; `?reveal=true` requires HR and writes an audit row |
| 38 | POST | `/kyc/{employee_id}/verify` | HR | Mark Aadhaar/PAN verified |
| 39 | GET | `/work-experience/{employee_id}` | Own, HR | List |
| 40 | POST | `/work-experience` | Own, HR | Add |
| 41 | PUT | `/work-experience/{id}` | Own, HR | Update (blocked once verified) |
| 42 | DELETE | `/work-experience/{id}` | Own, HR | Remove (blocked once verified) |

### 10.4 Time & Leave — 24 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 43 | POST | `/attendance/check-in` | Own | Marks today; **409** if already checked in |
| 44 | POST | `/attendance/check-out` | Own | Computes `hours_worked` and final status (11.5) |
| 45 | GET | `/attendance` | Auth | Employees see own; managers see their team; HR sees all. Filters: `employee_id`, `date_from`, `date_to`, `status`, `department_id` |
| 46 | GET | `/attendance/{id}` | Own, Mgr, HR | Detail |
| 47 | PUT | `/attendance/{id}` | HR | Regularization — correct a record, with the reason written to `audit_logs` |
| 48 | DELETE | `/attendance/{id}` | HR | Remove an erroneous record (audited) |
| 49 | POST | `/attendance/export` | HR | **202** — queues a Celery CSV export, returns `job_id` |
| 50 | GET | `/shifts` | Auth | List |
| 51 | POST | `/shifts` | HR | Create |
| 52 | PUT | `/shifts/{id}` | HR | Update |
| 53 | DELETE | `/shifts/{id}` | HR | Blocked if currently assigned |
| 54 | POST | `/shifts/{id}/assign` | HR | Assign to an employee from a date; rejects overlapping assignments |
| 55 | GET | `/holidays` | Auth | List, filterable by year |
| 56 | POST | `/holidays` | HR | Add |
| 57 | DELETE | `/holidays/{id}` | HR | Remove |
| 58 | GET | `/leave-types` | Auth | Company's configured leave types |
| 59 | POST | `/leave-types` | HR | Create a custom type |
| 60 | PUT | `/leave-types/{id}` | HR | Update allowance/policy (applies to the *next* allocation, never retroactively) |
| 61 | GET | `/leaves` | Auth | Scoped by role. Filters: `employee_id`, `status`, `leave_type_id`, `date_from`, `date_to` |
| 62 | POST | `/leaves` | Own, Mgr, HR | Apply — runs every validation in 11.3. A manager may apply on behalf of a direct report; HR on behalf of anyone. |
| 63 | GET | `/leaves/{id}` | Own, Mgr, HR | Detail |
| 64 | PUT | `/leaves/{id}` | Mgr, HR | Approve or reject. Approval auto-marks attendance `on_leave` for each covered working day. |
| 65 | DELETE | `/leaves/{id}` | Own, HR | Employee cancels their own **pending** leave. HR may additionally cancel an **approved** leave, which reverses the attendance rows and restores the balance (11.3). |
| 66 | GET | `/leaves/balance/{employee_id}` | Own, HR | Per-type balance for a year (11.4) |

### 10.5 Performance — 11 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 67 | GET | `/performance/cycles` | Auth | List |
| 68 | POST | `/performance/cycles` | HR | Create |
| 69 | PUT | `/performance/cycles/{id}` | HR | Activate / close |
| 70 | POST | `/performance/goals` | Own | Set goals for the active cycle |
| 71 | GET | `/performance/goals/{employee_id}` | Own, Mgr, HR | List goals with ratings |
| 72 | PUT | `/performance/goals/{id}` | Own | Update progress (locked once the cycle closes) |
| 73 | POST | `/performance/goals/{goal_id}/self-review` | Own | Submit self rating; requires weightages to sum to 100 |
| 74 | POST | `/performance/goals/{goal_id}/manager-review` | Mgr, HR | Submit manager rating |
| 75 | GET | `/performance/summary/{employee_id}` | Own, Mgr, HR | Weighted final rating |
| 76 | POST | `/performance/summary/{employee_id}` | HR | Finalize; may flag a salary revision |
| 77 | GET | `/performance/report` | HR | Company-wide distribution and completion rates |

### 10.6 Payroll — 22 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 78 | POST | `/payroll/structures` | HR | Create a structure with its components |
| 79 | GET | `/payroll/structures` | HR | List |
| 80 | GET | `/payroll/structures/{id}` | HR | Detail with components |
| 81 | PUT | `/payroll/structures/{id}` | HR | Edit (does not retroactively change issued payslips — 7.6) |
| 82 | DELETE | `/payroll/structures/{id}` | HR | Soft delete; **409** if assigned to an active employee |
| 83 | POST | `/payroll/employees/{employee_id}/assign` | HR | Assign structure + CTC with `effective_from` |
| 84 | GET | `/payroll/employees/{employee_id}/salary` | Own, HR | Current structure, CTC, and the computed monthly breakdown |
| 85 | GET | `/payroll/statutory-config` | HR | Company PF/ESI/PT/LWF/TDS settings |
| 86 | PUT | `/payroll/statutory-config` | HR | Update (audited) |
| 87 | GET | `/payroll/pt-slabs` | HR | Slabs for the company's state |
| 88 | PUT | `/payroll/pt-slabs` | SA | Platform-managed — government-defined |
| 89 | GET | `/payroll/tax-slabs` | HR, SA | Brackets by country / financial year / regime |
| 90 | POST | `/payroll/tax-slabs` | SA | Platform-managed |
| 91 | POST | `/payroll/runs` | HR | **202** — requires `Idempotency-Key`; queues the run (11.9). Body carries `run_type` (`regular` \| `off_cycle`) and, for off-cycle, an explicit `employee_ids` list. |
| 92 | GET | `/payroll/runs` | HR | List runs |
| 93 | GET | `/payroll/runs/{id}` | HR | Run detail with all payslips |
| 94 | POST | `/payroll/runs/{id}/approve` | HR | Approve → payslips become visible to employees |
| 95 | GET | `/payroll/payslips/me` | Auth | Own **approved** payslips only |
| 96 | GET | `/payroll/payslips/{employee_id}` | HR | Any employee's payslips |
| 97 | POST | `/payroll/reimbursements` | Own | Submit a claim with a receipt |
| 98 | GET | `/payroll/reimbursements` | Auth | Scoped by role |
| 99 | PUT | `/payroll/reimbursements/{id}` | HR, Mgr | Approve or reject |

### 10.7 Projects — 21 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 100 | GET | `/projects` | Auth | Members see their projects; HR sees all |
| 101 | POST | `/projects` | HR, Mgr | Create |
| 102 | GET | `/projects/{id}` | Members, HR | Detail with team and progress |
| 103 | PUT | `/projects/{id}` | Mgr, HR | Update |
| 104 | DELETE | `/projects/{id}` | HR | Soft delete |
| 105 | POST | `/projects/{id}/members` | Mgr, HR | Add a member with a role |
| 106 | DELETE | `/projects/{id}/members/{employee_id}` | Mgr, HR | Remove (sets `left_at`) |
| 107 | GET | `/projects/{id}/tasks` | Members | Filters: `status`, `assigned_to`, `priority`, `due_before` |
| 108 | POST | `/projects/{id}/tasks` | Members | Create |
| 109 | GET | `/tasks/{id}` | Members | Detail |
| 110 | PUT | `/tasks/{id}` | Assignee, Mgr | Update status/details; sets `completed_at` on `done` |
| 111 | DELETE | `/tasks/{id}` | Mgr, HR | Soft delete |
| 112 | GET | `/tasks/{id}/comments` | Members | Thread |
| 113 | POST | `/tasks/{id}/comments` | Members | Add comment |
| 114 | POST | `/tasks/{id}/time-entries` | Assignee | Log hours |
| 115 | GET | `/time-entries` | Auth | Own by default; managers see their team. Filters: `project_id`, `date_from`, `date_to`, `status` |
| 116 | PUT | `/time-entries/{id}` | Own, Mgr | Edit own draft; managers approve or reject |
| 117 | GET | `/projects/{id}/milestones` | Members | List |
| 118 | POST | `/projects/{id}/milestones` | Mgr, HR | Create |
| 119 | PUT | `/milestones/{id}` | Mgr, HR | Update status / completion |
| 120 | GET | `/projects/{id}/report` | Mgr, HR | Completion %, overdue tasks, hours by member, budget vs actual |

### 10.8 Platform — 16 routes

| # | Method | Path | Access | Description |
|---|---|---|---|---|
| 121 | GET | `/dashboard` | Auth | Role-shaped stats, Redis-cached 60 s (11.10) |
| 122 | GET | `/announcements` | Auth | Active, non-expired, targeted to the caller |
| 123 | POST | `/announcements` | HR | Create |
| 124 | DELETE | `/announcements/{id}` | HR | Remove |
| 125 | GET | `/notifications` | Auth | Own; `?unread_only=true` |
| 126 | PUT | `/notifications/{id}/read` | Own | Mark read |
| 127 | PUT | `/notifications/read-all` | Own | Mark all read |
| 128 | GET | `/audit-logs` | HR | Filters: `action`, `actor_email`, `entity_type`, `date_from`, `date_to` |
| 129 | POST | `/audit-logs/export` | HR | **202** — Celery CSV export |
| 130 | POST | `/files/upload` | Auth | Multipart upload → `file_object_id`. Validates type and size (9.9) |
| 131 | GET | `/files/{id}/url` | Auth | Time-limited signed URL; **never** a public link |
| 132 | GET | `/documents/{employee_id}` | Own, HR | List an employee's documents |
| 133 | POST | `/documents` | HR | Attach an uploaded file to an employee |
| 134 | GET | `/search` | Auth | Global search across employees, projects, tasks — always tenant-scoped |
| 135 | GET | `/health` | Public | Liveness + database and Redis connectivity |
| 136 | GET | `/jobs/{job_id}` | Auth | Poll a background job: `queued` / `started` / `success` / `failure`, plus result reference |

---

## 11. Business logic specifications

The rules in this section are where bugs are expensive. Each one is specified precisely enough to be implemented and unit-tested without further interpretation.

### 11.1 Money and rounding — read before writing any calculation

**Rule: money is `Decimal`, never `float`.**

```python
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")

def money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
```

- `NUMERIC(14,2)` in PostgreSQL maps to `Decimal` in Python. Never cast to `float` anywhere in the path.
- **Round once, at the end of each component's calculation** — not at every intermediate step, which compounds error.
- Rounding mode is `ROUND_HALF_UP` (0.005 → 0.01) throughout, so hand-checks match the system.
- After computing all components, assert the payslip balances exactly: `sum(earnings) − sum(employee deductions) + reimbursements == net_salary`. If it does not, that is a bug — raise, do not silently adjust. (This is the same invariant as 11.6 step 6; there is only one.)
- `0.1 + 0.2 != 0.3` in binary floating point. On a payroll of 500 employees, float error becomes a real reconciliation problem and a real conversation with a real finance team.

### 11.2 Employee code generation

Format: `{COMPANY_CODE}-{SEQUENCE:04d}` → `ACME-0042`.

The sequence is per company and must be safe under concurrency. Two HR admins creating an employee at the same instant must not both get `0042`.

**Implementation:** rely on the database, not on a read-then-write in Python.

```sql
-- inside the same transaction that inserts the employee
UPDATE companies SET last_employee_seq = last_employee_seq + 1
WHERE id = :company_id
RETURNING last_employee_seq;
```

The `UPDATE ... RETURNING` takes a row lock on the company for the duration of the transaction, so a concurrent request blocks until this one commits and then gets the next number. Do **not** implement it as `count(*) + 1`, and do **not** reach for a per-company PostgreSQL sequence — the application role is granted `USAGE` but not `CREATE` on the schema (8.2), deliberately, so it cannot create one. `count(*) + 1` is a race condition, and the unique constraint `uq_employees_company_id_employee_code` will surface it as a 500 in production, under load, on a Monday morning.

### 11.3 Leave application — every validation, in order

`POST /leaves` runs these checks in this order and returns the **first** failure with a clear message:

1. The employee exists, is active, and belongs to the caller's company.
2. The caller is that employee, or is HR, or is that employee's manager. Otherwise `403`.
3. `end_date >= start_date`. Otherwise `400`.
4. `leave_type_id` exists, belongs to this company, and is active.
5. `start_date >= today`, **unless** the caller is HR (HR may back-date with a reason, which is audited).
6. `max_consecutive_days` on the leave type is not exceeded.
7. **No overlap** with any existing leave for this employee whose status is `pending` or `approved`:
   `existing.start_date <= new.end_date AND existing.end_date >= new.start_date`.
   On overlap, return `409` naming the conflicting dates.
8. Sufficient balance for the year, unless `leave_types.is_paid` is false (unpaid leave is always allowed and becomes LOP in payroll).

**`total_days` calculation:**

```
total_days = count of dates from start_date to end_date inclusive
             MINUS weekends (per the company's configured working week)
             MINUS company holidays that fall in the range and apply to this employee's department
if is_half_day and start_date == end_date: total_days = 0.5
```

Weekends come from `company_settings.weekend_days` (7.2) — never a hardcoded Saturday/Sunday, because some companies work six days. The leave year comes from `company_settings.leave_year_type` and `.leave_year_start_month`.

**On approval:** for every working day covered, upsert an `attendance` row with `status = on_leave` and `source = system`. Use an upsert (`ON CONFLICT (employee_id, date) DO UPDATE`), because the employee may already have marked attendance that day.

**On cancellation of an approved leave:** reverse the attendance rows created by the approval, and restore the balance. Only HR may cancel an approved leave; employees may only cancel while `pending`.

### 11.4 Leave balance

```
available = opening_balance + allocated - used - encashed
```

- `opening_balance` is carried forward at year rollover, capped at `leave_types.carry_forward_limit`.
- `used` is the sum of `total_days` across `approved` leaves in that year for that type.
- Balance is **recomputed and written** on leave approval and on cancellation — inside the same transaction as the status change, so the two can never disagree.
- `GET /leaves/balance/{employee_id}` returns per-type: `allocated`, `used`, `available`, `carry_forward_eligible`.
- Negative balances are permitted only when the leave type is unpaid; the response flags `is_negative` so the UI can warn.

### 11.5 Attendance

| Rule | Detail |
|---|---|
| One record per employee per day | Enforced by `uq_attendance_employee_id_date` at the database level, not only in code |
| Check-in | Sets `check_in`, `status = present`. **409** if a record already exists for today. |
| Check-out | Sets `check_out`, computes `hours_worked`. **400** if there is no check-in, or if `check_out <= check_in`. |
| Half day | `hours_worked < company_settings.half_day_hours_threshold` (7.2, default 4) → `status = half_day` |
| Overnight shifts | If the assigned shift's `end_time < start_time`, the shift crosses midnight; `hours_worked` must be computed across the date boundary, not as a negative number |
| Holiday / weekend | Not stored as rows by default. Computed at read time from the `holidays` table and `company_settings.weekend_days`, so a changed calendar does not require rewriting history. |
| Leave | Written by leave approval with `source = system` |
| Regularization | HR-only correction via `PUT /attendance/{id}`; the previous value and the reason go to `audit_logs` |

### 11.6 The payslip calculation engine — the most important code in the system

**Build this as a pure function first. No routes. No database. No ORM objects.**

```python
# app/modules/payroll/service/payslip_engine.py

@dataclass(frozen=True)
class PayslipInput:
    ctc_annual: Decimal
    components: list[ComponentSpec]      # from the assigned salary structure
    statutory: StatutoryConfigSpec       # rates from statutory_configs — passed in, never imported
    pt_slabs: list[PTSlabSpec]           # from pt_slabs, already filtered to the company's state
    tax_slabs: list[TaxSlabSpec]         # from tax_slabs, for financial_year + regime
    # Period — LWF applies only in certain months, PT slabs and tax slabs are
    # dated, and TDS needs to know how many months of the year remain.
    month: int                           # 1-12
    year: int
    financial_year: str                  # e.g. "2026-2027"
    # Day counts, derived from company_settings.payroll_working_days_basis
    working_days: Decimal
    present_days: Decimal
    paid_leave_days: Decimal
    lop_days: Decimal
    # Year-to-date tax already deducted this financial year — without this the
    # monthly TDS calculation over-deducts catastrophically (11.7).
    tds_paid_ytd: Decimal = Decimal("0")
    reimbursement_amount: Decimal = Decimal("0")

@dataclass(frozen=True)
class PayslipOutput:
    earnings: list[LineItem]
    deductions: list[LineItem]
    employer_contributions: list[LineItem]
    gross_salary: Decimal
    total_deductions: Decimal
    net_salary: Decimal
    employer_cost: Decimal

def calculate_payslip(data: PayslipInput) -> PayslipOutput: ...
```

**Every rate arrives as an argument.** Nothing is imported from settings, read from the database, or written as a literal inside this function. That is what makes it unit-testable against hand-calculated numbers, and what makes rule 7 real.

**Order of calculation — this order matters:**

```
1.  monthly_ctc = ctc_annual / 12

2.  Compute FULL-MONTH earnings from the structure:
      percentage components:  value% of (ctc | basic) as declared
      fixed components:       the declared amount
      balance component:      monthly_ctc − (all other earnings + employer PF)
    → full_gross = sum of full-month earning lines

3.  Apply loss of pay, allocating the rounding residual:
      paid_days = working_days − lop_days
      ratio     = paid_days / working_days
      target    = round(full_gross × ratio)
      For every NON-balance earning line:  line_earned = round(line_full × ratio)
      balance_line_earned = target − sum(those rounded non-balance lines)   ← absorbs the residual
      earned_gross = sum of ALL rounded earning lines  ( == target, by construction )
      If the structure has no `balance` component, add the residual to the largest
      earning line instead. Either way the lines sum to earned_gross exactly.

4.  Compute statutory deductions:
      EPF (employee)  = pf_employee_rate% × pf_wage       if pf_enabled
      EPF (employer)  = pf_employer_rate% × pf_wage       if pf_enabled
          where pf_wage = min(earned_basic, pf_wage_ceiling) if pf_restrict_to_ceiling
                          else earned_basic
      ESI: ELIGIBILITY is tested on FULL-MONTH gross; the RATE applies to earned gross:
      ESI (employee)  = esi_employee_rate% × earned_gross  if esi_enabled AND full_gross <= esi_wage_ceiling
      ESI (employer)  = esi_employer_rate% × earned_gross  under the same condition
      Professional Tax = the pt_slabs row containing FULL-MONTH gross, for the company's state,
                         effective in this month (plus special_month_amount where the state defines one)
      LWF              = the configured amount, only in statutory.lwf_months
      TDS              = (projected_annual_tax − tds_paid_ytd) / months_remaining   (11.7)

5.  total_deductions = sum(employee-side deductions)
    net_salary        = earned_gross − total_deductions + reimbursement_amount
    employer_cost     = earned_gross + sum(employer contributions)

6.  Assert: sum(earning lines) == earned_gross
            earned_gross − sum(deduction lines) + reimbursements == net_salary
    Any mismatch raises. Never round the difference away.
```

**Three details that are wrong in most first implementations:**

**(a) `earned_gross` is *defined* as the sum of the rounded lines.** Computing it independently as `per_day × paid_days` and then rounding each line separately produces mismatches on ordinary inputs — a ₹100.00 gross split as 33.34 / 33.33 / 33.33 at half pay rounds to 16.67 × 3 = ₹50.01, against an independently computed ₹50.00. Step 6's assertion would then fire on a perfectly normal payslip and abort the run. Define the total as the sum, allocate the residual to the `balance` component, and the assertion becomes a real invariant instead of a landmine.

**(b) The `balance` component must not depend on gross.** `balance = monthly_ctc − (other earnings + employer contributions)` is circular if any employer contribution is a percentage of gross, because gross is not known until `balance` is resolved. The rule that removes the circularity: **CTC includes employer PF (a percentage of Basic, which is known) but not employer ESI**, which is treated as a company cost outside CTC. For the same reason, **`percentage_of = 'gross'` is not permitted on a structure that has a `balance` component** — validate and reject that combination when the structure is saved, not when payroll runs.

**(c) ESI eligibility and the PT slab are decided on full-month gross, not earned gross.** Otherwise an employee just above the ESI ceiling drops *into* ESI in any month with unpaid leave and back out the next — their deductions would flip month to month because they took a day off, which is both wrong and impossible to explain to them.

**Critical detail — the ESI contribution period.** ESI eligibility is governed by contribution periods, not by a fresh month-by-month test: an employee whose wages cross the ceiling mid-period generally continues contributing until the period ends. Rule (c) above is the MVP simplification. **Write that limitation as a comment in the code**, and verify the real rule against ESIC before this computes anyone's actual pay.

**Testing requirement, non-negotiable:** before writing the route, hand-calculate the complete expected payslip for **three different salary levels** — one below the ESI ceiling, one above it, one at a PT slab boundary — and write those numbers as unit test assertions. The function must reproduce them exactly. Only then wire it to a route.

### 11.7 TDS — scope and honesty

Full Indian TDS requires: annual income projection, the employee's regime choice, Chapter VI-A declarations (80C, 80D, HRA exemption), verified investment proofs, surcharge and cess, and mid-year recalculation when declarations change.

**MVP scope:** compute TDS from the `tax_slabs` table using the company's default regime and **no** deductions or exemptions:

```
projected_annual_income = full_month_gross × 12          ← FULL-month, never post-LOP
projected_annual_tax    = apply tax_slabs(projected_annual_income) + cess
months_remaining        = months left in the financial year, including this one
monthly_tds             = max(0, (projected_annual_tax − tds_paid_ytd) / months_remaining)
```

**Both corrections in that formula matter, and getting either wrong is a serious bug:**

- **Subtract `tds_paid_ytd`.** Dividing the *full* annual liability by the remaining months every month deducts roughly `T × (1/12 + 1/11 + … + 1/1) ≈ 3.1 × T` across the year — over-deducting an employee's pay by about 210%. This is why `tds_paid_ytd` is an input to the engine.
- **Project from full-month gross, not earned gross.** Projecting from a post-LOP figure means one month of unpaid leave permanently under-projects the year's income, and the shortfall lands on the employee in March.

**This will not match an employee's real tax liability.** The payslip must therefore show TDS labelled as an estimate, and the README must record this as a documented limitation. `employee_tax_declarations` and proof verification are deferred (Section 23) — the full calculation is built when that table is.

Do not present an approximate TDS figure as a final tax computation anywhere in the UI.

### 11.8 Full-and-final settlement

Triggered by `GET /employees/{id}/fnf-settlement` after a resignation is approved.

```
Earnings
  + salary for days worked in the final month (11.6, prorated)
  + leave encashment: available balance on leave types where is_encashable
                      × per-day basic
  + any approved but unpaid reimbursements

Deductions
  − notice period shortfall, only when employees.notice_waived is false:
      employees.notice_recovery_days × per-day gross
      where notice_recovery_days = max(0, notice_period_days − days actually served)
      and is recorded on the employee at resignation approval, not recomputed later
  − standard statutory deductions on the final month's earnings

Net settlement = earnings − deductions
```

Gratuity is **deferred** (Section 23) — it applies only after five years of continuous service and needs its own verified rules. Salary advances and company loans are likewise out of MVP scope; there is no table for them (Section 7), so they are not a line in this calculation.

`notice_waived` and `notice_recovery_days` are written on the employee row when HR approves the resignation (route 28). Freezing the decision at approval time — rather than recomputing it whenever the settlement is viewed — means the number cannot silently change between the conversation with the employee and the payment.

**Route 30 returns a full itemized breakdown and nothing else — it never writes.** Paying the settlement is a separate, deliberate action: an off-cycle payroll run (`POST /payroll/runs` with `run_type: off_cycle` and this employee's id), so the payment is recorded, idempotent and auditable exactly like every other payment. That is why `payroll_runs.run_type` exists and why the one-run-per-month constraint applies only to `regular` runs (7.6).

### 11.9 Idempotency for payroll runs

```
POST /payroll/runs
Idempotency-Key: <client-generated uuid>
```

Server behaviour:

1. Missing header → `400`.
2. `SELECT` `payroll_runs` by `(company_id, idempotency_key)`. If a row exists → return `200` with that run's current status. **Do not create a second run.**
3. Otherwise `INSERT` a `draft` row.
4. **Catch `IntegrityError` on that insert**, re-select by `(company_id, idempotency_key)`, and return `200` with the row the other request created.
5. On a successful insert: commit, then queue the Celery job.

Step 4 is the part that is usually missing. `SELECT ... FOR UPDATE` on a row that does **not** exist locks nothing, so two concurrent requests both pass step 2 and both attempt the insert; one wins and one raises. Without the catch, that loser is an unhandled `IntegrityError` — a 500 on the most safety-critical endpoint in the system, returned to a user who now has no idea whether payroll ran. `INSERT ... ON CONFLICT DO NOTHING RETURNING id` with an empty return treated as the duplicate branch is an equally correct alternative.

**Test it explicitly:** fire the identical request twice and assert that exactly one `payroll_runs` row exists and exactly one set of `payroll_items` exists. Paying a company's staff twice is the single most damaging bug this system can have.

### 11.10 Dashboard

Role-shaped payloads, cached in Redis for 60 seconds under a key that includes the company id and the role.

| Role | Contents |
|---|---|
| `super_admin` | Company counts by status, pending approvals, platform-wide user count |
| `hr_admin` | Headcount, present today, on leave today, pending leave requests, pending reimbursements, recent hires, department distribution, last payroll run summary |
| `manager` | Team headcount, team present today, team leave requests awaiting them, team task load |
| `employee` | Own attendance this month, own leave balances, own pending requests, latest payslip status, assigned open tasks |

Cache invalidation: on attendance mark, leave approval, and employee create/deactivate, delete the company's dashboard keys. A 60-second stale window is acceptable; a stale headcount after an employee was just added is not.

---

## 12. India statutory payroll — MVP scope

**Read Section 0.3 before using anything in this section.** These figures come from the project's earlier research document. They are a structurally correct model of how Indian payroll composes; they are **not** verified against current government notifications, and they must be confirmed against the official source before they compute a real person's pay.

### 12.1 Salary components

| Component | Type | Typical calculation | Statutory |
|---|---|---|---|
| Basic | Earning | 40–50% of CTC | No |
| HRA | Earning | 20–25% of CTC (commonly 40–50% of Basic) | No |
| Dearness Allowance | Earning | 5–10% of CTC | No |
| Conveyance Allowance | Earning | Fixed monthly amount | No |
| Special Allowance | Earning | `balance` — whatever remains of CTC | No |
| EPF (employee) | Deduction | % of Basic, subject to a wage ceiling | Yes |
| EPF (employer) | Employer contribution | % of Basic, subject to the same ceiling | Yes |
| ESI (employee) | Deduction | % of Gross, only when Gross ≤ the wage ceiling | Yes |
| ESI (employer) | Employer contribution | % of Gross, same condition | Yes |
| Professional Tax | Deduction | State slab from `pt_slabs` | Yes |
| LWF | Deduction | State-specific fixed amount | Yes |
| TDS | Deduction | Tax slab projection (11.7 — MVP is an estimate) | Yes |

### 12.2 Rates to verify before use

The figures in the project research document, carried here **unverified**, are:

| Item | Value in the research document | Verify against |
|---|---|---|
| EPF rate | 12% of Basic, employee and employer each | EPFO |
| EPF wage ceiling | ₹15,000 | EPFO |
| EPS share of employer EPF | 8.33% of Basic, capped | EPFO |
| ESI employee rate | 0.75% of Gross | ESIC |
| ESI employer rate | 3.25% of Gross | ESIC |
| ESI wage ceiling | ₹21,000 gross | ESIC |
| Professional Tax | ₹0–200/month, varies by state and slab | The relevant State PT authority |
| LWF | ₹6–25/month typically, varies by state | The relevant State Labour Welfare Board |
| Income tax slabs | Regime-dependent | Income Tax Department, for the current financial year |

**How to handle this correctly in the build:**

1. Seed `statutory_configs`, `pt_slabs` and `tax_slabs` from `app/db/seed/`, with each seed row carrying a `source_note` recording where the figure came from and the date it was checked.
2. Before the payroll milestone's exit gate, verify each figure against its official source and update the seed and the `source_note`.
3. The README records which figures were verified, when, and against what.
4. **No rate ever appears as a literal in Python.** A rate change must be a data update, never a deploy.

### 12.3 What is deferred

Gratuity, Statutory Bonus, Form 16, Form 24Q, and ECR filing are deferred (Section 23). Each is either tenure-dependent, annual, or a filing-format export rather than a calculation — none blocks a correct monthly payslip.

---

## 13. Background jobs

### 13.1 What runs in the background

Anything that can exceed roughly one second, or that touches an external service.

| Job | Trigger | Why background |
|---|---|---|
| `process_payroll_run` | `POST /payroll/runs` | Hundreds of employees × a multi-step calculation |
| `export_attendance_csv` | `POST /attendance/export` | Unbounded row count |
| `export_audit_logs_csv` | `POST /audit-logs/export` | Same |
| `generate_payslip_pdf` | Payroll approval | PDF rendering is slow |
| `send_email` | Invites, approvals, resets | An external API that can be slow or down |
| `allocate_annual_leave` | Scheduled, at year rollover | Bulk write across every employee |
| `expire_activation_tokens` | Scheduled, daily | Housekeeping |

The two scheduled entries need something to schedule them. That is **Celery beat**, a third process alongside the API and the worker:

```bash
celery -A app.workers.celery_app beat -l info
```

Its schedule is declared in `celery_app.py` (`beat_schedule`). **Exactly one beat process may run**, ever — two would fire every scheduled task twice, which for `allocate_annual_leave` means every employee getting a double allocation. On a platform that can scale the worker horizontally, run beat as its own single-instance service, and say so in the deployment configuration (18.3).

### 13.2 Rules for every task

1. **Tasks take IDs, not objects.** Pass `payroll_run_id`, not a `PayrollRun` instance — ORM objects do not serialize and will be stale by the time the worker runs.
2. **Tasks open their own database session and call `bind_tenant_to_session`** (8.4) — not the one-shot `set_tenant_context` — because there is no HTTP request to inherit the context from, and a long task commits repeatedly. Binding installs the `after_begin` listener so the context survives every commit; setting it once would leave every write after the first commit failing `WITH CHECK` with a permission error that looks nothing like its cause.
3. **Tasks are idempotent.** A retried task must not double-write. Check current state first.
4. **Every task updates a status the API can poll** — `GET /jobs/{job_id}` (route 136). A user who clicks "run payroll" must be able to see what happened.
5. **Failures are captured**, not swallowed: write the error to the owning record (`payroll_runs.error_message`), report to Sentry, and set a terminal status. A job that vanishes silently is worse than one that fails loudly.
6. **Configure retries deliberately** — `autoretry_for=(TransientError,), retry_backoff=True, max_retries=3`. Never retry a business-logic failure; only transient infrastructure failures.

### 13.3 Local development

Celery requires a running worker (`celery -A app.workers.celery_app worker -l info`) in a second terminal. To avoid blocking early development, add a setting `CELERY_TASK_ALWAYS_EAGER=true` for local runs, which executes tasks inline. **Turn it off before testing anything about background behaviour** — eager mode hides exactly the bugs background execution introduces.

---

## 14. Frontend specification

The assignment states advanced UI/UX is not required. The bar is: clean, functional, responsive enough to use, and a genuine demonstration of end-to-end API integration. Build for that bar, and do not exceed it until Scope A is complete.

### 14.1 Structure

```
frontend/src/
├── app/
│   ├── router.tsx           # route definitions + role guards
│   ├── providers.tsx        # QueryClientProvider, AuthProvider, ToastProvider
│   ├── auth-context.tsx     # access token in memory, user object, login/logout
│   └── api-client.ts        # axios instance: base URL, auth header, refresh interceptor
├── modules/
│   ├── identity/            # login, register-company, activate
│   ├── hr/                  # employees, departments, kyc, experience
│   ├── time_leave/          # attendance, leaves, holidays, shifts
│   ├── performance/
│   ├── payroll/
│   ├── projects/
│   └── platform/            # dashboard, announcements, notifications, audit, search
└── shared/
    ├── ui/                  # shadcn components
    ├── api/types.gen.ts     # GENERATED — never hand-edited
    ├── components/          # DataTable, PageHeader, ConfirmDialog, EmptyState, ErrorBoundary
    └── hooks/               # usePagination, useDebounce, useRole
```

Frontend module folders mirror backend module folders exactly. Finding the frontend for a backend feature is never a search.

### 14.2 Token handling — the one thing worth getting exactly right

- The **access token lives in a React state variable, in memory only.** Not `localStorage`, not `sessionStorage`. Anything in `localStorage` is readable by any script that gets injected into the page.
- The **refresh token is an httpOnly cookie** set by the backend. JavaScript cannot read it, so a script injection cannot steal it.
- On app load, call `POST /auth/refresh` once. If it succeeds, the user is still logged in and has a fresh access token. If it fails, show the login page. This is what makes a page refresh not log the user out, without ever persisting a token where a script can reach it.
- One Axios response interceptor handles `401`: attempt refresh once, retry the original request, and if refresh also fails, clear state and redirect to `/login`. **Guard against an infinite loop** — never let the refresh call itself trigger the interceptor.

*If httpOnly cookies prove awkward early on, an in-memory refresh token is an acceptable temporary step, but it must be recorded in the README as a known gap and closed before deployment.*

### 14.3 Pages — 28

| # | Page | Route | Access | Key features |
|---|---|---|---|---|
| 1 | Login | `/login` | Public | Email + password, lockout message, company disambiguation when needed |
| 2 | Company registration | `/register-company` | Public | Multi-step: details → industry → contact. Shows "pending approval" on success. |
| 3 | Employee activation | `/activate/:token` | Public | Preview invite, set username + password |
| 4 | Forgot / reset password | `/forgot-password` | Public | OTP request and reset |
| 5 | Super admin dashboard | `/admin` | SA | Platform stats, pending companies, approve/reject |
| 6 | Dashboard | `/dashboard` | Auth | Role-shaped — the API returns the right payload (11.10) |
| 7 | Employee list | `/employees` | HR, Mgr | Table with search, department filter, sort, pagination |
| 8 | Employee profile | `/employees/:id` | Own, HR | Tabs: details · KYC · experience · documents · salary |
| 9 | Employee create/edit | `/employees/new`, `/employees/:id/edit` | HR | Form with Zod validation mirroring the backend schema |
| 10 | Departments | `/departments` | HR | CRUD with employee counts; delete blocked with a clear reason |
| 11 | Attendance | `/attendance` | Auth | Check in/out, monthly grid, filters, CSV export with job polling |
| 12 | Leave management | `/leaves` | Auth | Apply, list with status, approve/reject for HR and managers |
| 13 | Leave balance | `/leaves/balance` | Auth | Per-type balance cards |
| 14 | Holiday calendar | `/holidays` | Auth | Calendar view; HR can add and remove |
| 15 | Shifts | `/shifts` | HR | Create shifts, assign to employees |
| 16 | Payroll setup | `/payroll/setup` | HR | Structure builder, statutory config, PT slabs |
| 17 | Payroll run | `/payroll/run` | HR | Trigger a run, poll status, review results, approve |
| 18 | My payslip | `/payroll/payslip` | Employee | Full component breakdown, PDF download |
| 19 | Reimbursements | `/payroll/reimbursements` | Auth | Submit with receipt; HR approves |
| 20 | Performance cycles | `/performance` | HR | Create, activate, close |
| 21 | My goals | `/performance/goals` | Employee | Set goals, submit self review |
| 22 | Performance review | `/performance/review/:employeeId` | Mgr, HR | Rate a team member's goals |
| 23 | Projects | `/projects` | Auth | List, create, team management |
| 24 | Task board | `/projects/:id/tasks` | Members | Table view first; Kanban second |
| 25 | Timesheet | `/timesheet` | Auth | Log time, view approval status |
| 26 | Company settings | `/settings/company` | HR | Profile, leave types, working week, statutory config |
| 27 | User settings | `/settings` | Auth | Change password, notification preferences |
| 28 | Audit logs | `/audit` | HR | Filterable trail with CSV export |

Announcements, notifications and global search live in the app shell (a notification bell, a search box in the header) rather than as separate pages.

### 14.4 Shared components — build these once

- **`DataTable`** — one component providing search, sort, pagination and empty/loading/error states, consuming the standard pagination envelope from 10.1. Every list page uses it. Building this once and reusing it eleven times is the single largest time saving in the frontend.
- **`PageHeader`** — title, breadcrumb, primary action button.
- **`ConfirmDialog`** — for every destructive action.
- **`RoleGuard`** — wraps a route; redirects when the role is not permitted.
- **`ErrorBoundary`** — catches render errors and reports to Sentry rather than showing a blank white page.
- **`JobStatus`** — polls `GET /jobs/{job_id}` and renders progress. Used by every 202 endpoint.

### 14.5 Generated API types

```bash
npx openapi-typescript http://localhost:8000/api/v1/openapi.json -o src/shared/api/types.gen.ts
```

Run this whenever the backend contract changes, and commit the output. `types.gen.ts` is never hand-edited. A backend field rename then becomes a TypeScript compile error rather than a runtime `undefined` discovered by a user — that is rule 6 paying for itself.

### 14.6 Form validation

Zod schemas mirror the backend Pydantic schemas. Client validation is for user experience — instant feedback — and the server always validates again. **Client-side validation is never a security control.**

### 14.7 Loading, empty and error states

Every screen that fetches data handles four states: loading, empty, error, and content. A page that renders nothing while loading, or blank when a list is empty, reads as broken. This is cheap to do and is exactly the kind of thing a reviewer notices.

---

## 15. Testing strategy

### 15.1 The three layers

| Layer | Location | Needs a database? | Targets |
|---|---|---|---|
| **Unit** | `tests/unit/` | No | Pure functions: the payslip engine, leave-day counting, balance math, FnF, token helpers, employee-code formatting |
| **Integration** | `tests/integration/` | Yes — a real test database | Routes end to end: auth flow, CRUD, permissions, validation, pagination |
| **Isolation** | `tests/isolation/` | Yes | The cross-tenant suite (8.6). **CI blocks merge on failure.** |

### 15.2 Test database and fixtures

- A separate database, `ems_pro_test`, created and migrated by `conftest.py`.
- **Migrations run as `ems_owner`; the tests themselves connect as `ems_app`.** This is not a detail — `ems_owner` keeps every privilege regardless of the `REVOKE` statements in 8.2, and it bypasses any policy that got `ENABLE` but not `FORCE`. Running tests as the owner would make the isolation suite pass on tables that are not actually protected, and would make WP-11's gate ("prove the application role cannot UPDATE an audit row") impossible to fail. Mirror the production split: `TEST_DATABASE_URL` uses `ems_app`, `TEST_MIGRATION_URL` uses `ems_owner`.
- **Test isolation uses a savepoint, not a plain transaction.** Services commit (6.7), and a service commit would end a simple outer transaction, leaving the rollback with nothing to undo and letting data leak between tests. The working pattern:

```python
@pytest.fixture
def db(connection):
    outer = connection.begin()                 # connection-level transaction
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session                              # service commits release savepoints, not `outer`
    session.close()
    outer.rollback()                           # everything the test did disappears
```

  `join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0) makes the session's commits land on savepoints inside the outer transaction. The `after_begin` listener from 8.4 re-applies the tenant context on each of those, so RLS keeps working through the test's commits.
- `conftest.py` provides: `db`, `client`, and `company_a` / `company_b` fixtures that each yield a company plus ready-made auth headers for `hr_admin`, `manager` and `employee`.
- **Never run tests against the development database.** The test database URL is a separate environment variable, and `conftest.py` refuses to run if it points at the dev database name.

### 15.3 What must be tested — non-negotiable

| Area | Required tests |
|---|---|
| Auth | Register → login → access protected route → refresh → logout. Invalid token, expired token, no token, wrong role. **Refresh-token reuse revokes the family.** |
| Tenant isolation | Every tenant table, every verb, from the other company's token — asserting 404 or an empty list (8.6) |
| Payroll engine | Three hand-calculated salary levels reproduced exactly (11.6). Plus: zero LOP, full-month LOP, gross exactly at the ESI ceiling, gross at a PT slab boundary |
| Idempotency | The same `Idempotency-Key` twice produces exactly one run (11.9) |
| Leave | Overlap rejected, insufficient balance rejected, past date rejected for non-HR, holidays excluded from `total_days`, approval writes attendance rows |
| Attendance | Duplicate check-in rejected, check-out without check-in rejected, overnight shift hours computed correctly |
| Permissions | For each role, at least one route it may use and one it may not |
| Pagination | Page boundaries, `limit` cap enforced, an invalid `sort` column rejected rather than interpolated |
| Soft delete | A deleted record is absent from lists and returns 404 by id, but still exists in the database |

### 15.4 Coverage

Target 80% on `service.py` files — that is where the business rules live. Do not chase coverage on `models.py` or `schemas.py`, where a high number means very little. Coverage is a smoke detector, not a goal.

### 15.5 Rules

- **Tests are written in the same work package as the feature, never afterwards.** A work package with no tests does not pass its gate.
- One behaviour per test. The test name states the behaviour: `test_leave_application_is_rejected_when_dates_overlap_existing_leave`.
- Arrange–Act–Assert, visibly separated.
- Never assert on a hardcoded UUID or timestamp — use fixtures and relative time.
- A failing test is fixed or deleted with a stated reason. A permanently skipped test is worse than no test, because it looks like coverage.

---

## 16. Observability

### 16.1 Structured logging

JSON to stdout (the hosting platform collects stdout). Every log line carries `request_id`, and `company_id` / `user_id` where known, so one request can be followed across services.

Levels: `DEBUG` local only · `INFO` for business events (`employee_created`, `payroll_run_completed`) · `WARNING` for handled anomalies (rate limit hit, login lockout) · `ERROR` for unhandled exceptions and failed jobs.

Re-read 6.8: never log secrets, tokens, or PII.

### 16.2 Request ID middleware

Read `X-Request-ID` from the request or generate one, put it in a context variable available to every log call, and return it in the response header and in every error envelope. When a user reports a problem, the request id is what turns "it broke" into a specific log line.

### 16.3 Sentry

Wired in Phase 0, before features are built on top of it — not at the end.

- Backend and frontend both report, with `environment` set (`development`, `staging`, `production`) and the release tagged with the Git SHA.
- **`send_default_pii=False`.** Scrub `password`, `token`, `authorization`, `aadhaar`, `pan`, `bank_account` from every event.
- Attach `request_id`, `company_id` and `role` as tags so errors can be grouped by tenant.
- **Verify it works by deliberately raising an error and seeing it appear in the dashboard.** An error tracker nobody has ever seen fire is not an error tracker.

### 16.4 Health check

`GET /health` returns `200` only when the application, PostgreSQL and Redis are all reachable, with a per-dependency breakdown and the app version. Hosting platforms use this for restarts, so it must be honest — never a hardcoded `{"status": "ok"}`.

---

## 17. Configuration

### 17.1 Rules

- All configuration comes from environment variables, loaded once by `pydantic-settings` into a single `settings` object.
- **No `os.getenv` anywhere except `config.py`.** One place reads the environment; everything else imports `settings`.
- The application **fails to start** if a required variable is missing. A missing `SECRET_KEY` must be a startup crash, never a silent default — a defaulted secret key in production is a full authentication bypass.
- `.env.example` is committed and lists every variable with a safe placeholder. `.env` is git-ignored.

### 17.2 `.env.example`

```dotenv
# ── Application ─────────────────────────────────────────────
ENVIRONMENT=development              # development | staging | production
DEBUG=true
APP_NAME=EMS Pro
API_V1_PREFIX=/api/v1

# ── Database ────────────────────────────────────────────────
# Runtime role: NOT the table owner, NOT superuser, NOBYPASSRLS (Section 8.2)
DATABASE_URL=postgresql+psycopg://ems_app:CHANGE_ME@localhost:5432/ems_pro
# Migration role: owns the schema, used only by Alembic
ALEMBIC_DATABASE_URL=postgresql+psycopg://ems_owner:CHANGE_ME@localhost:5432/ems_pro
# Tests connect as the APPLICATION role, so RLS and grants are actually exercised (15.2)
TEST_DATABASE_URL=postgresql+psycopg://ems_app:CHANGE_ME@localhost:5432/ems_pro_test
TEST_MIGRATION_URL=postgresql+psycopg://ems_owner:CHANGE_ME@localhost:5432/ems_pro_test
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_ECHO=false

# ── Redis ───────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
CELERY_TASK_ALWAYS_EAGER=false

# ── Security ────────────────────────────────────────────────
# Generate: python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=CHANGE_ME_GENERATE_A_REAL_ONE
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
# Generate: python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
ENCRYPTION_KEY=CHANGE_ME_BASE64_32_BYTES
ENCRYPTION_KEY_VERSION=1
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_MINUTES=15

# ── CORS ────────────────────────────────────────────────────
CORS_ORIGINS=["http://localhost:5173"]

# ── Email ───────────────────────────────────────────────────
EMAIL_BACKEND=console                # console | sendgrid
SENDGRID_API_KEY=
EMAIL_FROM=noreply@example.com
FRONTEND_BASE_URL=http://localhost:5173

# ── File storage ────────────────────────────────────────────
STORAGE_BACKEND=local                # local | s3
S3_BUCKET=
S3_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
MAX_UPLOAD_MB=10

# ── Observability ───────────────────────────────────────────
SENTRY_DSN=
LOG_LEVEL=INFO

# ── Platform defaults for NEW companies ─────────────────────
# These seed a company's `company_settings` row at approval time and are never
# read again afterwards. Per-tenant policy lives in the `company_settings` table
# (7.2), not here — an env var would apply one company's working week to every
# company on the platform, which is engineering rule 7 violated in one line.
DEFAULT_COUNTRY=IN
DEFAULT_CURRENCY=INR
DEFAULT_WORKING_WEEK_DAYS=5
DEFAULT_HALF_DAY_HOURS_THRESHOLD=4
```

### 17.3 Environments

| | Development | Staging | Production |
|---|---|---|---|
| Database | Local Docker Postgres | Managed, separate instance | Managed, separate instance |
| `DEBUG` | true | false | false |
| Email | console | Real, to test addresses | Real |
| Sentry | optional | on | on |
| CORS | localhost | staging frontend URL | production frontend URL |
| Secrets | `.env` file | Platform secret store | Platform secret store |
| Backups | none | daily | daily + one **tested** restore |

**Staging exists so that "it worked on my machine" is never the last check before users see it.** Deploy to staging first, always.

---

## 18. CI/CD, tooling and agent configuration

### 18.1 GitHub Actions

`.github/workflows/ci.yml` runs on every push and pull request:

```
1. Checkout, set up Python 3.12
2. Install dependencies (cached)
3. ruff check .            # lint
4. ruff format --check .   # formatting
5. mypy app/               # advisory — allowed to fail early on, tightened later
6. Start Postgres + Redis service containers
7. alembic upgrade head    # as ems_owner — proves migrations apply from scratch, every time
8. Create the ems_app role and apply grants (app/db/seed/bootstrap_roles.sql)
9. pytest -v --cov=app --cov-report=term-missing   # as ems_app, so RLS is genuinely exercised
10. Frontend: npm ci, tsc --noEmit, npm run build
```

**The isolation suite failing fails the build.** That is rule 9 made real.

Step 7 matters more than it looks: running migrations from an empty database on every push catches the migration that works on your machine (because your database already has the column) but fails on a fresh one.

### 18.2 Pre-commit hooks

`ruff check --fix`, `ruff format`, trailing-whitespace, end-of-file-fixer, and a `detect-secrets` scan. Catching a committed secret at commit time is far cheaper than rotating it afterwards.

### 18.3 Deployment

1. Multi-stage `Dockerfile`: build stage installs dependencies, runtime stage copies only what is needed and runs as a **non-root user**.
2. Migrations run as a release step **before** the new version starts serving — never inside the application's startup path, where two starting instances would race.
3. Three processes, sharing one image and differing only by command:
   - **API** — `uvicorn app.main:app` (scale horizontally as needed)
   - **Worker** — `celery -A app.workers.celery_app worker` (scale horizontally as needed)
   - **Beat** — `celery -A app.workers.celery_app beat` — **exactly one instance, never more** (13.3). Two beat processes fire every scheduled job twice; for `allocate_annual_leave` that means every employee getting a double leave allocation.
4. Roll out to staging → smoke test → production.
5. Production smoke test: register a company, approve it, add an employee, mark attendance, apply for leave, run payroll. If any step fails, roll back.

### 18.4 `.claude/settings.json` — agent guardrails

```json
{
  "permissions": {
    "allow": [
      "Read(**)",
      "Write(app/**)", "Write(tests/**)", "Write(frontend/src/**)",
      "Write(alembic/versions/**)", "Write(docs/**)",
      "Bash(pytest*)", "Bash(ruff*)", "Bash(alembic*)",
      "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)"
    ],
    "deny": [
      "Read(.env)", "Write(.env)",
      "Bash(rm -rf*)",
      "Bash(git push*)",
      "Bash(alembic downgrade*)",
      "Bash(psql*DROP*)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "ruff format app/ tests/ 2>/dev/null; ruff check --fix app/ tests/ 2>/dev/null" }]
      }
    ]
  }
}
```

What each denial buys:

- `Read(.env)` / `Write(.env)` — real secrets never enter the agent's context and can never be overwritten.
- `git push` — every push is a deliberate human action, so nothing reaches the remote unreviewed.
- `alembic downgrade` — a downgrade against a database with real data is how data is lost. Human-only.

The `PostToolUse` hook means every file the agent writes is formatted and lint-fixed immediately, so formatting never appears as noise in a diff.

### 18.5 `.claude/commands/` — reusable commands

**`.claude/commands/new-module.md`**

```markdown
Create a new backend module named $ARGUMENTS, following docs/EMS_PRO_DEV_SPEC.md Section 4.1 exactly.

Create app/modules/$ARGUMENTS/ with: __init__.py, models.py, schemas.py,
repository.py, service.py, router.py.

Rules:
- Tenant tables inherit TenantBase; non-tenant tables inherit TimeStampedBase
- Every tenant table gets an RLS policy in the same migration (Section 8.3)
- Repositories contain queries only; services contain rules only; routers contain HTTP only
- Register the router in app/main.py under /api/v1
- Add the module's tables to tests/isolation/ in the same change
- Follow app/modules/identity/ as the reference implementation

Then generate the Alembic migration and show me the diff before applying it.
```

**`.claude/commands/verify.md`**

```markdown
Run the full verification gate and report results as a checklist:
1. ruff check . && ruff format --check .
2. mypy app/
3. alembic upgrade head against a scratch database
4. pytest -v --cov=app
5. Confirm every new tenant table has an RLS policy AND an isolation test
6. Confirm no secrets, tokens, or PII appear in any log statement added in this change

Report each as PASS or FAIL with the specific failure. Do not fix anything yet — report first.
```

**`.claude/commands/wp.md`**

```markdown
Start work package $ARGUMENTS from docs/EMS_PRO_DEV_SPEC.md Section 19.

Before writing any code:
1. Read the work package's scope and exit gate in full
2. List the files you will create or change
3. State anything ambiguous and how you intend to resolve it

Then implement it, then run /verify, then summarize what changed against the exit gate.
```

---

## 19. Build sequence — work packages

This is the working section. Work in order. **A work package is finished only when its exit gate passes** — not when the code is written.

Each package states: what it delivers, which spec sections govern it, and the gate. The gate is something you *run*, not something you feel.

### How to use this with Claude Code

One work package per session. Start each with:

```
/wp 07
```

End each with:

```
/verify
```

Then commit with a message naming the work package: `feat(hr): WP-07 employee CRUD and invite activation`.

**Do not start the next work package until the current gate passes.** Skipping a gate does not save time; it moves the debugging to a point where three more layers sit on top of the bug.

---

### Milestone 0 — Reconcile and Foundation

#### WP-01 · Reconcile existing code
**Governs:** Section 20 (in full)
**Deliver:** An audit report of the existing repository against this specification, then the fixes it identifies.
**Gate:** The audit report exists at `docs/RECONCILIATION.md`; every item is either fixed or listed with the work package that will fix it; `alembic upgrade head` runs clean on an empty database; the app starts and `/health` returns 200.

#### WP-02 · Foundation
**Governs:** 3, 4, 6, 16, 17 · route 135
**Deliver:** `pyproject.toml` with pinned dependencies and ruff config · `docker-compose.yml` (Postgres 16 + Redis 7) · `app/db/seed/bootstrap_roles.sql` creating `ems_owner` and `ems_app` **with `ALTER DEFAULT PRIVILEGES`** (8.2) · `app/core/config.py` · `app/core/time.py` · `app/db/base.py` (`TimeStampedBase`, `TenantBase`) · `app/db/session.py` · `app/core/exceptions.py` + handlers · `app/core/logging.py` · `app/core/middleware.py` (request-id, security headers) · `app/main.py` with `/health` · Alembic wired to `Base.metadata` · **the `companies` table, created *without* the `approved_by` foreign key** (7.2 migration-ordering note) · `.env.example` · `.gitignore` · CI workflow running lint + a trivial test.
**Gate:** `docker compose up` gives a reachable database and Redis; `/health` reports both dependencies honestly; a deliberately raised `NotFoundError` returns the exact error envelope from 6.6 including a `request_id`; the app refuses to start when `SECRET_KEY` is unset; `alembic upgrade head` succeeds against a completely empty database; **connecting as `ems_app` can read and write the `companies` table** (proving the default-privileges grant works, not just the one-time grant); CI is green.

#### WP-03 · Authentication
**Governs:** 5.3, 7.9, 9.1–9.4, 10.2 routes 1–11
**Deliver:** `users` + `refresh_tokens` models and migration, then a follow-up migration adding `companies.approved_by` with `use_alter=True` (7.2) · `app/core/security.py` (Argon2id via `argon2-cffi`, JWT create/decode with PyJWT, refresh token generate/hash, `DUMMY_HASH`) · `app/core/dependencies.py` (`get_current_user`, `require_role`) · identity module's repository/service/router · **routes 1–11 in full**, including the Redis-backed OTP flow for forgot/reset password (hashed OTP, 10-minute TTL, 5-attempt cap — 7.9) · refresh token as an httpOnly cookie with the attributes in 9.2 · lockout policy · `UserRepository` methods that require `company_id` except the three documented pre-auth lookups (7.2).
**Gate:** Through Swagger — log in and receive an access token in the body and a refresh cookie marked `HttpOnly` (check it in DevTools); call a protected route with a valid token (200), an invalid token (401), an expired token (401), no token (401), and a refresh token used as an access token (401); refresh rotates and the **old refresh token is rejected on reuse and revokes the family**; 5 bad passwords lock the account and the 6th attempt returns **423, not 401**, even with the correct password; a forgot-password request for a non-existent email returns 200 with the same body and timing as a real one; an OTP expires after its TTL and is rejected after 5 wrong attempts; `require_role` admits the right role and rejects the wrong one. Integration tests cover every one of these.

> **Understanding checkpoint.** Before moving on, explain out loud, without looking at the code: what is in an access token, why the refresh token is stored only as a hash, and what happens when someone replays an old refresh token. If any part is fuzzy, re-read 9.2 — everything after this builds on it.

#### WP-04 · Multi-tenancy, RLS and the isolation suite
**Governs:** Section 8 (in full), 15
**Deliver:** `enable_rls()` Alembic helper · `app/db/rls.py` with `set_tenant_context` **and the `after_begin` listener** (8.4) · `get_tenant_db` dependency, plus `get_current_user` binding the context from the JWT before it loads the user · the `company_settings` table, its migration and its RLS policy — the first RLS'd table · application-level `company_id` enforcement on `UserRepository` (7.2) · `tests/conftest.py` with the savepoint fixture (15.2) and `company_a` / `company_b` fixtures · `tests/isolation/` first tests, including the parametrized sweep over every tenant table · rate limiting on `/auth/login` · CORS · security headers.
**Gate:** A manual `psql` session **connected as `ems_app`** proves the policy: set `app.current_company_id` to A, query, set it to B, query, get different rows. The same is then proven through the API by an automated test. **A test asserts that an unset tenant context returns zero rows, not all rows.** A test writes a row, commits, and reads it back within one request — proving the `after_begin` listener works (8.4). Hammering `/auth/login` returns 429. CI fails if the isolation test is broken deliberately — verify this by breaking it once, watching CI go red, then fixing it.

#### WP-05 · Companies and onboarding
**Governs:** 7.2, 10.2 routes 12–18, 6.7
**Deliver:** `industry_presets` seed (12 industries) · public company registration · super-admin list/approve/reject · approval seeds the company's `company_settings` row (the table itself came with WP-04), departments and leave types, and creates the HR admin — all in **one transaction** · company profile read/update.
**Gate:** Two companies register and are approved through real API calls; each has its preset departments, leave types **and a `company_settings` row**; a deliberately failing seed step rolls the whole approval back, leaving the company still `pending`; company A's HR admin gets 404 on company B's profile. **Also gate WP-04's transaction fix here:** inside one request, write a row, commit, then read it back and assert it is still visible (8.4).

---

### Milestone A — Assignment scope

**Everything the Python Developer Assignment requires is delivered by the end of WP-15. Finish this milestone completely — tests, frontend, documentation — before starting Milestone B.**

#### WP-06 · Departments
**Governs:** 7.3, 10.3 routes 31–35
**Deliver:** Model, migration with RLS, full CRUD, employee-count aggregation, delete blocked when employees are assigned, isolation tests.
**Gate:** All five routes work in Swagger; deleting a department with employees returns 409 with the count; the isolation suite covers `departments`.

#### WP-07 · Employees
**Governs:** 7.3, 10.3 routes 19–26 · 11.2
*(Routes 27–30 — resignation and full-and-final — belong to WP-27, not here. The employee frontend pages are WP-13.)*
**Deliver:** `employees` model with RLS · CRUD with search/filter/sort/pagination using the shared helper · concurrency-safe employee-code generation · soft deactivate · invite-token generation, wired to the `/auth/activate` routes already built in WP-03 · manager scoping on list.
**Gate:** List supports `?q=`, `?department_id=`, `?sort=-hire_date`, `?page=2&limit=10` and returns the exact envelope from 10.1; an invalid `sort` column returns 400 rather than being interpolated; a created employee can activate their own account and log in; a deactivated employee cannot log in but still exists in the database; a manager sees only their own reports; isolation tests cover `employees`.

#### WP-08 · KYC and work experience
**Governs:** 9.6, 7.3, 10.3 routes 36–42
**Deliver:** `app/core/encryption.py` built and unit-tested **in isolation first** · `employee_kyc` and `work_experiences` models · masked-by-default responses · `?reveal=true` gated on HR and audited · verification workflow.
**Gate:** A unit test proves encrypt→decrypt round-trips and that a tampered ciphertext raises. Querying the database directly shows ciphertext in `aadhaar_encrypted`, not a readable number. A normal `GET /kyc/{id}` shows `XXXX XXXX 1234`. `?reveal=true` as an employee returns 403; as HR it returns the value **and** writes an `audit_logs` row.

#### WP-09 · Attendance, shifts and background jobs
**Governs:** 11.5, 13, 10.4 routes 43–54 · route 136 · page 15
**Deliver:** `attendance` model with the unique constraint · `shifts` and `employee_shifts` models with RLS · shift CRUD and assignment, rejecting overlapping date ranges · check-in/check-out with hours calculation that handles a shift crossing midnight · role-scoped list with filters · HR regularization (audited) · Celery app, worker **and beat** · a trivial background task proven first · CSV export as a real Celery job returning 202 + `job_id` · `GET /jobs/{job_id}` · frontend page 15 (shifts).
**Gate:** A second check-in on the same day returns 409 (and the database constraint holds even if the check is bypassed); check-out without check-in returns 400; a test proves `hours_worked` is correct for an employee assigned to a shift whose `end_time < start_time` — the result must be positive, not negative; assigning a second overlapping shift period is rejected; the trivial Celery task completes asynchronously while the API stays responsive; the CSV export returns 202 immediately and the file appears when the job finishes.

#### WP-10 · Leave management
**Governs:** 11.3, 11.4, 7.4, 10.4 routes 55–66
**Deliver:** `leave_types`, `leaves`, `leave_balances`, `holidays` models · all eight application validations in order · `total_days` excluding weekends and holidays · approval writing attendance rows via upsert · balance recompute in the same transaction · cancellation reversing both.
**Gate:** Every validation in 11.3 has a test that triggers it; an overlapping application returns 409 naming the conflicting dates; a leave spanning a company holiday counts one day fewer; approving a leave creates `on_leave` attendance rows for exactly the working days covered; cancelling an approved leave removes them and restores the balance.

#### WP-11 · Dashboard, audit and notifications
**Governs:** 11.10, 7.8, 10.8 routes 121, 125–129 · pages 5, 28
**Deliver:** `audit_logs` (append-only, `UPDATE`/`DELETE` revoked at the database level, scoped in the repository rather than by RLS — 7.8) · audit middleware for sensitive actions · role-shaped dashboard with Redis caching and invalidation · basic in-app notifications · frontend pages 5 (super-admin dashboard) and 28 (audit logs).
**Gate:** **Connected as `ems_app`** (not `ems_owner` — the distinction is the whole point, 15.2), a direct `UPDATE audit_logs SET ...` fails with a permission error. A platform-level audit row with a NULL `company_id` inserts successfully. Company B's HR admin sees none of company A's audit rows. Each of the four roles gets its own dashboard shape. Marking attendance invalidates the cached dashboard. Approving leave creates a notification for the employee.

#### WP-12 · Frontend foundation and auth
**Governs:** 14.1, 14.2, 14.5, pages 1–4
**Deliver:** Vite + React + TS + Tailwind + shadcn · router with role guards · auth context with the in-memory access token · Axios instance with the refresh interceptor · generated API types · login, company registration, activation, forgot-password pages · `ErrorBoundary`.
**Gate:** Log in through the UI and reach a protected page; refresh the browser and stay logged in (via the refresh call, with **no token in `localStorage`** — verify in DevTools); let the access token expire and watch the interceptor refresh transparently; a failed refresh redirects to login without an infinite loop.

#### WP-13 · Frontend HR pages
**Governs:** 14.3, 14.4, pages 7–10
**Deliver:** The shared `DataTable` (search, sort, pagination, four states) · employee list · employee profile with the tabs whose APIs exist by now — **details, KYC and work experience only**; the documents tab arrives with WP-26 and the salary tab with WP-16 · create/edit form with Zod · departments CRUD.
**Gate:** Every list page uses the same `DataTable`; server-side search, sort and pagination all work against the real API; loading, empty and error states are all visible; a validation error from the backend is displayed on the correct field.

#### WP-14 · Frontend time, leave and dashboard
**Governs:** pages 6, 11–14, 26, 27
**Deliver:** Dashboard rendering the role-appropriate payload · attendance page with check-in/out, monthly view, filters, CSV export with the `JobStatus` poller · leave apply/list/approve · leave balance · holiday calendar · company settings page 26 (profile, leave types, working week — the `company_settings` fields from 7.2) · user settings page 27 (change password).
**Gate:** A full journey through the UI only: HR creates an employee → the employee activates → logs in → marks attendance → applies for leave → HR approves → the employee sees the updated balance and the attendance row.

#### WP-15 · Assignment completion gate
**Governs:** 21, 22
**Deliver:** `README.md` (setup, run, migrations, deploy, API docs link, **documented assumptions and known limitations**) · `.env.example` verified complete · Postman collection exported to `docs/` · `docs/ERD.md` as a mermaid diagram · test coverage reviewed against 15.3 · a clean, meaningful commit history.
**Gate:** **Clone the repository into a fresh directory and follow your own README, step by step, with nothing from your existing environment reused.** If any step fails or needs knowledge that is not written down, fix the README and repeat. Then walk the full journey in the frontend once more. All tests pass. `docs/RECONCILIATION.md` shows no open items.

> **At this point the assignment is complete and submittable.** Everything after this is EMS Pro's extended scope. If the deadline is close, stop here and polish, rather than starting a module you cannot finish.

---

### Milestone B — Payroll

#### WP-16 · Salary structures
**Governs:** 7.6, 10.6 routes 78–84
**Deliver:** `salary_structures`, `salary_components`, `employee_salaries` · structure CRUD with components · assignment to an employee with CTC and `effective_from` · overlap prevention on salary periods.
**Gate:** A structure can be built with percentage, fixed and `balance` components summing to 100% of CTC; assigning an overlapping salary period is rejected; deleting an assigned structure returns 409.

#### WP-17 · Statutory configuration
**Governs:** Section 12 · 7.6 · 10.6 routes 85–90
**Deliver:** `statutory_configs` per company · `pt_slabs` and `tax_slabs` tables and seeds, each row carrying a `source_note` · read/update routes with super-admin gating on the government-defined tables.
**Gate:** **Every rate in the seed has a `source_note` naming where it came from and the date checked** (Section 0.3). A repository-wide search for hardcoded rates (`0.12`, `12`, `15000`, `21000`) finds none in `app/modules/payroll/service/`. Changing a rate through the API changes the next calculation with no code change.

#### WP-18 · The payslip engine
**Governs:** 11.1, 11.6, 11.7 — **the most important package in the build**
**Deliver:** `calculate_payslip` as a pure function taking every rate as an argument · full unit test suite.
**Gate:** Three hand-calculated payslips — one below the ESI ceiling, one above it, one at a PT slab boundary — are reproduced **exactly**, to the paisa. Zero-LOP and full-LOP cases pass. The internal balance assertion (`earnings − deductions + reimbursements == net`) holds in every test. `grep -rn "float" app/modules/payroll/` returns nothing meaningful. **No route exists yet** — this package is the function and its tests only.

#### WP-19 · Payroll runs
**Governs:** 11.9, 13, 10.6 routes 91–94
**Deliver:** `payroll_runs`, `payroll_items` (append-only) · the run route with `Idempotency-Key` · the Celery job calling WP-18's function · attendance and LOP feeding the calculation · approval workflow.
**Gate:** A run over a multi-employee company produces payslips matching WP-18's hand-calculated figures end to end. **The same `Idempotency-Key` submitted twice produces exactly one run and one set of items** — asserted by a test, not by looking. An employee cannot see a payslip before the run is approved.

#### WP-20 · Payslips and reimbursements
**Governs:** 10.6 routes 95–99
**Deliver:** Payslip view with full breakdown · PDF generation as a Celery job · reimbursement submit/approve with receipt upload · approved reimbursements added to the next run as a non-taxable line.
**Gate:** An employee sees only their own approved payslip; the PDF matches the API breakdown exactly; an approved reimbursement appears on the next payslip and increases net pay by exactly its amount.

#### WP-21 · Payroll frontend
**Governs:** pages 16–19
**Gate:** A structure is built in the UI, assigned to three employees, a run is triggered and polled to completion, approved, and each employee sees their own payslip with the correct breakdown. **Re-verify the three hand-calculated numbers through the UI**, not just the API.

---

### Milestone C — Performance

#### WP-22 · Performance backend
**Governs:** 7.5, 10.5
**Gate:** A cycle can be created and activated; goals with weightages that do not sum to 100 are rejected at self-review; self and manager reviews are each submittable once; the final rating is the correct weighted average; isolation tests cover all four tables.

#### WP-23 · Performance frontend
**Governs:** pages 20–22
**Gate:** A complete cycle runs through the UI: HR creates → employee sets goals and self-reviews → manager rates → HR finalizes → the summary displays the weighted rating.

---

### Milestone D — Projects

#### WP-24 · Projects backend
**Governs:** 7.7, 10.7
**Gate:** A project with members and tasks can be created; only members can see it; time entries are validated (`0 < hours ≤ 24`); the project report's totals match the sum of its time entries; isolation tests cover all six tables.

#### WP-25 · Projects frontend
**Governs:** pages 23–25
**Gate:** Table view first and working, then Kanban drag-and-drop persisting status changes to the API, then the timesheet. If Kanban runs long, the table view alone is a complete deliverable — ship it and return to Kanban.

---

### Milestone E — Platform, hardening and launch

#### WP-26 · Platform services
**Governs:** 7.8, 10.8 routes 122–124, 130–134
**Deliver:** `file_objects` with one upload path · signed URLs · documents · announcements · global search (tenant-scoped) · email notifications via Celery + SendGrid replacing the console backend.
**Gate:** An uploaded file is retrievable only through a time-limited signed URL — a direct storage URL returns denied; an oversized or wrong-type upload is rejected; global search never returns another tenant's rows.

#### WP-27 · Resignation and full-and-final
**Governs:** 11.8, 10.3 routes 27–30
**Deliver:** Resignation submit/approve/reject · `employees.notice_waived` and `notice_recovery_days` written at approval · the FnF calculation route (read-only) · payment through an off-cycle payroll run (`run_type: off_cycle`, route 91).
**Gate:** A resignation flows submit → approve → FnF; the settlement's itemized breakdown is verified against a hand calculation; approving with the notice waived produces no recovery line, and approving it charged produces exactly `notice_recovery_days × per-day gross`; leave encashment uses only `is_encashable` types and the correct balance; **an off-cycle run in a month that already has a regular run succeeds** — proving the `run_type` in the unique constraint (7.6) — and the settlement appears as a normal `payroll_items` row.

#### WP-28 · Hardening
**Governs:** 9, 15, 16, 17.3
**Deliver:** Automated daily backups **plus one practice restore actually performed** · a self-audit (no raw SQL string building, CORS reviewed, no committed secrets, no `dangerouslySetInnerHTML` without cause) · test gaps closed in auth, the payroll engine and isolation · a staging environment · a load test (Locust, 50–100 concurrent users).
**Gate:** A backup has been restored into a scratch database and the data verified — **a backup nobody has restored is a hope, not a backup.** The self-audit is written up in `docs/SECURITY_AUDIT.md`. The load test's slowest queries are identified and either fixed or documented with a reason.

#### WP-29 · Deploy
**Governs:** 18.3
**Gate:** Staging deployed and smoke-tested; production deployed; the production smoke test (register → approve → employee → attendance → leave → payroll) passes against the real URL; Sentry and backups confirmed active **in production**, not only locally; the README's deployment section reproduces the deployment from scratch.

---

## 20. Reconciliation of existing code

The repository already contains a partial build. **WP-01 is this section, and nothing else starts until it is done.** The goal is not to throw the existing work away — most of it is close — but to make it match this specification before more code is stacked on it.

### 20.1 Method

1. Read every existing file under `app/` and `alembic/`.
2. Compare each against the governing spec section.
3. Write `docs/RECONCILIATION.md`: one row per finding — file, what the spec requires, what the code does, severity (blocking / should-fix / later), and the fix.
4. Apply the blocking and should-fix items now. Assign the rest to a work package.
5. Do not begin WP-02 until `docs/RECONCILIATION.md` has no open blocking items.

### 20.2 The checklist

**Structure (Section 4)**
- Does every module have exactly `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`?
- Are there leftover `routers/`, `models/`, `schemas/`, `utils/` folders from the earlier flat layout? They must go.
- Is every route mounted under `/api/v1`? (6.9 — retrofitting this later touches every file.)

**Layering (Section 5.2)**
- Does any router contain business logic or a database query? Move it.
- Does any service call `db.query(...)` directly instead of a repository? Move it.
- Does any repository raise `HTTPException`? Replace with an `AppError` raised by the service.
- Does any response schema expose `hashed_password` or a raw token? Remove immediately.

**Database (Sections 6, 7)**
- Integer primary keys anywhere? Must become UUID (rule 2).
- Timestamps without a time zone? Must become `TIMESTAMPTZ` (6.3).
- `datetime.utcnow()` anywhere? Replace with the `utcnow()` helper.
- Money as `Float` or `Numeric` without a scale? Must be `NUMERIC(14,2)` (11.1).
- Missing `deleted_at` on tables that need soft delete (6.5)?
- Missing indexes on foreign keys and on filtered columns (7.1)?
- Do the existing models match the column names in Section 7 exactly? Rename now, while the tables are empty.

**Multi-tenancy (Section 8)**
- Does every tenant table have `company_id NOT NULL`?
- **Does any tenant table lack an RLS policy?** This is always blocking. The three deliberate exceptions are `users`, `refresh_tokens` and `audit_logs` (7.2, 7.8) — do **not** "fix" those by adding policies; verify instead that their application-level scoping is genuinely in place.
- Does the application connect as a role that is a superuser, owns the tables, or has `BYPASSRLS`? If so, every policy is inert — fix the roles.
- Does any query take `company_id` from a request body, path or header rather than the verified JWT? Always blocking.

**Security (Section 9)**
- Is `python-jose` in use? Replace with `PyJWT` (3.1).
- Is `passlib` in use? Replace with `argon2-cffi`'s `PasswordHasher` directly (3.1, 9.1). Existing Argon2id hashes remain valid — `argon2-cffi` produced them in the first place — so this is a code change, not a password reset.
- Is `jwt.decode` called without an explicit `algorithms=[...]` list?
- Are refresh tokens stored raw rather than hashed? Blocking.
- Is rotation implemented, with reuse detection (`replaced_by_id`)?
- Is `is_active` re-checked on every request, or only at login?
- Do login failures reveal whether the email exists (9.3)?
- Is `SECRET_KEY` defaulted in code rather than required (17.1)? Blocking.
- Is `.env` git-ignored, and has it ever been committed? If it has, rotate every value in it.
- Is CORS `["*"]` with credentials (9.7)?

**Errors and configuration**
- Is there one error envelope, or ad-hoc `{"detail": ...}` shapes?
- Is `os.getenv` called outside `config.py`?
- Any `print()` instead of a logger?

**Migrations**
- Does `alembic upgrade head` succeed against a **completely empty** database? Run it against a scratch database to be sure — this is the check that catches migrations which only work because your local database already has the column.
- Are there tables created outside a migration (a leftover `Base.metadata.create_all` call)? Remove it; Alembic is the only source of truth.

**Tests**
- Does `tests/` exist at all? If not, this is blocking — WP-04's isolation suite has nowhere to live.

### 20.3 Known items from the earlier codebase

The earlier version of this project used a flat `app/routers/` layout with business logic inside route functions, integer primary keys, `app/utils/tenant.py::scoped_query` as the only tenant filter, and `app/utils/auth.py` for authentication. **None of that structure carries forward.** The behaviour it implemented is valuable as a reference for business rules that were already thought through — leave overlap checks, KYC verification, FnF — but every one of those rules is now specified in Section 11 and must be implemented against this document, not copied.

Specifically, do not carry forward:
- `scoped_query` as the isolation mechanism — RLS replaces it as the primary layer (8.1), with typed repository signatures replacing it on the three non-RLS tables
- Integer IDs
- Business logic in route functions
- OTP stored in a database column — Redis with TTL (7.9)
- Any hardcoded statutory rate

---

## 21. Documentation deliverables

| Document | Location | Contents |
|---|---|---|
| **README.md** | Repo root | What the project is · prerequisites · local setup step by step · how to run migrations · how to run tests · how to run the frontend · environment variables · link to `/docs` (Swagger) · **assumptions and design decisions** · **known limitations** · deployment |
| **This specification** | `docs/EMS_PRO_DEV_SPEC.md` | The full design |
| **Reconciliation report** | `docs/RECONCILIATION.md` | WP-01 output, kept current |
| **ERD** | `docs/ERD.md` | Mermaid entity-relationship diagram of all 40 tables |
| **API docs** | Auto-generated | FastAPI Swagger at `/docs`, ReDoc at `/redoc` |
| **Postman collection** | `docs/postman_collection.json` | Exported from the OpenAPI spec, with an environment file |
| **Security audit** | `docs/SECURITY_AUDIT.md` | WP-28 output |
| **CLAUDE.md** | Repo root | Short project context loaded by the agent every session |

### 21.1 The README's assumptions section

The assignment explicitly asks for assumptions to be documented. Write them honestly. At minimum:

- Email is unique **per company**, not globally, and why (7.2)
- Statutory rates are seeded from the project research document and **which ones have been independently verified, when, and against what source** (0.3, 12.2)
- TDS is an estimate in MVP scope; declarations and proofs are deferred (11.7)
- Multi-country payroll is designed but not built (23)
- Gratuity and statutory bonus are deferred, with the reason (23)
- Sub-tasks and task dependencies are deferred (23)
- Notifications are stored in the database and shown on load; real-time push is deferred (23)
- Any place where a simpler approach was deliberately chosen over a more complete one

A limitation you named yourself reads as engineering judgement. The same limitation found by a reviewer reads as an oversight. Write them down.

---

## 22. Assignment compliance matrix

Check this before submitting. Every row must be demonstrable, not merely believed.

| Assignment requirement | Where it is satisfied | Verify by |
|---|---|---|
| Clean, maintainable code | Sections 5, 6 · ruff + mypy in CI | CI green; no lint suppressions without a comment |
| Well-structured architecture | Section 4 (domain modules) · Section 5 (four layers) | Any module opens as five predictable files |
| RESTful API design | Section 10 · plural nouns, correct verbs, correct status codes | Swagger review against 10.1 |
| Relational database design | Section 7 · FKs, constraints, indexes, normalization | `docs/ERD.md`; every FK has an index |
| Authentication and authorization | Section 9 · JWT + refresh rotation · `require_role` | WP-03 gate tests |
| Input validation | Pydantic at the edge (9.9) · Zod on the client (14.6) | 422 responses on malformed bodies |
| Error handling | Section 6.6 · one envelope · global handlers | Every error path returns the same shape with a `request_id` |
| Logging | Section 6.8, 16.1 · structured JSON | Logs show `request_id` and no secrets |
| Testing | Section 15 · unit + integration + isolation | `pytest --cov`; the isolation suite blocks CI |
| API integration with a frontend | Section 14 · 28 pages · generated types | The full WP-14 journey through the UI |
| Clear documentation | Section 21 · README, Swagger, Postman, ERD | **A fresh clone set up by following only the README** |
| CRUD, validation, search, filter, sort, pagination | 10.1 shared helper, applied to every list endpoint | Query-parameter tests on every list route |
| Database migrations | Alembic, from the first migration (7.1) | `alembic upgrade head` on an empty database in CI |
| Appropriate indexing | 7.1 and each table's index list | `EXPLAIN` on the employee list query shows an index scan |
| Password hashing | Argon2id (9.1) | The database column shows an `$argon2id$` hash |
| Environment variables | Section 17 · `.env.example` committed, `.env` ignored | `git log --all -- .env` returns nothing |
| Secure API design | Sections 8, 9 · RLS, rate limiting, CORS, headers | WP-04 and WP-28 gates |
| Unit tests for critical logic | The payslip engine (11.6), leave rules (11.3), auth (9) | Named tests exist for each |
| Meaningful Git history | 6.10 · conventional commits, one package per branch | `git log --oneline` reads as a build narrative |
| Daily progress updates | Section 19 work packages map to reportable units | One update per work package: done · in progress · blockers · next |

### 22.1 Daily progress update template

The assignment requires a daily update to your assigned senior. One work package produces one update. Keep it to four short lines:

```
Date: <date>
Done:        WP-07 — employee CRUD, search/filter/sort/pagination, invite-activation flow
In progress: WP-08 — AES-256 encryption utility, unit tested in isolation
Blockers:    none
Next:        Wire encryption into the KYC routes; masked responses with an audited reveal
```

Bullets, not paragraphs. If there is a blocker, say it on the day it appears, not on the day it becomes a delay.

---

## 23. Deferred scope

These are sequenced, not cut. Each has a reason for waiting, and the design work for most of it is already done.

| Item | Why it waits | What it needs when built |
|---|---|---|
| **Multi-country payroll** (US, UK, Germany, Australia) | India-only proves the engine. Building five countries before one is verified multiplies unverified rates by five. | `countries`, `country_salary_templates`, `tax_configurations`, `exchange_rates` tables (designed in the research document) — and **every rate re-verified against that country's official source at build time**, never copied from any earlier document |
| **Employee tax declarations and proofs** | Requires the payroll engine to be correct first; TDS is an estimate until then (11.7) | `employee_tax_declarations`, `employee_tax_proofs`, regime selection, mid-year TDS recalculation |
| **Gratuity** | Applies only after five years of continuous service | Verified rules; tenure calculation from `hire_date` |
| **Statutory bonus** | Annual, computed at financial year end | Verified Payment of Bonus Act rules |
| **Form 16 / Form 24Q / ECR filing** | Filing formats, not calculations. Build once TDS and EPF are live and verified. | Government-specified export formats |
| **Task sub-tasks and dependencies** | Flat tasks prove the module end to end; hierarchy is a data-model and UI complexity jump | Recursive queries, dependency-cycle prevention, a Gantt view |
| **Real-time push notifications (WebSockets)** | Database-stored notifications shown on load cover the actual need. WebSockets are a separate skill, best learned deliberately. | A WebSocket layer, connection management, reconnection handling |
| **Learning management, employee engagement, org chart, 360° feedback** | Not required by any current user; large surface area | Their own specification |
| **Biometric and geo-fenced attendance** | Hardware and mobile integration | Device integration, location permissions |
| **PgBouncer, aggressive Redis caching, AWS/GCP migration** | Premature at MVP traffic — each adds an operational moving part with no measurable benefit yet | Real usage numbers from WP-28's load test |

**Rule for everything in this table: when it is built, its own rates and rules are verified at that time. Nothing in this document, or in the research document behind it, is a source of current law.**

---

## 24. Decision log

Each entry: the decision, the reasoning, and what would make it worth revisiting.

| Decision | Reasoning | Revisit when |
|---|---|---|
| Synchronous SQLAlchemy, not async | One fewer concept while learning; no event loop, no async test harness, simpler debugging. FastAPI runs sync endpoints in a threadpool, which is adequate well beyond MVP traffic. | The load test (WP-28) shows request queuing under concurrency that profiling attributes to blocking I/O |
| Modular monolith, not microservices | One deployment, one database, one transaction boundary. Microservices trade local complexity for distributed complexity — a bad trade for a solo build. | Independent teams need independent deploy cadence |
| RLS **and** application filtering | Defence in depth. Application filtering is fast and expressive; RLS is the layer that survives a forgotten `WHERE`. | Never — do not remove either |
| UUID v4 rather than v7 | v7's index locality matters at millions of rows. v4 works today with no extra dependency, and the column type is identical so switching later is a one-line change. | Table sizes reach the millions and index bloat is measured, not assumed |
| JSONB payslip snapshots | A payslip is a historical financial record. Structures change; issued payslips must not. | Never |
| Rates in tables, never in code | A statutory change must be a data update, not a deploy. Also makes the engine unit-testable with fixed inputs. | Never |
| Email unique per company, not globally | The same person can work at two companies on this platform. Global uniqueness would block a legitimate case. | A product decision that one email means one person platform-wide |
| Redis for OTPs, not a table | TTL expiry removes an entire class of cleanup bug. | Never |
| `PyJWT` over `python-jose` | Active maintenance and published advisories against the alternative (3.1). Verify current advisories yourself before finalizing any crypto dependency. | Advisory status changes — recheck at each dependency review |
| Access token in memory, refresh in an httpOnly cookie | `localStorage` is readable by injected scripts. httpOnly cookies are not. | Never for the access token; the cookie approach can be revisited only with an equivalently strong alternative |
| 404, not 403, for another tenant's resource | A 403 confirms the record exists, which leaks information across tenants. | Never |
| Assignment scope shipped complete before extended scope | A complete small system evaluates better than an incomplete large one, and gives a real deadline safety margin. | Never — this ordering is the schedule's insurance |
| Frontend kept deliberately plain | The assignment states advanced UI/UX is not required. Effort spent there is effort not spent on correctness. | Scope A is complete and time remains |
| `users`, `refresh_tokens` and `audit_logs` scoped in the application, not by RLS | All three are queried at moments when no tenant context can exist: login before authentication, and platform-level audit events that genuinely have no company. Under an unset context an RLS policy correctly returns zero rows, which would break login outright and make platform audit rows impossible to insert. Each is compensated: repository signatures that require `company_id`, no route that lists users, and explicit isolation tests. | Never for `users`. `audit_logs` could adopt RLS with an `OR company_id IS NULL` clause if the platform-event volume ever justifies it |
| `argon2-cffi` used directly, not through `passlib` | passlib's last release imports the standard-library `crypt` module, removed in Python 3.13 — depending on it would cap the interpreter version for the life of the project, in exchange for a thin wrapper over the library underneath | Never, unless passlib resumes releases |
| Employer ESI excluded from the CTC balance component | `balance = CTC − (other earnings + employer contributions)` is circular when an employer contribution is a percentage of gross, because gross is not known until `balance` resolves. Excluding employer ESI (and forbidding `percentage_of='gross'` alongside a balance component) removes the circularity without an iterative solver. | A customer's CTC definition genuinely includes employer ESI — then solve the closed form and document it |
| ESI eligibility and PT slab decided on full-month gross | Deciding them on post-LOP gross makes an employee's statutory deductions flip on and off depending on whether they took unpaid leave that month — wrong, and impossible to explain to the employee | Never |
| Beat runs as exactly one instance | Two schedulers fire every scheduled job twice; for annual leave allocation that means every employee getting double | Never — if beat needs HA, use a scheduler with leader election, not a second instance |

---

## Appendix A — Quick reference

**Start local development**

```bash
docker compose up -d                                   # Postgres + Redis
source venv/bin/activate
psql -f app/db/seed/bootstrap_roles.sql                # roles + grants (first run only)
alembic upgrade head                                   # schema (runs as ems_owner)
uvicorn app.main:app --reload                          # API      → localhost:8000/docs
celery -A app.workers.celery_app worker -l info        # worker   (second terminal)
celery -A app.workers.celery_app beat   -l info        # scheduler (third terminal, ONE only)
cd frontend && npm run dev                             # frontend → localhost:5173
```

**Verify before every commit**

```bash
ruff check . && ruff format --check .
mypy app/
pytest -v --cov=app
```

**Add a new tenant table — the checklist**

1. Model inherits `TenantBase`
2. `alembic revision --autogenerate -m "add <table>"`
3. Add `enable_rls("<table>")` to the migration **by hand** — autogenerate will not do it
4. Write any new enum type into the migration **by hand** — autogenerate will not do that either (7.1)
5. Add the table to the parametrized isolation test
6. Index every foreign key
7. `alembic upgrade head` against a scratch database **as `ems_owner`**, then `pytest` **as `ems_app`**

**The five questions before any pull request**

1. Is business logic only in `service.py`?
2. Does every new tenant table have an RLS policy **and** an isolation test?
3. Is every money value a `Decimal` with explicit rounding?
4. Are there tests for the failure paths, not only the happy path?
5. Could any log line, error message, or API response leak a secret or another tenant's data?

---

*End of specification. Amend this document before changing the architecture, not after.*
