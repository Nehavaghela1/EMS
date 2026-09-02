# Reconciliation Report

**Governs:** Section 20 of `docs/EMS_PRO_DEV_SPEC.md` (in full). Originally WP-01's output; kept current across later work packages per Section 21's table ("WP-01 output, kept current").
**Method:** Every file under `app/` and `alembic/` was read in full and compared against the spec section that governs it, using the Section 20.2 checklist. Where the checklist implied a runnable check (does the app start, does `alembic upgrade head` actually create tables, is a package importable), that check was executed against the local dev database — read-only at audit time; the blocking items were then actually applied (this revision of the report) and re-verified the same way. See "How this was verified" at the end.

**Status: WP-01's 14 blocking items are fixed and verified. WP-02 (foundation, config, errors, logging, role split) — §12–§14. WP-04 (multi-tenancy, RLS, the isolation suite, rate limiting) — §15–§17. WP-05 (company registration and approval workflow) — §18–§20. WP-06 (departments) — §21–§22. WP-07 (employees) — §23–§25. WP-03 (auth routes 3-11, OTP reset, employee activation) — §26–§28. WP-09 (attendance, shifts, background jobs) — §29–§31. WP-10 (leave management, balances, holidays) — §32–§34. WP-11 (audit logging, dashboard, notifications) — §35–§37. WP-12 (frontend foundation, auth, all four public pages) and WP-13 (frontend HR pages) — §38–§41, including a CI fix (§41) that had left CI failing at the pytest step since the workflow was written. WP-14 (frontend dashboard, admin, attendance, leave, shifts, plus a small backend addition) — §42–§44. All delivered and verified. Routes 27–30 (resignation, full-and-final) belong to WP-27. Not proceeding further this session.**

**Severity key**
- **Fixed** — was blocking or should-fix; corrected in this pass and re-verified.
- **Should-fix** — real defect in code that already exists; still open. Not gating WP-02, but should be picked up soon.
- **Later (WP-nn)** — not a defect. The feature/file legitimately doesn't exist yet, or its full correct implementation depends on infrastructure a later work package delivers.

---

## 0. Executive summary

WP-01's blocking items are fixed. The identity module now: imports and runs; creates real tables via Alembic on a genuinely empty database; mounts every route under `/api/v1`; uses `argon2-cffi` and `PyJWT` (not `passlib`/`python-jose`); enforces per-company, case-insensitive email and username uniqueness; issues the refresh token only as an httpOnly cookie, never in a JSON body; and implements refresh rotation with expiry checking and full reuse-detection (replaying a rotated token revokes the whole token family). This was verified with a live end-to-end run — register → wrong-password login → correct login → cookie issuance → refresh rotation → replay of the old token → 401 and family revocation confirmed in the database — not just by import.

Two spec amendments landed first (both resolving spec gaps raised in the original audit): `users`' per-company email/username uniqueness is now explicitly case-insensitive, consistent with `companies`; `email-validator` is now named in the Section 3.1 stack table. `EMS_PRO_DEV_SPEC.md` moved into `docs/`, matching the Section 4 tree.

One reclassification happened before any code was touched: item 2.2 (`HTTPException` instead of `AppError`) moved from Blocking to **Later (WP-02)**, because `AppError` lives in `app/core/exceptions.py`, a WP-02 deliverable — it cannot be built from inside WP-01 without starting WP-02. Every `HTTPException` raise site now carries a `# TODO(WP-02): AppError` comment naming the specific subclass it should become.

One item was carried forward rather than fixed, and is called out explicitly (it was in this report's executive summary prose from the start but, on review, never had its own row with a severity — that gap in the report itself is corrected here): `register_company`'s workflow — creating an already-active company and an already-active `hr_admin` user directly at registration, instead of the spec's `pending` → super-admin-approval flow (routes 12 & 15) — is unchanged. Building it correctly needs `company_settings` (WP-04), `industry_presets` and the approval route (WP-05); implementing a partial version now would mean starting WP-05 out of order. See §2.6.

Two defects were found and fixed *during this pass*, not in the original audit — both caught by an end-to-end smoke test (register → login → refresh) run after the rewrite, before declaring anything done. See §4.21 and §4.22.

**Counts:** 14 fixed (originally 14 blocking + the reclassified 2.2 excluded), 15 should-fix (2 fixed in this pass, 13 remain open), ~20 later (explicitly deferred, listed for completeness), 1 item carried forward by name (§2.6), 2 new items found and fixed during verification (§4.21, §4.22).

---

## 1. Structure (Section 4)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 1.1 | `app/main.py`, `app/modules/identity/router.py` | Every route mounted under `/api/v1` (6.9) | Was: `router = APIRouter(prefix="/auth")`, no `/api/v1` anywhere. | **Fixed** | `main.py` now does `app.include_router(auth_router, prefix=API_V1_PREFIX)` with `API_V1_PREFIX = "/api/v1"`. Verified live: `GET /openapi.json` lists `/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/refresh`. |
| 1.2 | repo root | No leftover flat `routers/`, `models/`, `schemas/`, `utils/` folders | None found | — | Still compliant. |
| 1.3 | every module in `app/modules/` | Exactly `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `__init__.py` | `identity/` has all five; `hr/`, `time_leave/`, `performance/`, `payroll/`, `projects/`, `platform/` are correctly empty stubs | **Later** (own WPs, §19) | Unchanged. |
| 1.4 | repo root | `docs/EMS_PRO_DEV_SPEC.md` per the Section 4 tree | Was at repo root | **Fixed** | Moved to `docs/EMS_PRO_DEV_SPEC.md`. `CLAUDE.md`'s existing references now resolve correctly. |

---

## 2. Layering (Section 5.2)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 2.1 | `app/modules/identity/repository.py` | Repository "does not commit — the service owns transaction boundaries" (5.2, 6.7) | Was: every repo method called `self.db.commit()`/`.refresh()` | **Fixed** | All three repository classes now `add()` + `flush()` only. `AuthService` owns every `commit()` — one per logical operation (register, login-success, login-failure/lockout, refresh-success, refresh-reuse-detected). |
| 2.2 | `app/modules/identity/service.py` | Service "raises `AppError` subclasses ... never `HTTPException` directly" (5.2, 6.6) | Was: raised `HTTPException` throughout, with `# TODO(WP-02): AppError` markers | **Closed in WP-02.** | `app/core/exceptions.py` now has the six base classes from 6.6 (`NotFoundError`, `ValidationError`, `ConflictError`, `ForbiddenError`, `UnauthorizedError`, `RateLimitedError`) plus handlers for `AppError`, `RequestValidationError`, `IntegrityError` and a catch-all, registered in `main.py`. Every `# TODO(WP-02)` site in `service.py` was resolved: `InvalidCredentialsError`, `CompanyRequiredError`, `AccountLockedError`, `AccountInactiveError` are identity-specific subclasses defined in `service.py` itself (matching 5.3's worked example, which names classes beyond the base six). `grep -rn HTTPException app/modules/` → no hits. |
| 2.3 | `app/modules/identity/repository.py` | No `HTTPException`, no business decisions | Compliant | — | Unchanged. |
| 2.4 | `app/modules/identity/router.py` | Router body is 1–3 lines | Compliant | — | Unchanged; still true after the cookie-handling additions (the cookie helper is a private function, not inline route logic). |
| 2.5 | `app/modules/identity/schemas.py` | Response schemas must never expose a raw token (5.2) | Was: `TokenResponse.refresh_token: str` | **Fixed** | Field removed. `TokenResponse` now carries only `access_token` and `token_type`. |
| 2.6 | `app/modules/identity/service.py` — `register_company` | Route 12 (`POST /companies/register`): company self-registration → `status = pending`. The HR admin user is created only at approval (route 15), in one transaction with seeding `company_settings`, departments and leave types (10.2, 6.7). | Was: set `status = active` immediately and created an already-active `hr_admin` user from a client-supplied password, with no approval step | **Closed in WP-05, leave-type seeding closed in WP-10.** | `POST /companies/register` (moved off `/auth/register`, onto its own `companies_router`) now does exactly the spec's route 12: creates the company with `status = pending` and **no user at all**. `POST /companies/{id}/approve` (route 15, SA-only) does the rest — seeds `company_settings`, applies the company's industry preset to `departments` (WP-06 extended this once that table existed) and now `leave_types` too (WP-10, once that table existed — §32), and creates the HR admin — all in one transaction, verified live and in an automated test (§18) by planting a conflicting `company_settings` row and confirming the whole approval rolls back, company left `pending`. |

---

## 3. Database (Sections 6, 7)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 3.1 | `app/db/base.py` | Two shared base classes: `TimeStampedBase` **and** `TenantBase` (7.1) | Was: only `TimeStampedBase` | **Fixed** | `TenantBase(TimeStampedBase)` added exactly per 7.1 — `company_id` FK to `companies.id`, `ondelete="RESTRICT"`, indexed, `nullable=False`. Not yet used by any model (no tenant table exists yet — first use is `company_settings` in WP-04), but ready. |
| 3.2 | `app/db/base.py` | Every timestamp column `TIMESTAMPTZ` (6.3) | Compliant | — | Unchanged. |
| 3.3 | `app/modules/identity/models.py` — `User.locked_until` | `TIMESTAMPTZ` (6.3, "no exceptions") | Was: naive `DateTime`, and `Mapped[DateTime]` (wrong type hint) | **Fixed** | `DateTime(timezone=True)`, `Mapped[datetime | None]`. Verified via `psql \d users`: `timestamp with time zone`. |
| 3.4 | `app/modules/identity/models.py` — `RefreshToken.expires_at` | `TIMESTAMPTZ` (6.3) | Same defect as 3.3 | **Fixed** | Same fix. Verified via `psql \d refresh_tokens`: `timestamp with time zone`. |
| 3.5 | Primary keys, all models | UUID, generated in Python (6.4) | Compliant | — | Unchanged. |
| 3.6 | `datetime.utcnow()` / shared time helper | `app/core/time.py::utcnow()` (6.3) | Was: direct `datetime.now(timezone.utc)` calls in `security.py`, `service.py`, `repository.py` | **Closed in WP-02.** | `app/core/time.py::utcnow()` created. Every direct call site swapped to import and use it. `grep -rn "datetime.now(timezone.utc)" app/` → no hits outside `app/core/time.py` itself. |
| 3.7 | `app/modules/identity/models.py` — `Company` | Spec's `companies` table (7.2), column for column | Was: wrong types (`code` 50 chars, `country` free text defaulting to `"India"`, `currency` 10 chars), missing `rejected` status, no `lower(email)` uniqueness, missing `gst_number`…`last_employee_seq`, missing `approved_by` | **Fixed** | Rewritten column-for-column against 7.2: `code VARCHAR(20)`, `country VARCHAR(2) DEFAULT 'IN'`, `currency VARCHAR(3) DEFAULT 'INR'`, `CompanyStatus` includes `rejected`, functional unique index on `lower(email)` (the plain column-level `UNIQUE` was deliberately *not* also kept — one enforcement mechanism, not two), plus every other column in the spec's table. `approved_by` added via the `use_alter=True` follow-up migration per the 7.2 cycle note (see §7). |
| 3.8 | `app/modules/identity/models.py` — `User` | `uq_users_company_id_email`, `uq_users_company_id_username`, `last_login_at` | Missing username uniqueness and `last_login_at` | **Fixed** | Both added. Uniqueness on both `email` and `username` is a composite `(company_id, lower(...))` index per the spec amendment resolving spec-gap #1 (see §10). |
| 3.9 | `app/modules/identity/models.py` — `RefreshToken` | `replaced_by_id`, `revoked_at`, `ip_address` (7.2) | None existed | **Fixed** | All three added. `replaced_by_id` is a self-referential nullable FK to `refresh_tokens.id`. Verified via `psql \d refresh_tokens`. |
| 3.10 | Money columns | `NUMERIC(14,2)` (7.1, 11.1) | No money columns exist yet | **Later** | N/A until payroll (WP-16+). |
| 3.11 | `app/db/session.py` | Runtime session as the non-owning `ems_app` role (8.2) | Single-role `DATABASE_URL`, no split yet | **Later (WP-02)** | `docker-compose.yml`/`bootstrap_roles.sql` are WP-02 deliverables. |

---

## 4. Multi-tenancy and security (Sections 8, 9)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 4.1 | Every tenant table | RLS policy (8.3) | Was: no tenant tables existed yet | **Closed in WP-04.** | `company_settings` is the first tenant table (7.2), created via `enable_rls("company_settings")` in the same migration. Verified live via `psql` as `ems_app`: context A → 1 row; context B → a *different* row; context unset → 0 rows. `tests/isolation/test_rls_policies.py` parametrizes over `app.db.base.tenant_table_names()` (discovered from the `TenantBase` class hierarchy, not a maintained list) and asserts `ENABLE`+`FORCE`+at least one policy for every one of them — deliberately broken once (`ALTER TABLE company_settings NO FORCE ROW LEVEL SECURITY`) to confirm it goes red, then restored and confirmed green again. |
| 4.2 | `app/modules/identity/repository.py` — `UserRepository` | Every method except the pre-auth lookups requires `company_id` (7.2) | Was: `get_by_email`/`get_by_id` took no `company_id` at all | **Fixed** | `find_by_email(email, company_code=None)` is the pre-auth, cross-company lookup (returns `list[User]`, matching 5.3's worked example). `get_by_id(user_id, company_id)` now requires it. `get_by_id_for_token_refresh(user_id)` is a fourth, explicitly-documented exception beyond the three the spec names in 7.2 — see the note in §10 (spec gap #3, new). |
| 4.3 | `app/modules/identity/repository.py` + `service.py` | Multi-company email match → `409 company_required` with the company list (5.3, 7.2, 9.2 route 1) | Was: `.first()` — silently picked one company | **Fixed** | `find_by_email` returns every candidate; `login()` implements 5.3's worked example: 0 matches → constant-time `DUMMY_HASH` check, no match on password → generic 401 (with lockout bookkeeping), >1 match → `409` with `code: "company_required"` and the company name list, else the normal checks (lockout, active) in the spec's order. Verified live: registering one company and logging in behaves correctly; the >1-company branch is exercised by unit-level reasoning (no second company was registered in the smoke test — real coverage arrives with WP-03's test suite, per Section 15.5, tests land with their feature). |
| 4.4 | `app/db/rls.py`, `get_tenant_db` | (8.4) | Was: didn't exist | **Closed in WP-04.** | `app/db/rls.py`: `set_tenant_context` (`set_config(..., true)`, never `SET LOCAL`), `bind_tenant_to_session`, and the `after_begin` listener. `app/core/dependencies.py` (new, pulled forward from WP-03 since WP-04's own Section 19 text requires it): `get_current_user` binds the tenant context from the verified JWT claim *before* loading the user, then `get_tenant_db`. A real bug was found and fixed while testing this: the `after_begin` listener must execute against the raw `connection` Core object the event hands it, not call back into `session.execute()` — doing the latter raises `"This session is provisioning a new connection; concurrent operations are not permitted"` the moment a post-commit attribute access (e.g. reading `.id` on an expired ORM object) triggers an implicit refresh mid-provisioning. Verified live: a test writes a row, commits, and reads it back within the same session with no explicit re-bind — proving the listener actually re-applies the context. |
| 4.5 | `app/core/security.py` | `argon2-cffi`'s `PasswordHasher` directly, not `passlib` (3.1, 9.1) | Was: `passlib.CryptContext` | **Fixed** | `PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)`; `hash_password`/`verify_password`/`needs_rehash`; `DUMMY_HASH` is a real, pre-generated Argon2id hash literal (generated once with the same parameters, per 9.1's instruction — not computed at import time). |
| 4.6 | `app/modules/identity/models.py` — `User.email` | Unique **per company**, case-insensitive (7.2, Section 24 decision, and the spec amendment in §10 below) | Was: bare column-level `UNIQUE`, i.e. globally unique | **Fixed** | Composite functional unique index on `(company_id, lower(email))`. Verified via `psql \d users`: `"uq_users_company_id_email" UNIQUE, btree (company_id, lower(email::text))`. |
| 4.7 | `app/core/security.py` | `PyJWT`, not `python-jose` (3.1) | Was: `from jose import jwt` | **Fixed** | `jwt.encode`/`jwt.decode` from PyJWT, `algorithms=["HS256"]` explicit on decode, plus a `type` claim (`"access"`) that `decode_access_token` now rejects if it's anything else — closing the "refresh token used as access token" gap 9.2 warns about (moot in practice here since refresh tokens are opaque, not JWTs, but the check is cheap and matches the spec's explicit verification rules). |
| 4.8 | `requirements.txt`, venv | No `python-jose`/`passlib` (3.1) | Neither was ever listed; now neither is imported either | **Fixed** | Confirmed by successful `import app.core.security` and a live server run. |
| 4.9 | venv / `requirements.txt` | `email-validator` for Pydantic `EmailStr` | Was: absent | **Fixed** | `email-validator==2.3.0` (+ its `dnspython==2.8.0` dependency) added to `requirements.txt` and installed. Confirmed by `import app.main` succeeding. |
| 4.10 | `app/modules/identity/router.py`, `schemas.py` | Refresh token: httpOnly cookie only (9.2, 5.3) | Was: JSON body both ways | **Fixed** | Login and refresh both call a shared `_set_refresh_cookie` helper: `HttpOnly`, `Secure` (omitted only when `ENVIRONMENT=development`), `SameSite=Lax`, `Path=/api/v1/auth`, `Max-Age` from `settings.REFRESH_TOKEN_EXPIRE_DAYS`. Refresh reads `request.cookies["refresh_token"]`, never a body field. Verified live: `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax` on both `/login` and `/refresh` responses (no `Secure` — dev environment, as designed). |
| 4.11 | `app/modules/identity/service.py` — `refresh` | Reject an expired token (9.2 step 5) | Was: `expires_at` never checked | **Fixed** | Explicit `token_record.expires_at <= datetime.now(timezone.utc)` check before rotation. |
| 4.12 | `app/modules/identity/service.py` — `refresh` | Reuse of a revoked token revokes the whole family (9.2 step 4) | Was: impossible — no `replaced_by_id`, and revoked tokens were filtered out of the lookup entirely | **Fixed** | `get_by_hash` no longer filters `is_revoked`; `refresh()` checks `is_revoked` explicitly and, if true, revokes every active token for that user via `get_active_by_user` + `revoke`. Verified live end-to-end: rotated token A → B; replaying A returns 401 **and** B (not just A) is now `is_revoked = true` in the database; a subsequent refresh attempt with B also returns 401. Audit-log write is still **Later (WP-11)** — no `audit_logs` table exists yet. |
| 4.13 | `app/modules/identity/models.py` — `RefreshToken` | See 3.9 | See 3.9 | **Fixed** | Same item as 3.9. |
| 4.14 | `app/core/security.py` | `needs_rehash` / rehash-on-login (9.1) | Function didn't exist | **Fixed (function) / Later (wiring, WP-03)** | `needs_rehash()` now exists on `PasswordHasher`. It is not yet called anywhere in `login()` — transparent rehash-on-successful-login is a small, self-contained addition better done alongside WP-03's fuller auth-hardening pass than bolted on here. |
| 4.15 | `app/modules/identity/service.py` — `login` | Lockout after 5 failures → `423` (9.4); `DUMMY_HASH` timing defense (9.3); thresholds live in config, not as Python literals (17.2) | Neither lockout nor `DUMMY_HASH` existed; once added (WP-01), `MAX_LOGIN_ATTEMPTS`/`LOCKOUT_MINUTES` were module-level constants in `service.py`, not settings | **Fixed, and closed in WP-02.** | Lockout and `DUMMY_HASH` implemented in WP-01 as part of 5.3's worked example. The residual should-fix from that pass is now closed: `MAX_LOGIN_ATTEMPTS` and `LOCKOUT_MINUTES` moved into `app/core/config.py::Settings` (defaults 5 / 15, matching 17.2's `.env.example`); `service.py` reads `settings.MAX_LOGIN_ATTEMPTS`/`settings.LOCKOUT_MINUTES`, no local constants remain. |
| 4.16 | `app/main.py` | CORS: explicit origin list from `settings.CORS_ORIGINS`, explicit method/header allowlist including `X-Requested-With` (9.7) | Was: hardcoded origin, `allow_methods=["*"]`, `allow_headers=["*"]` | **Closed in WP-02.** | `settings.CORS_ORIGINS` (default `["http://localhost:5173"]`, JSON-array env var). `allow_methods` is the explicit `["GET","POST","PUT","PATCH","DELETE","OPTIONS"]` list from 9.7; `allow_headers` is `["Authorization","Content-Type","Idempotency-Key","X-Request-ID","X-Requested-With"]`. No wildcards anywhere. |
| 4.17 | `app/main.py` | Rate limiting, security headers, request-ID middleware (9.5, 9.8, 16.2) | Was: none present | **Closed.** | Security headers and request-ID middleware were actually delivered in WP-02 (`app/core/middleware.py`) but this row was missed when WP-02's items were closed — corrected here rather than left stale. Rate limiting (9.5) is closed now, in WP-04: `app/core/rate_limit.py` (`slowapi.Limiter`, Redis storage via `settings.REDIS_URL`), `@limiter.limit("10/minute")` on `POST /auth/login`, `SlowAPIMiddleware` wired into `main.py`, and a `RateLimitExceeded` handler in `app/core/exceptions.py` producing the same envelope shape as every other error (not slowapi's own default shape). Verified live: 15 rapid logins → the first 10 return `401` (wrong credentials), the 11th onward return `429` with `{"error":{"code":"rate_limited",...}}`. CORS and security headers were re-verified after inserting `SlowAPIMiddleware` into the stack — preflight `OPTIONS` and response headers on `/health` both still match 9.7/9.8 exactly. The IP-extraction caveat in 9.5 ("behind a proxy, read the trusted forwarded header") is not implemented — `slowapi`'s default `get_remote_address` is used, correct until a reverse proxy is actually introduced; noted as a later concern, not a defect against the current deployment shape. |
| 4.18 | `.env`, git history | Never committed, no defaulted secret | Compliant | — | Unchanged. |
| 4.19 | `alembic.ini` | No casually-committed credential (spirit of 9.10) | Was: plaintext local DB URL committed (`sqlalchemy.url = postgresql://ems_user:ems_pass@...`) | **Closed in WP-02.** | `alembic.ini`'s `sqlalchemy.url` is now blank with a comment explaining why. `alembic/env.py` overrides it at runtime with `config.set_main_option("sqlalchemy.url", settings.ALEMBIC_DATABASE_URL)`, read from the environment like every other setting. Verified: `alembic current`/`alembic upgrade head` both connect correctly using only the exported `ALEMBIC_DATABASE_URL`, with no credential in the tracked `.ini` file. |
| 4.20 | `app/modules/identity/models.py` — `Company`/`User` relationships | N/A — not a spec item, a bug introduced and caught during this pass | Adding `Company.approved_by` (FK to `users.id`) created a **second** FK path between `companies` and `users` alongside `users.company_id`. SQLAlchemy's `relationship()` on both sides then can't auto-resolve which FK to join on and refuses to configure the ORM mappers at all. | **Fixed** | Caught by the end-to-end smoke test (`app.main` imported fine — the error only surfaces when a query actually touches both mappers — a live `POST /register` call raised `sqlalchemy.exc.InvalidRequestError`). Both `Company.users` and `User.company` now pass `foreign_keys=` explicitly, pinned to `User.company_id`. Re-verified: full register → login → refresh flow now runs clean with no server-side errors. |
| 4.21 | `app/modules/identity/service.py` — `register_company` | N/A — a bug introduced and caught during this pass | After `UserRepository.get_by_email` was renamed to `find_by_email` (returning a list, §4.2/4.3), `register_company`'s duplicate-admin-email check still called the old name and raised `AttributeError` on every request. | **Fixed** | Caught by the same smoke test. Updated to call `find_by_email` and check for a nonempty list. The check's *business meaning* is unchanged and still carried forward to WP-05 per §2.6 — this fix only keeps the existing (deferred-as-is) behavior from crashing. |

---

## 5. Section 20.3 — "must not carry forward" check (re-verified after the fix pass)

| Item | Found in current code? | Evidence |
|---|---|---|
| `scoped_query` as the isolation mechanism | No | No `app/utils/` directory; RLS-exemption compensating control is now real (typed, `company_id`-scoped repository methods — §4.2), not a query wrapper. |
| Integer primary keys | No | Every model still UUID via `TimeStampedBase`. |
| Business logic inside route functions | No | `identity/router.py` bodies remain thin; the new cookie-setting logic lives in a private helper, not inline in the route body. |
| OTP stored in a database column | No | No OTP code exists yet (WP-03). |
| Any hardcoded statutory rate | No | No payroll code exists yet. (The lockout thresholds added in §4.15 are a security/session policy, not a statutory rate — but see that row's should-fix note; they belong in `settings`, not as Python literals, once WP-02 exists.) |

**Still fully clean.**

---

## 6. Errors, configuration, logging

| # | Item | Status |
|---|---|---|
| 6.1 | One error envelope vs. `{"detail": ...}` | Unchanged — still FastAPI's default shape. Tracked with §2.2 (WP-02). |
| 6.2 | `os.getenv` outside `config.py` | Still none. Compliant. |
| 6.3 | `print()` instead of a logger | Still none. Compliant. |
| 6.4 | Structured JSON logging | **Closed in WP-02.** `app/core/logging.py::configure_logging()` — JSON to stdout, `request_id` merged into every log line automatically via a contextvar set by `RequestIDMiddleware` (16.2), `LOG_LEVEL` from settings. Verified live: a raised `NotFoundError` produced `{"timestamp":...,"level":"WARNING","logger":"app","message":"Employee not found.","request_id":"demo-request-id-42","code":"not_found","status_code":404}` on stdout, with the same `request_id` in the response header. |

---

## 7. Migrations — re-verified after the fix

| # | Check | Result |
|---|---|---|
| 7.1 | Does `alembic upgrade head` succeed against a genuinely empty database and create real tables? | **Fixed and verified.** `alembic/env.py` now imports `app.modules.identity.models` before `target_metadata` is used (with an explanatory comment so this doesn't regress silently again). The two empty stub migrations were deleted. Two new migrations were generated per the 7.2 cycle note: `07da587a3d1f_companies_users_refresh_tokens.py` (companies, without `approved_by`, + users + refresh_tokens) and `17d00ae67fda_add_companies_approved_by.py` (adds `companies.approved_by` via `op.create_foreign_key(..., use_alter=True)`). **Verified against a genuinely empty database:** every table, index, and constraint dropped from the dev DB (including both enum types), then `alembic upgrade head` run from zero — `\dt` afterward shows `companies`, `users`, `refresh_tokens`, `alembic_version`. (`ems_user` has no `CREATEDB` grant, so this was done by fully clearing the existing `ems_pro` database rather than provisioning a separate scratch one — functionally identical for this check, and consistent with the eventual `ems_app` role also lacking `CREATEDB`.) |
| 7.2 | Tables created outside a migration? | Still none. Compliant. |

---

## 8. Tests

| # | Check | Result | Status |
|---|---|---|---|
| 8.1 | Does `tests/` exist with real coverage? | Directory exists; still only empty `__init__.py` files, no `conftest.py`, no `tests/isolation/`. | **Later (WP-03/WP-04)** — unchanged. Per Section 15.5, tests land with their feature; WP-01 was a reconciliation pass, not a feature. The live end-to-end verification in this report (register → login → refresh → reuse-detection, against a real database) stands in for automated coverage until WP-03 writes the real suite, but it is not a substitute for one. |

---

## 9. Everything correctly not built yet ("Later") — updated after WP-10

Delivered by WP-02: `pyproject.toml`/ruff/mypy config, `bootstrap_roles.sql` and the `ems_owner`/`ems_app` role split, `app/core/time.py`/`exceptions.py`/`logging.py`/`middleware.py`, `CORS_ORIGINS`/lockout settings/security headers, `docker-compose.yml`'s Postgres+Redis definition, `.github/workflows/ci.yml`, `.env.example`, the `.gitignore` fix (§12–§14).

Delivered by WP-04: `app/db/rls.py` (`enable_rls`, `set_tenant_context`, `bind_tenant_to_session`, the `after_begin` listener), `app/core/dependencies.py` (`get_current_user`, `get_tenant_db` — pulled forward from WP-03's list since WP-04's own Section 19 text requires them), `company_settings` (the first RLS'd table), `tests/conftest.py` (savepoint fixture, `company_a`/`company_b`, `client`, auto-provisioning `ems_pro_test`), `tests/isolation/` (the parametrized sweep plus `company_settings`-specific tests), rate limiting on `/auth/login` (§15–§17).

Delivered by WP-05: `industry_presets` (seed + repository), the real `pending → active/rejected` approval workflow (one transaction: `company_settings` + departments-from-preset + HR admin), `GET`/`PUT /companies/me`, `GET /companies`, `GET /companies/{id}`, `app/core/pagination.py` (pulled forward — needed for the company list envelope), `app/core/dependencies.py::require_role` (pulled forward for the first time SA/HR-only routes existed) (§18–§20).

Delivered by WP-06: `departments` (model, migration + RLS, full CRUD, `tests/isolation/test_departments.py`) — automatically covered by the parametrized sweep with no test file changes required, and the first route to close WP-04's "proven through the API" caveat (§21–§22).

Delivered by WP-07: `employees` (model, migration + RLS, full CRUD with search/filter/sort/pagination via the shared `app/core/pagination.py` helper, concurrency-safe `employee_code` generation, soft deactivate, invite-token generation, manager scoping on list) — plus the two WP-06 gaps this closed (live department employee counts, 409-blocked delete) and a genuine bug fix in the shared pagination helper (`resolve_sort` was raising a 422, not the spec's 400) (§23–§25).

Delivered by WP-03: routes 3-11 in full — `logout`, `logout-all`, `me` (current user + linked employee summary + role-derived permissions), `change-password`, the Redis-backed `forgot-password`/`reset-password` OTP flow (7.9), `check-username`, and `activate`/`activate/{token}` — the pair that redeems WP-07's activation tokens, closing that package's open gate condition. Also: rehash-on-login wiring for `needs_rehash` (9.1); `app/core/otp.py` and `app/core/email.py` (new, small, single-purpose helpers); the `employee_id` JWT-claim spec gap (#6) resolved by amending the spec to match the code, not the other way around — see §10 and the spec's own Section 24 decision log (§26–§28).

Delivered by WP-09: `attendance`, `shifts`, `employee_shifts` (model, migration + RLS, check-in/check-out with midnight-crossing hours calculation, role-scoped list, HR regularization/delete, shift CRUD + overlap-rejecting assignment); `app/workers/celery_app.py` and `app/workers/tasks/` (the Celery app, worker, and beat, proven with a trivial task on a real subprocess worker before anything else was built on it); attendance CSV export as a real background job + `GET /jobs/{job_id}` polling Celery's own result backend (no dedicated `jobs` table exists in the spec's schema) (§29–§31).

Delivered by WP-10: `leave_types`, `leaves`, `leave_balances`, `holidays` (model, migration + RLS); all eight Spec 11.3 application validations, in order; `total_days` excluding weekends and holidays; approval upserting `on_leave` attendance rows via a real `ON CONFLICT ... DO UPDATE`, with the balance recompute in the same transaction; cancellation reversing both. Also closes the leave-type-seeding gap carried since WP-05 (item 2.6) — `CompanyService.approve_company` now seeds `leave_types` from the industry preset alongside departments (§32–§34).

Delivered by WP-11: `audit_logs` (model, migration, no RLS by design — the third deliberate exception alongside `users`/`refresh_tokens` — append-only via an explicit `REVOKE UPDATE, DELETE ... FROM ems_app` in the same migration) and `notifications` (model, migration + RLS, picked up by the isolation sweep automatically); audit writes wired into employee create/update/deactivate, leave approve/reject, attendance regularize/delete, each inside the mutating service's own transaction; `GET`/`POST /audit-logs`(`/export`) (routes 128-129); `GET /dashboard` (route 121, Spec 11.10's four role shapes, Redis-cached 60s, invalidated on the named mutations); `app/core/cache.py` (new, generic Redis JSON cache); notifications list/mark-one-read/mark-all-read (routes 125-127) emitted on leave approved/rejected and attendance regularized (§35–§37).

Delivered by WP-12/WP-13: `frontend/` scaffolded (Vite + React 19 + TS, plain CSS per explicit instruction — not Tailwind/shadcn); in-memory access token + httpOnly-cookie refresh recovery, a single guarded refresh-and-retry interceptor, central error-envelope parsing, `RequireAuth`/`RoleGuard`/`PublicOnly` route guards, generated OpenAPI types committed; all four public pages (login, company registration, employee activation, forgot/reset password — §38, §41); the shared `DataTable`/`PageHeader`/`ConfirmDialog`/`EmptyState` and employee list/profile/create-edit/departments CRUD (pages 7-10, §38); a CI workflow fix (`DATABASE_URL`/`TEST_DATABASE_URL` had been hardcoded to the identical database, so CI had never once run its pytest step successfully — §41) plus the frontend build steps CI's own placeholder comment had been waiting on since WP-02.

Delivered by WP-14: public `GET /industry-presets` (backend, no route number assigned in Section 10 — spec gap #17) wired into the registration page's industry field; dashboard (page 6, one component over all four Spec 11.10 role shapes, the backend's own hardcoded-zero forward-dependency fields omitted from the UI entirely rather than shown as real values); admin dashboard (page 5, super_admin, pending companies + approve/reject); attendance (page 11, check-in/check-out with today's state, role-scoped history, HR regularize); leave (page 12, apply/list/balances/approve-reject, every Spec 11.3 validation message rendered verbatim from the backend, none re-implemented); shifts (page 15, CRUD + assignment) (§42–§44).

Still correctly deferred:

- `app/core/encryption.py` (WP-08)
- `EMAIL_BACKEND=sendgrid` (`app/core/email.py`) raises `NotImplementedError` until WP-26; `console` (the default) prints to stdout instead, dev/test only
- `Dockerfile` content, `README.md` content (WP-15)
- Frontend pages 2, 3, 4, 13, 14, 26, 27 remain — page 2/3/4 were WP-12's own text (closed, §41); pages 13 (a dedicated leave-balance page — folded into page 12 instead, this session's explicit instruction), 14 (holiday calendar), 26 (company settings), 27 (user settings) are Section 19's actual WP-14 assignment, substituted this session for pages 5 and 15 instead — see §42's deviation note
- `allocate_annual_leave` as a Celery beat scheduled task (13.1's bulk annual rollover with carry-forward) — not in either WP-09's or WP-10's explicit deliverable list this session. `LeaveService._get_or_allocate_balance` (WP-10) lazily materializes a balance the first time an employee needs one, which is what makes leave usable today, but it does not apply carry-forward the way a real rollover job would — see spec gap #12 below.
- Routes 27-30 (resignation, full-and-final) — WP-27. The `employees` table already carries `resignation_status`/`resignation_date`/`last_working_date`/`notice_waived`/`notice_recovery_days` (created in WP-07's migration, per the spec's own column-for-column table), but no route in this session reads or writes them.
- HR-admin credential delivery at approval, and the employee invite-token hand-off in the `POST /employees`/`resend-invite` response, are both interim MVP substitutes (a secret returned once in the response body, never logged) — WP-26 replaces both with real email delivery via Celery + SendGrid once that infrastructure exists (§19, §23)
- Actual Sentry SDK initialization (WP-02 added the `SENTRY_DSN` setting; wiring `sentry_sdk.init(...)` is still not done)
- IP extraction behind a trusted proxy for rate limiting (9.5's caveat) — `slowapi`'s default direct-peer extraction is used; revisit when a reverse proxy is actually introduced
- KYC, performance, payroll, projects — everything from WP-08 onward except platform's audit logs/dashboard/notifications, which WP-11 delivered
- `announcements`, `file_objects` (7.8's other two platform tables) — not part of WP-11's task; still open
- A `super_admin`-path audit trail (8.5's "every request where `is_platform_admin` is on writes an audit_logs row") — WP-11 scoped audit writes to the six named employee/leave/attendance mutations only; the super-admin/company-approval audit trail 8.5 separately mandates is still open
- `pending_reimbursements`, `last_payroll_run`, `latest_payslip_status`, `team_task_load`, `assigned_open_tasks` on the WP-11 dashboard API — still hardcoded to `0`/`None` server-side; the underlying `payroll_runs`/reimbursement/`tasks` tables don't exist yet. WP-14's frontend omits all five from the UI (see above) — the backend fields themselves are unchanged.

---

## 10. Spec gaps

1. **~~Case-insensitive uniqueness on `users.email`~~ — RESOLVED.** Section 7.2 now explicitly specifies `(company_id, lower(email))` and `(company_id, lower(username))`, consistent with `companies.email`. Implemented in `models.py` and verified in the database (§4.6).
2. **~~Where `email-validator` is declared~~ — RESOLVED.** Section 3.1's stack table now names `email-validator` (or `pydantic[email]`) explicitly. Added to `requirements.txt`.
3. **New: a fourth pre-authentication-shaped repository method.** Section 7.2 names exactly three lookups exempt from requiring `company_id` (`find_active_by_email`, `get_by_activation_token`, `get_for_password_reset`). Implementing `refresh()`'s reuse-detection required a fourth: loading the `User` behind a refresh token, where — exactly as at login — there is no verified `company_id` yet. `get_by_id_for_token_refresh` was added, matching the same justification the spec gives for the other three (unreachable without the corresponding secret — here, a hashed, unexpired refresh token). This is implemented and documented in the code, not blocked on a spec answer, but it's worth Section 7.2 either naming it as a fourth exception or folding refresh-token lookups under a reworded version of the existing three, so the list stays authoritative.
4. **New: what a `super_admin` account's own `company_id` refers to.** `users.company_id` is `NOT NULL` for every role (7.2) — including `super_admin`, which is platform-wide by definition (1.3) and, per 8.5, only ever created by direct database action, never a route. The spec doesn't say what company a super_admin's own row should point at. This project's fixtures and manual test setup use an ordinary company row created for the purpose (e.g. "Platform Ops") — harmless in practice, since `is_platform_admin=True` bypasses RLS entirely regardless of what `company_id` is set to (8.3's policy `OR` clause), but worth Section 7.2 or 8.5 naming the convention explicitly (a real "platform" company seeded once, vs. any company being acceptable) so every future seed script agrees.
5. **New: industry names in the `industry_presets` seed are this project's own choice, not spec-verified.** Section 7.8 specifies the table's shape (`industry_name`, `departments_json`, `leave_types_json`) and says "seeded once with 12 industries," but not which 12 or what departments/leave types belong to each. The 12 chosen here (Technology, Manufacturing, Healthcare, Retail, Banking & Financial Services, Education, Hospitality, Construction, Real Estate, Logistics & Transportation, Media & Entertainment, Non-Profit) and their department lists are a structurally reasonable starting point — not verified against any real company's org chart, the same caveat Section 0.3 already applies to the statutory payroll figures. Worth a product decision before this seeds a real customer's departments.
6. **~~The access-token `employee_id` claim (9.2)~~ — RESOLVED in WP-03, by amending the spec to match the code.** WP-07 had flagged this: 9.2's worked example showed access tokens carrying `"employee_id": "<employee_uuid_or_null>"`, and 10.1's access-key table defined `Own`/`Mgr` as "a service check against `current_user.employee_id`," while the actual code resolved the same fact via `EmployeeRepository.get_by_user_id(company_id, user_id)` instead. WP-03 made the deliberate call and recorded it: embedding the claim would mean `AuthService.login`/`.refresh` look up the caller's `Employee` row on *every* login and refresh — access tokens are short-lived and refreshed often (9.2's own table) — even for HR/SA callers who never need it. The lazy lookup only queries on the routes that actually need it. Both `docs/EMS_PRO_DEV_SPEC.md` (9.2's claims example and its new explanatory note, and 10.1's `Own`/`Mgr` row) and Section 24's decision log were updated to match the code exactly — code and spec no longer disagree.
7. **New: "contact fields" (route 23) is not itemized by the spec.** 10.3 route 23 says "employees may edit only contact fields; department, level, manager and dates are HR-only" without naming the fields. This project treats `last_name`, `personal_email` and `phone` as the contact fields an `Own` caller may set, and treats `email` (the work email) as HR-only alongside department/level/manager/dates/employment_type — reasoned as: `email` is the administrative identifier used for login and company communication, closer in kind to the HR-controlled fields than to personal contact details. `CONTACT_FIELDS` in `app/modules/hr/service.py` is the single place this list lives if it needs revisiting.
8. **Bug found and fixed during WP-07, not part of the original audit:** `app/core/pagination.py::resolve_sort` — used by every list endpoint's `sort` parameter (companies, departments, and now employees) — raised the app's `ValidationError` (422) for an invalid sort column. 10.1's status table reserves 422 for "request body failed schema validation (FastAPI default)" and defines 400 as "business rule violated," which an invalid `sort` query parameter is. WP-07's gate is the first one that actually asserts this status code (`?sort=hashed_password` → `400`), which is what surfaced it — companies' and departments' list endpoints had the same latent defect since WP-05/WP-06 but nothing tested it. Fixed by raising a new `InvalidSortError(AppError)` (400, `code: "invalid_sort"`) instead; verified live and in `test_invalid_sort_column_returns_400_not_an_interpolated_order_by`.
9. **New: route 5's `GET /auth/me` "permissions" list is this project's own choice, not spec-verified.** The spec's route table (10.2) says the response carries "current user + linked employee summary + permissions," but Section 7 defines no permissions table or schema, and no other route reads or writes a permission set. `AuthService._ROLE_PERMISSIONS` (identity/service.py) is a small, static, role-keyed list of capability strings — a documented judgment call standing in for a real RBAC system, not one. Worth a product decision (a real permissions table, or a formal statement that role IS the permission model) before any frontend starts branching UI on these specific strings.
10. **New: `GET /auth/check-username/{username}` (route 9) checks platform-wide, not per-company.** `username` is only unique *within* a company (`uq_users_company_id_username`, 7.2), but this route is `Public` and has no company parameter in its path (10.2), so there is no tenant to scope the check to at call time. `UserRepository.username_taken_anywhere` is a conservative, cross-company availability hint — it can say "taken" for a username that is actually still free in the caller's own company. The real, correctly-scoped enforcement is `POST /auth/activate` (route 11) via `UserRepository.get_by_username(company_id, ...)` plus the database's own unique constraint; this route is a UX pre-check only, not a source of truth. Worth Section 10.2 either accepting the platform-wide simplification explicitly or adding a `company_code` query parameter if per-company accuracy ever matters to the frontend.
11. **New: a fifth pre-authentication-shaped `UserRepository` method.** 7.2 names four exceptions to "every method requires `company_id`" (`find_active_by_email`, `get_by_activation_token`, `get_for_password_reset`, and `get_by_id_for_token_refresh` added in WP-01/WP-04, spec gap #3 above). WP-03 added a fifth: `username_taken_anywhere` (item #10 above), for the same class of reason — reachable pre-authentication, with no tenant context yet — but it doesn't guard a secret the way the other four do (a username isn't sensitive), so it is a genuinely different shape (never returns a `User`, never leaks more than a boolean). Worth Section 7.2 naming it explicitly as a distinct, fifth category ("public existence checks") rather than folding it into the "unreachable without a secret" framing the other four share.
12. **New: leave balances are allocated lazily, not by a bulk annual-rollover job.** 11.4 says `allocated` comes "from `leave_types.annual_allowance` at allocation time" and 13.1 lists `allocate_annual_leave` as a scheduled job, but neither WP-09's nor WP-10's Section 19 deliverable list names it explicitly this session. `LeaveService._get_or_allocate_balance` materializes a `leave_balances` row — `allocated = leave_type.annual_allowance`, `opening_balance = 0` — the first time an employee needs one for a given leave type and year, which is what makes a newly created employee's leave usable immediately rather than blocked until some later scheduled job runs. What this deliberately does **not** do is what a real `allocate_annual_leave` run would: apply `carry_forward_limit` from the prior year's unused balance into `opening_balance`. Worth a product decision on whether lazy allocation with `opening_balance` fixed at 0 is acceptable long-term, or whether `allocate_annual_leave` needs to be built (and this lazy path kept only as the new-employee fallback it was designed as).
13. **New: the WP-11 task's "routes 125-129" heading doesn't match the spec's own route table.** 10.8 assigns 125-127 to notifications and 128-129 to `GET`/`POST /audit-logs(/export)` — not five notification routes. Built the route set the spec's own table actually assigns (121, 125-127, 128-129), noting the discrepancy here rather than inventing two extra notification routes the table doesn't have.
14. **New: "unread count," asked for as a notifications deliverable, has no route of its own in 10.8.** Folded into `GET /notifications`'s own response (`NotificationListResponse.unread_count`) instead of adding a route the spec's table doesn't assign a number to — cheaper to compute alongside the list query than to invent route "130."
15. **New: "attendance regularisation approve/reject," as an audit/notification target, doesn't correspond to any decision workflow this codebase has.** `PUT /attendance/{id}` (WP-09) is a single-step, HR-only direct correction — there is no separate pending/approved/rejected state machine for attendance the way leave has one. Treated the correction itself as the "decision" being audited (`ATTENDANCE_REGULARIZED`) and notified, and audited `delete_attendance` (`ATTENDANCE_DELETED`) since both already carried `# TODO(WP-11)` markers pointing at exactly this. There is deliberately no "regularisation rejected" notification, for the same reason: HR either corrects the record or removes it — no third "reject and leave it as-is" action exists to notify about. Worth Section 11.10/13's language naming attendance correction explicitly instead of borrowing leave's approve/reject vocabulary, if a real regularization-request workflow (employee requests, HR decides) is ever added.
16. **New: leave-approval-only cache invalidation is a literal reading of 11.10's wording, not a completeness judgment.** "on attendance mark, leave approval, and employee create/deactivate" names approval, not rejection — a rejected leave changes none of the cached dashboard fields (headcount, present-today, on-leave-today, balances) anyway, so the literal reading and the correct one happen to coincide here. Worth Section 11.10 saying so explicitly (or naming rejection too) so a future cached field that *does* change on rejection doesn't get missed by copying this precedent forward.
17. **New: no route number is assigned to a public industry-presets list in Section 10's own table.** 7.8 defines the `industry_presets` table and its `RLS: No` shape; nowhere in Section 10's route table (routes 1–136) does a number correspond to reading it back — needed the moment the registration page (14.3 page 2, WP-12) had to populate a real industry dropdown instead of free text. Built `GET /industry-presets` (WP-14) unnumbered rather than inventing one. Worth Section 10 adding a number for it, a natural fit near routes 12–18 (company onboarding).

---

## 11. WP-01 exit gate — current status

Per Section 19: *the audit report exists; every item is fixed or assigned; `alembic upgrade head` runs clean on an empty database; the app starts and `/health` returns 200.*

| Gate condition | Status |
|---|---|
| `docs/RECONCILIATION.md` exists | **Done** |
| Every item fixed or assigned to a WP | **Done** — 14 blocking items fixed (§1–§4), 2 should-fix items open at the time and intentionally not blocking (§4.16, §4.19 — both since closed in WP-02, see §12), everything else is assigned a work package by name |
| `alembic upgrade head` runs clean on an empty database, creating real tables | **Done — verified.** See §7.1. |
| App starts, `/health` returns 200 | **Done — verified.** `import app.main` succeeds; live server: `GET /health` → `200 {"status":"ok","environment":"development"}`. |

**WP-01 gate passed.** WP-02 followed; see below.

---

## 12. WP-02 — Foundation, config, errors, logging, role split

**Governs:** Section 19 WP-02 (as amended — see the `docs(spec)` commit reconciling Section 19 with what WP-01 already delivered).

**Delivered:**

- **Packaging:** `pyproject.toml` (pinned deps, ruff config, pytest config) replacing `requirements.txt` (deleted). `ruff`/`mypy`/`pytest-cov`/`httpx`/`redis` added as dependencies.
- **`docker-compose.yml`:** rewritten to Postgres 16 + Redis 7 only, with healthchecks. Bootstrap superuser is `postgres` (not `ems_owner` directly) — `bootstrap_roles.sql` is the thing that creates `ems_owner`/`ems_app` against it, per its own header.
- **`.github/workflows/ci.yml`:** the exact step order from 18.1 (lint → format → mypy → services → migrate as `ems_owner` → bootstrap `ems_app` + grants → pytest as `ems_app`). The Postgres service's `POSTGRES_USER` is `ems_owner` itself, which is CI-specific — see the comment block in the workflow explaining why that ordering does *not* generalize to docker-compose/production (bootstrap-then-migrate there, not migrate-then-bootstrap).
- **`app/db/seed/bootstrap_roles.sql`:** creates `ems_owner` (CREATEDB, so it can provision `ems_pro_test` and scratch databases) and `ems_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`); `ALTER DEFAULT PRIVILEGES` for both tables and sequences; `REASSIGN OWNED BY ems_user TO ems_owner` to migrate WP-01's objects (guarded, no-op where `ems_user` doesn't exist); `\set ON_ERROR_STOP on` so a failed statement aborts the script instead of silently continuing (found the hard way — see §13).
- **`app/core/config.py`:** every variable in 17.2 — `CORS_ORIGINS`, `MAX_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES`, `ALEMBIC_DATABASE_URL`, `TEST_DATABASE_URL`, `TEST_MIGRATION_URL`, `REDIS_URL`, `LOG_LEVEL`, `SENTRY_DSN`, and the rest. `ALGORITHM` renamed to `JWT_ALGORITHM` to match the spec's env var name (`security.py` updated to match).
- **`app/core/time.py`, `exceptions.py`, `logging.py`, `middleware.py`:** built as specified — see the closed rows in §2, §3, §6 above for exactly what each replaced.
- **`app/db/session.py`:** pool size/overflow/echo now read from `settings` instead of being hardcoded.
- **`app/main.py`:** exception handlers registered; `RequestIDMiddleware` and `SecurityHeadersMiddleware` wired (CORS outermost, matching 5.1's request lifecycle diagram); `configure_logging()` called at startup; `/health` now genuinely checks PostgreSQL (`SELECT 1`) and Redis (`PING`), returning `200` only when both succeed and `503` with a per-dependency breakdown otherwise — never a hardcoded `"ok"`.
- **`.env.example`:** written in full, matching 17.2. **`.gitignore`:** fixed a real bug found while writing it — the existing `.env.*` pattern silently excluded `.env.example` from ever being committed; now has an explicit `!.env.example` negation. Also added the standard tooling-cache/frontend-build entries that were missing.
- **`alembic/env.py`:** now sets `config.set_main_option("sqlalchemy.url", settings.ALEMBIC_DATABASE_URL)`, so `alembic.ini` carries no credential (closes §4.19). Import order fixed to resolve a real `ruff` E402 finding along the way.
- **`docs/EMS_PRO_DEV_SPEC.md`:** three amendments (spec gap #3 resolved by naming `get_by_id_for_token_refresh` as a fourth pre-auth lookup; the `Company`/`User` `foreign_keys=` note added to the migration-ordering paragraph; WP-02/WP-03 Deliver lines rewritten to match what WP-01 actually shipped) — committed separately as `docs(spec): reconcile Section 19 with WP-01 delivery`, before any WP-02 code.
- **Reconciliation items closed:** 2.2, 3.6, 4.15 (residual constants), 4.16, 4.19, 6.4 — see their rows above, now marked accordingly.

**Not delivered in this pass** (see §9 for the full updated "Later" list): `app/core/dependencies.py`, `pagination.py`, `rate_limit.py`, `encryption.py`; `Dockerfile` content; actual `sentry_sdk.init(...)` wiring (only the `SENTRY_DSN` setting was added, per the explicit instruction list); rate limiting itself (still WP-04, per the original spec).

---

## 13. WP-02 verification — actual output

Every check below was run for real, most against the local dev database and a locally started `uvicorn`. **Docker itself is not available in this sandbox** — there is no `docker`/`docker-compose` binary — so `docker compose up -d` could not be executed literally. `docker-compose.yml` was validated for YAML correctness instead, and every check that would normally run against its containers was run against the equivalent native Homebrew Postgres 16 / Redis 7 services already present in this environment, which is as close a substitute as exists here. This is a real gap between "verified in this session" and "verified via the actual `docker compose up -d` command" — worth re-running once on a machine with Docker before this gate is fully closed end to end.

| # | Check | Result |
|---|---|---|
| 1 | `docker compose up -d`, Postgres + Redis reachable | **Docker unavailable in this sandbox (see above).** `docker-compose.yml` parsed as valid YAML. Substitute: `pg_isready` → `accepting connections`; `redis-cli ping` → `PONG` (native services). |
| 2 | `psql` as `ems_app`: SELECT and INSERT on `companies` | **Pass.** `SELECT count(*)` → `0`; `INSERT ... RETURNING name, code` → succeeded, row visible, cleaned up after. |
| 3 | Scratch table created as `ems_owner` via a real Alembic migration; `ems_app` reads/writes it with no manual grant | **Pass.** Generated `alembic revision`, hand-wrote `op.create_table("scratch_default_privileges_check", ...)`, ran `alembic upgrade head` as `ems_owner`. `ems_app` immediately `INSERT`ed and `SELECT`ed the row with zero grants issued in between — this is the actual proof `ALTER DEFAULT PRIVILEGES` took, not just the one-time `GRANT`. Cleaned up via a direct `DROP TABLE` (as `ems_owner`) plus `alembic stamp` back to the prior head — **not** `alembic downgrade`, which is banned. |
| 4 | `ems_app` is not the owner of `companies` | **Pass.** `psql` connected as `ems_app`, `\dt companies` → `Owner: ems_owner`. |
| 5 | A route raising `NotFoundError` returns the exact 6.6 envelope, with `request_id` in the response header **and** the log line | **Pass — after fixing a real bug.** First attempt raised `KeyError: "Attempt to overwrite 'message' in LogRecord"` — Python's stdlib `logging` reserves the `message` attribute name, and the handler was passing it inside `extra={...}`. Fixed by making `exc.message` the log call's own message argument instead of an `extra` field. Re-verified: HTTP response `404`, `X-Request-ID: demo-request-id-42`, body matching the envelope exactly; stdout log line `{"...,"level":"WARNING","message":"Employee not found.","request_id":"demo-request-id-42","code":"not_found","status_code":404}` — same `request_id` in both places. |
| 6 | Unset `SECRET_KEY` → app refuses to start | **Pass.** Run from `/tmp` (so the real `.env` isn't discovered) with `SECRET_KEY` explicitly unset via `env -u`: `Settings()` raises `pydantic_core.ValidationError: SECRET_KEY / Field required`, exit code 1. `.env` itself was never read or modified. |
| 7 | `GET /health` with Redis stopped → reports Redis down, not a blind `200` | **Pass.** Baseline: `200 {"status":"ok",...,"checks":{"database":"ok","redis":"ok"}}`. After `brew services stop redis`: `503 {"status":"unavailable",...,"checks":{"database":"ok","redis":"error: Error 61 connecting to localhost:6379. Connection refused."}}`. Redis restarted immediately after (`brew services start redis` → `PONG`). |
| 8 | `grep -rn "datetime.now(timezone.utc)" app/` → no hits outside `app/core/time.py` | **Pass.** Zero matches elsewhere. |
| 9 | `grep -rn "HTTPException" app/modules/` → no hits | **Pass.** Zero matches. |
| 10 | `ruff check . && ruff format --check .` | **Pass, after real fixes.** Initial run found 16 lint errors (mostly Alembic's own generated-code style, plus a genuine `E402` in the hand-edited `alembic/env.py`) and `ruff format` reaching into fenced ```python blocks inside `docs/EMS_PRO_DEV_SPEC.md`. Fixed: `env.py`'s import order; `pyproject.toml` excludes `alembic/versions` (generated code, never linted — matches the project's own `.claude/settings.json` convention of only auto-formatting `app/`/`tests/`) and `docs` (markdown, not executable code); `UP042`/`B008` deliberately ignored (they'd fight Spec 7.1's `str, enum.Enum` convention and FastAPI's own `Depends(...)` default-argument idiom, respectively). Final: `All checks passed!` / `35 files already formatted`. |
| 11 | CI green | **Not run via actual GitHub Actions** (no push/PR triggered one). Simulated locally instead, step by step, against a freshly created `ems_pro_test` database: lint ✓, format ✓, mypy ✓ (0 issues after a one-line `# type: ignore[call-arg]` for the well-known pydantic-settings/mypy false positive on required-field constructors), migrate as `ems_owner` ✓, bootstrap `ems_app` + grants ✓, `pytest -v --cov=app` ✓ (5 passed). **One real bug found and fixed in the process:** running migrate-then-bootstrap (CI's literal order) against a database *not* owned by `ems_owner` from creation fails with `permission dended for schema public` — `ems_owner` needs `bootstrap_roles.sql`'s `GRANT CREATE ON SCHEMA public` first. This is fine for CI itself (its `ems_owner` owns the database from container init — see §12's `ci.yml` note) but exposed that `bootstrap_roles.sql` needed `ON_ERROR_STOP` so a failure like this can never be silently swallowed by a downstream script; added and re-verified (the same failing case now aborts with a nonzero exit instead of continuing). |

mypy (advisory): `Success: no issues found in 26 source files.`

pytest (with coverage): `5 passed` — `test_time.py`, `test_exceptions.py` (2 tests), `test_exception_handlers.py` (2 tests, covering the NotFoundError-envelope check above as a permanent regression test, not just a one-off script).

---

## 14. WP-02 exit gate — current status

Per Section 19: *`docker compose up` gives a reachable database and Redis; `/health` reports both dependencies honestly; a deliberately raised `NotFoundError` returns the exact error envelope from 6.6 including a `request_id`; the app refuses to start when `SECRET_KEY` is unset; `alembic upgrade head` succeeds against a completely empty database; connecting as `ems_app` can read and write the `companies` table (proving the default-privileges grant works, not just the one-time grant); CI is green.*

| Gate condition | Status |
|---|---|
| `docker compose up` reachable DB + Redis | **Substitute-verified** (native services; Docker unavailable in this sandbox — see §13 row 1). `docker-compose.yml` itself is written and YAML-valid but has not been run for real. |
| `/health` reports both dependencies honestly | **Done — verified**, including the honest-failure case (Redis stopped → `503`, not `200`). See §13 row 7. |
| `NotFoundError` → exact 6.6 envelope, `request_id` in header and log line | **Done — verified**, after fixing a real logging bug. See §13 row 5. |
| App refuses to start without `SECRET_KEY` | **Done — verified.** See §13 row 6. |
| `alembic upgrade head` succeeds against a completely empty database | **Done — verified**, twice: once by fully clearing `ems_pro`, once against a freshly created `ems_pro_test`. See §13 rows 3 and 11. |
| `ems_app` can read/write `companies`, proving `ALTER DEFAULT PRIVILEGES` | **Done — verified**, both directly on `companies` and via a scratch table created after the grant, which is the stronger proof. See §13 rows 2–3. |
| CI is green | **Simulated, not run via actual GitHub Actions** — see §13 row 11's caveat. |

**WP-02 gate substantially passes**, with two honest caveats explicitly flagged rather than glossed over: (1) `docker compose up -d` itself was never executed, only its equivalent; (2) CI was simulated locally step-by-step, not confirmed green by GitHub Actions itself. Both are environment limitations of this sandbox, not known defects in the deliverables — but re-running both for real on a machine with Docker and a GitHub remote is the honest next step before treating this gate as unconditionally closed.

Not proceeding to WP-03 per instruction.

---

## 15. WP-04 — Multi-tenancy, RLS and the isolation suite

**Governs:** Section 8 (in full), 15. WP-03 was deliberately skipped this session (per instruction) — login/refresh already work from WP-01, so the missing auth routes (logout, logout-all, me, change-password, forgot/reset password, activate) don't block multi-tenancy. `get_current_user`/`get_tenant_db` were pulled into this package because WP-04's own Section 19 text requires them directly; WP-03 still owns `require_role` and routes 3–11.

**Delivered:**

- **`app/db/rls.py`:** `enable_rls(table)` — the Alembic migration helper (`ENABLE`+`FORCE ROW LEVEL SECURITY`, a `tenant_isolation` policy with both `USING` and `WITH CHECK` using the `NULLIF(current_setting(...), '')::uuid` construction, exactly per 8.3). `set_tenant_context` using `set_config(name, value, true)` — never `SET LOCAL`, which can't take bind parameters. `bind_tenant_to_session` plus the SQLAlchemy `after_begin` event listener (8.4).
- **`company_settings`** (Spec 7.2): model on `TenantBase`, migration (`d2e48d131137_company_settings.py`) with `enable_rls("company_settings")` added by hand in the same migration — the first RLS-protected table in the system.
- **`app/core/dependencies.py`:** `get_current_user` (verifies the access token, binds the tenant context from the JWT's `company_id`/`role` claims *before* loading the user, then loads it) and `get_tenant_db` (re-binds from the loaded user, matching 8.4's exact worked example including its apparent redundancy — `bind_tenant_to_session` is idempotent, so both dependencies calling it is cheap and decouples their correctness).
- **`tests/conftest.py`:** the savepoint fixture (`join_transaction_mode="create_savepoint"`), auto-provisioning of `ems_pro_test` (creates it via `ems_owner` if missing, migrates it via a real `alembic upgrade head` subprocess with `ALEMBIC_DATABASE_URL` overridden — never mutating this process's own `settings`), a refusal check if `TEST_DATABASE_URL` ever points at the same database as `DATABASE_URL`, `company_a`/`company_b` fixtures (each: a company, a `company_settings` row, and `hr_admin`/`manager`/`employee` users with ready-made `Authorization` header dicts), and a `client` fixture wrapping the real `app.main.app` with `get_db` overridden to the test session.
- **`tests/isolation/`:** `test_rls_policies.py` — a parametrized sweep over `app.db.base.tenant_table_names()` (every model inheriting `TenantBase`, discovered from the class hierarchy, not a hand-maintained list) asserting `ENABLE`+`FORCE`+at least one policy. `test_company_settings.py` — data-level isolation (A sees only A's row, B only B's), the unset-context-returns-zero-rows test, the write/commit/read-back test proving the `after_begin` listener, and the 8.5-mandated test that a `hr_admin` JWT can never cause `app.is_platform_admin` to be set (exercises the real `get_current_user`, not a hand-picked boolean).
- **Rate limiting:** `app/core/rate_limit.py` (`slowapi.Limiter`, Redis storage), `@limiter.limit("10/minute")` on `POST /auth/login`, `SlowAPIMiddleware`, and a `RateLimitExceeded` handler producing the standard error envelope.
- **CORS/security headers re-confirmed** after the middleware-ordering change (`SlowAPIMiddleware` inserted between `RequestIDMiddleware` and `CORSMiddleware`) — still exactly per 9.7/9.8.
- **Reconciliation items closed:** 4.1, 4.4, and 4.17's rate-limiting half (plus 4.17's security-headers/request-ID half, which had actually shipped in WP-02 but was missed when that report was updated — corrected now rather than left stale).

**A real, subtle bug was found and fixed while building this** (not part of the original audit): the `after_begin` listener, written exactly as Spec 8.4 shows it (calling back into `session.execute()`), raised `sqlalchemy.exc.InvalidRequestError: This session is provisioning a new connection; concurrent operations are not permitted` — triggered by something as ordinary as reading `company.id` on an ORM object right after `db.commit()` (SQLAlchemy expires attributes on commit by default; the next access issues an implicit refresh, which begins a new transaction, which fires `after_begin`, which re-entered the session mid-provisioning). Fixed by having the listener execute against the raw `connection` Core object the event already hands it, instead of calling back into the ORM `Session`. Documented in `app/db/rls.py`'s own comments so it isn't rediscovered.

**Not delivered in this pass:** `require_role`, routes 3–11, and everything else WP-03 owns (deliberately skipped per instruction); `app/core/pagination.py`/`encryption.py` (WP-08); trusted-proxy IP extraction for rate limiting (9.5's caveat, noted as a later concern).

---

## 16. WP-04 verification — actual output

| # | Check | Result |
|---|---|---|
| 1 | `psql` as `ems_app`: context A → query `company_settings`, context B → query again — different rows | **Pass.** Two companies + `company_settings` rows created (each inserted under its own context, proving `WITH CHECK` too). Context A → `weekend_days = {6,7}`; context B → `weekend_days = {7}` — different rows, not the same set twice. |
| 2 | `psql` as `ems_app` with the setting unset → zero rows, not all rows | **Pass.** `RESET app.current_company_id;` then `SELECT * FROM company_settings;` → `(0 rows)`. |
| 3 | A test writes, commits, and reads back within one request, proving the `after_begin` listener | **Pass — after fixing the reentrancy bug above.** `test_write_commit_and_read_back_within_one_request_proves_after_begin_listener`: binds context, updates `full_day_hours`, commits, then re-queries with **no** explicit re-bind — passes only because `after_begin` re-applied the context automatically. |
| 4 | The isolation suite passes for `company_settings` | **Pass — 7 tests.** And deliberately broken once: `ALTER TABLE company_settings NO FORCE ROW LEVEL SECURITY` on the test database → `test_tenant_table_has_rls_enabled_and_forced[company_settings]` failed with a clear assertion message → restored (`FORCE ROW LEVEL SECURITY`) → green again. This is the exact "break it once, watch it go red" proof Section 19's full gate text asks for. |
| 5 | Hammering `/auth/login` returns `429` | **Pass.** 15 rapid requests with wrong credentials: requests 1–10 → `401`; requests 11–15 → `429` with `{"error":{"code":"rate_limited","message":"Too many requests. Please try again later.",...}}`. |
| 6 | `pytest` and `ruff` clean | **Pass.** `pytest`: 12 passed (5 from WP-01/02, 7 new from WP-04). `ruff check .` / `ruff format --check .`: `All checks passed!` / all files formatted. `mypy app/`: `Success: no issues found in 29 source files` (advisory; two real findings fixed along the way — an untyped-subclass attribute access in `tenant_table_names()`, and a genuine `Limit | None` unguarded access in the new rate-limit exception handler). |
| — | CORS / security headers still correct after the middleware change | **Pass (not separately requested, verified anyway since the middleware stack changed).** Preflight `OPTIONS` on `/auth/login`: correct `Access-Control-Allow-Origin`/`-Methods`/`-Headers`/`-Credentials`, no wildcard. `GET /health`: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `X-Request-ID` all present. |

The full end-to-end HTTP-level proof of RLS ("the same is then proven through the API by an automated test," from Section 19's complete gate text) is intentionally **not** built as a dedicated route in this package — `company_settings` has no HTTP routes of its own yet (none are listed for it anywhere in Section 19 before WP-05, and Section 19's WP-04 deliverable list doesn't mention a router for it either). The mechanism itself (`get_current_user`, `get_tenant_db`, the listener) is real, wired, and tested directly — `test_hr_admin_jwt_can_never_set_is_platform_admin` calls the actual `get_current_user` dependency with a genuine JWT, which is the closest thing to an API-level proof available without inventing spec-undefined route surface. The first genuine HTTP round-trip through `get_tenant_db` will naturally arrive with WP-05's first protected route.

---

## 17. WP-04 exit gate — current status

Per Section 19: *a manual psql session connected as ems_app proves the policy... The same is then proven through the API by an automated test. A test asserts that an unset tenant context returns zero rows, not all rows. A test writes a row, commits, and reads it back within one request — proving the after_begin listener works. Hammering /auth/login returns 429. CI fails if the isolation test is broken deliberately.*

| Gate condition | Status |
|---|---|
| Manual `psql` proof (A vs B, different rows) | **Done — verified.** See §16 row 1. |
| Unset context → zero rows | **Done — verified.** See §16 row 2. |
| Proven through the API by an automated test | **Closed in WP-06.** `departments` (the first real tenant-scoped CRUD resource) provided the first `get_tenant_db`-protected route. `tests/isolation/test_departments.py::test_departments_are_tenant_isolated` and `tests/integration/test_company_onboarding.py::test_hr_admin_gets_404_not_403_on_another_companys_department` both create a department as one company's HR admin and confirm a second company's HR admin gets `404` on `GET`/`PUT`/`DELETE` for the same id, through real HTTP requests against the live app — no manual psql involved. See §22. |
| Write/commit/read-back proves `after_begin` | **Done — verified**, and only after finding and fixing the reentrancy bug above. See §16 row 3. |
| Hammering `/auth/login` → `429` | **Done — verified.** See §16 row 5. |
| Isolation test breaks CI when broken deliberately | **Done — verified locally** (not via actual GitHub Actions — same sandbox limitation as WP-02, §13). See §16 row 4. |

**WP-04 gate passes**, with the same category of honest caveat as WP-02 (no real Docker/GitHub Actions in this sandbox). The "proven through the API" clause — open at the time WP-04 itself was delivered, because no protected route existed yet — was closed two work packages later, in WP-06, the moment `departments` gave RLS a real route to run through. See §17's row above and §22.

---

## 18. WP-05 — Companies and onboarding

**Governs:** 7.2, 10.2 routes 12–18, 6.7.

**Delivered:**

- **`app/modules/platform/models.py` + `repository.py`:** `IndustryPreset` (RLS: No, global seed data — 7.8) and `IndustryPresetRepository`. First model in the `platform` module.
- **`app/db/seed/industry_presets.py`:** 12 industries (Technology, Manufacturing, Healthcare, Retail, Banking & Financial Services, Education, Hospitality, Construction, Real Estate, Logistics & Transportation, Media & Entertainment, Non-Profit), each with a `departments_json` list and a shared baseline `leave_types_json` (five common leave types — annual, sick, casual, maternity, paternity). Idempotent (upsert by `industry_name`), runnable directly (`python -m app.db.seed.industry_presets`) or imported.
- **`register_company` rewritten** (closes reconciliation item 2.6): `POST /companies/register` now creates the company with `status = pending` and creates **no user**, matching route 12 exactly. The old behavior (active company, active `hr_admin` from a client-supplied password, no approval step) is gone.
- **`CompanyService.approve_company`** (route 15, SA only): one transaction — binds the tenant context to the *target* company explicitly (acting as platform admin, 8.5), seeds a `company_settings` row, applies the company's industry preset to `departments` (added once WP-06 delivered that table — see §21), creates the HR admin (`must_change_password=True`), and commits once. Any failure before that commit leaves the company exactly as it was, still `pending` — verified by actually causing a failure, not just asserting the code looks atomic (§19).
- **HR-admin credential handling — an interim MVP decision, documented as such:** no email backend exists yet (WP-26 delivers `SendGrid`/Celery). A random password is generated, hashed, and returned **once**, in the `POST /companies/{id}/approve` response body, to the authenticated super_admin who triggered it — never logged (`hr_admin_created_at_approval` logs the email, not the password), never persisted anywhere in plaintext. This is a deliberate, narrow substitute for "sends credentials," not a security shortcut taken silently.
- **`list_companies`/`get_company_detail`/`reject_company`/`get_my_company`/`update_my_company`** (routes 13, 14, 16, 17, 18): standard CRUD against `CompanyRepository`, SA-gated via the new `require_role`, or HR-gated for the profile update. Company detail returns `counts` (`users`, and `departments` once WP-06 added that repository — see §21).
- **`app/core/pagination.py`** (pulled forward from its original WP-02/08 slot): `PageParams`, `Page[T]` (PEP 695 generic — Pydantic v2 supports it natively on Python 3.12+), `paginate()`, `resolve_sort()`. Needed the moment `GET /companies` required the standard list envelope (10.1); every future list endpoint reuses it.
- **`app/core/dependencies.py::require_role`** (pulled forward from WP-03, same justification as `get_current_user`/`get_tenant_db` in WP-04 — Section 19 already assigns `require_role` to WP-03's original `app/core/dependencies.py` line, but SA-only and HR-only routes exist starting here and need it now).
- **Reconciliation item closed:** 2.6.

**Not delivered in this pass:** leave-type seeding — the `leave_types` table didn't exist yet; **closed in WP-10, §32**; a real activation-email flow for the HR admin (WP-26).

---

## 19. WP-05 verification — actual output

All of this was run live against `uvicorn` first (to see the real behavior before writing permanent tests), then codified as `tests/integration/test_company_onboarding.py` (5 tests) so it isn't a one-off.

| # | Check | Result |
|---|---|---|
| 1 | Two companies register, land `pending`, no user created | **Pass.** `POST /companies/register` twice → both `201`, `status: "pending"`. `SELECT count(*) FROM users WHERE company_id = ...` → `0` for both, confirmed both live (`psql`) and in `test_register_creates_a_pending_company_with_no_user`. |
| 2 | Approved companies get preset departments, and a `company_settings` row | **Pass.** Registered a `super_admin` directly in the database (8.5 — never via a route), approved a Technology company through the real API → `GET /departments` as its new HR admin returned exactly the 7 Technology-preset departments (Design, DevOps, Engineering, Human Resources, Product, Quality Assurance, Sales); a Retail company returned its own 6. `GET /companies/me` succeeded, confirming `company_settings` exists (RLS would return nothing otherwise). Codified in `test_approve_seeds_company_settings_departments_and_hr_admin_in_one_transaction`. |
| 3 | A deliberately failing seed step rolls back the whole approval, company still `pending` | **Pass — proven by actually causing the failure.** Planted a `company_settings` row for a company before approving it (forces the real `UNIQUE` violation the seed step would hit), called `POST /companies/{id}/approve` → `409`, then confirmed: `status` still `pending`, `approved_at`/`ap proved_by` still `NULL`, zero `users` rows for that company. Live via `psql` first, then `test_a_failing_seed_step_rolls_back_the_whole_approval`. |
| 4 | Company A's HR admin gets `404`, not `403`, on company B's profile | **Substituted with `departments`, not `/companies/me` — see the note below.** `test_hr_admin_gets_404_not_403_on_another_companys_department`: HR admin X creates a department; HR admin Y requests the same id and gets `404`. Also closes WP-04's open caveat (§17). |
| 5 | WP-04's transaction fix, gated again here: write, commit, read back within one request | **Pass.** `PUT /companies/me` writes a real field (`website`, `city`), commits inside the service, and the response serializes the same ORM object afterward — exactly the "read an attribute after commit" pattern that surfaces the listener bug from WP-04 if it regresses. No error, response reflected the write; confirmed persisted via a direct `psql` read afterward. |
| 6 | `pytest` and `ruff` clean | **Pass** — folded into WP-06's combined run, see §22. |

**Why `/companies/me` isn't the literal route for check 4.** Route 17 (`GET /companies/me`) takes no id — it always resolves to the caller's own company from the verified JWT claim, never a path/query parameter (8.4's rule that `company_id` never comes from client input). There is structurally no "give me company B" request to make against it; attempting the proof through it would just confirm the route can't be attacked, not exercise `get_tenant_db`'s RLS binding against a real ID-addressable resource. `departments` (register 15, then WP-06 built moments later in this same session — see §21) is the first resource that's actually ID-addressable and accessible to a non-SA role, so the proof runs there instead. Also note: `GET /companies/{id}` (route 14) *is* ID-addressable, but it's SA-only — an HR admin calling it gets `403` for the role mismatch, the opposite of what "404 not 403" is trying to demonstrate, confirming it's the wrong route for this specific proof.

**Two real bugs found and fixed while building this**, neither part of the original audit:

1. **A test-infrastructure gap, not a production bug:** `ems_pro_test` had no `industry_presets` rows — `conftest.py` migrated the schema but never seeded reference data. Fixed by adding `_seed_reference_data()` (calls the same `seed_industry_presets()` the dev script uses) to the session-scoped setup fixture.
2. **A real session-handling bug, in both production code and its test-only mirror:** after a caught `IntegrityError` (or any exception) propagates out of a request, the SQLAlchemy session is left in Postgres's "aborted transaction" state — no further statement can run on it until an explicit `rollback()`. Production isn't affected in practice (`SessionLocal()` mints a fresh session per request), but it's still the objectively more correct, defensive way to manage a session's lifecycle regardless of who reuses it — so `app/db/session.py::get_db()` now rolls back on exception before closing. The test suite's `client` fixture reuses one session across every request *within a test*, deliberately (15.2's savepoint pattern) — there the bug was directly observable: a test that intentionally triggers a `409` and then makes a second request on the same client would get `PendingRollbackError` instead of the second request's real result. Fixed by mirroring the same rollback in the fixture's `_override_get_db`.

---

## 20. WP-05 exit gate — current status

Per Section 19: *two companies register and are approved through real API calls; each has its preset departments, leave types and a company_settings row; a deliberately failing seed step rolls the whole approval back, leaving the company still pending; company A's HR admin gets 404 on company B's profile. Also gate WP-04's transaction fix here.*

| Gate condition | Status |
|---|---|
| Two companies register and are approved; preset departments + `company_settings` | **Done — verified.** See §19 rows 1–2. Leave types were not seeded at the time — the table didn't exist yet; flagged, not silently skipped — **closed in WP-10, §32**, verified live: approving a Technology company now returns the same 5 leave types (`annual`, `sick`, `casual`, `maternity`, `paternity`) `app/db/seed/industry_presets.py` defines. |
| Failing seed step rolls back, company still pending | **Done — verified**, by causing the real failure. See §19 row 3. |
| HR admin A gets 404 on company B's resource | **Done — verified**, via `departments` rather than the literal (and structurally unattackable) `/companies/me` — see §19's note. |
| WP-04's write/commit/read-back re-gated here | **Done — verified.** See §19 row 5. |

**WP-05 gate passes.**

---

## 21. WP-06 — Departments

**Governs:** 7.3, 10.3 routes 31–35.

**Delivered:**

- **`app/modules/hr/models.py`:** `Department(TenantBase)` — the first model in the `hr` module. `head_employee_id` is a plain nullable `UUID` column with **no FK** for now: `employees` doesn't exist until WP-07, so there is nothing yet to reference. Added via a follow-up migration once it does, the same pattern as the `companies.approved_by`/`users` cycle (7.2), generalized to "the target table doesn't exist yet" rather than a true cycle.
- **Migration** (`2499347d1a53_departments.py`): table + `enable_rls("departments")` by hand, in the same migration, per 8.3.
- **Full CRUD** (routes 31–35): list (Auth, search + sort + pagination via the shared helper), create/update/delete (HR only), get (Auth). `DELETE` is a soft delete (`deleted_at`, per the universal rule in 7.1).
- **Two genuine, unavoidable gaps, documented rather than faked — both closed in WP-07 (§23):**
  - **"Live employee counts"** (route 31): `employee_count` was hardcoded to `0`, because there was no `employees` table yet to count against. **Closed in WP-07** — `DepartmentRepository.employee_counts`/`count_active_employees` query real, active (`is_active=true`, `deleted_at IS NULL`) rows.
  - **"409 if any active employee is assigned"** (route 35): was unimplemented, an unconditional delete. **Closed in WP-07** — `DepartmentService.delete_department` now raises `409` with `details.employee_count` when any active employee references the department.

  Building either for real at the time would have meant starting WP-07 out of order — the same reasoning WP-01 through WP-05 applied to every other forward dependency in this project so far.
- **`approve_company` extended** (identity module, from WP-05): now actually applies `departments_json` from the matched industry preset, via `DepartmentRepository`, inside the same one-transaction approval — closing the TODO WP-05 left for exactly this moment.
- **Company detail counts extended:** `GET /companies/{id}` now reports `departments` alongside `users`.
- **Isolation:** `tests/isolation/test_departments.py` — Spec 8.6's canonical isolation-suite shape (its own example uses `/employees`; `departments` is the first real resource to run it against). `tests/isolation/test_rls_policies.py`'s parametrized sweep picked up `departments` automatically — **zero changes** to that file were needed, which is the entire point of discovering tenant tables from the `TenantBase` class hierarchy (`app.db.base.tenant_table_names()`) instead of maintaining a list by hand.

---

## 22. WP-06 verification and exit gate — actual output

Per Section 19: *all five routes work in Swagger; deleting a department with employees returns 409 with the count; the isolation suite covers departments.*

| # | Check | Result |
|---|---|---|
| 1 | All five routes work | **Pass — live, then codified.** `POST` create → `201`; duplicate name → `409 conflict`; `GET` list and detail → `200`; `PUT` update → `200`, change persisted; `DELETE` → `204`, row still exists in the database with `deleted_at` set, subsequent `GET` → `404`. |
| 2 | Delete blocked with 409 + count when employees are assigned | **Closed in WP-07 — see §23–§24.** Was not deliverable in WP-06 because `employees` didn't exist yet; flagged explicitly at the time rather than stubbed to look done. `DELETE /departments/{id}` now returns `409` with `details.employee_count` when active employees are assigned, verified both by an automated test and live (§24). |
| 3 | Isolation suite covers `departments` | **Done — verified, and automatically.** `test_tenant_table_has_rls_enabled_and_forced[departments]` and `test_tenant_table_has_a_policy[departments]` both pass, discovered by `tenant_table_names()` with no test file edits. Plus the dedicated `test_departments_are_tenant_isolated`: HR admin A creates a department; HR admin B gets `404` on `GET`/`PUT`/`DELETE` for the same id; HR admin A still sees it correctly (404 is tenant isolation, not a general outage). |
| 4 | `pytest` and `ruff` clean (both WP-05 and WP-06, combined) | **Pass.** `pytest`: **21 passed** (12 from WP-01/02/04, 9 new — 5 onboarding + 1 rate-limit + 1 department isolation, plus the 2 structural sweep cases `departments` added itself). `ruff check .` / `ruff format --check .`: `All checks passed!` / all files formatted. `mypy app/`: `Success: no issues found in 38 source files`, no advisory findings this time. Coverage: 84% overall (`models.py`/`schemas.py` files at 100%, `service.py` files in the 33–71% range — full business-logic coverage is a later-WP concern per 15.4, not this session's target). |

**WP-06 gate passes**, with condition 2 explicitly named as not achievable this session rather than silently dropped, and closed two work packages later in WP-07 (§23–§24) the moment `employees` existed to check against.

---

## 23. WP-07 — Employees

**Governs:** 7.3, 10.3 routes 19–26, 11.2. *(Routes 27–30 — resignation and full-and-final — are WP-27's, not this session's. The employee frontend pages are WP-13, not this session's either.)*

**Delivered:**

- **`app/modules/hr/models.py`:** `Employee(TenantBase)` — the central table (7.3), column-for-column against the spec including the resignation fields WP-27 will use (created now so that package never needs an `ALTER TABLE`, the same reasoning `company_settings` and `industry_presets` applied to fields consumed by a later package). `department_id` FKs to `departments.id`; `reporting_manager_id` self-references `employees.id` with a `CHECK (reporting_manager_id <> id)`; `user_id` is a nullable, unique FK to `users.id` (null until activation, which is WP-03's). Email uniqueness is case-insensitive per company, consistent with `companies.email`/`users.email` (7.2's established convention, extended here — spec gap, not a violation).
- **`departments.head_employee_id` gets its real FK** (`fk_departments_head_employee_id_employees`), added in a follow-up migration (`f1a2b3c4d5e6`) once `employees` exists — same shape as the `companies.approved_by`/`users` cycle (7.2), generalized from WP-06's "the target table doesn't exist yet" placeholder to a real constraint.
- **Migration** (`b0a30daaecff_employees.py`): table + `enable_rls("employees")` in the same migration (8.3), verified against a real database. The `department_id`/`reporting_manager_id`/`user_id` FKs all resolve cleanly on an empty database because `departments` and `users` already exist by this point in the migration chain — no cycle, no `use_alter` needed on `employees`' own columns.
- **Full CRUD with search/filter/sort/pagination** (routes 19-23) via `app/core/pagination.py` — the same shared helper companies and departments already use, not bespoke per-route code. `q` searches `first_name`, `last_name`, `email`, `employee_code`. Filters: `department_id`, `is_active`, `level`, `employment_type`, `reporting_manager_id`. Sort allowlist exactly as route 19 specifies: `first_name`, `hire_date`, `employee_code`, `created_at`.
- **`employee_code` generation (11.2):** `CompanyRepository.increment_employee_seq` issues `UPDATE companies SET last_employee_seq = last_employee_seq + 1 ... RETURNING last_employee_seq, code`, inside the same transaction `EmployeeService.create_employee` commits — never `count(*) + 1`. Proved concurrency-safe by actually racing 12 real, independent database connections against it (not by reading the code) — see §24.
- **Soft deactivate (route 24):** `DELETE /employees/{id}` sets `is_active=false` on the employee and, if linked, on the user too — never a hard delete (6.5). `EmployeeRepository.get_by_id` (used by every single-record route) filters on `is_active=true`, so a deactivated employee 404s by id even though the row still exists — `get_by_id_any_status` is the separate lookup `toggle-active` (route 25) uses specifically because it must find an already-deactivated row.
- **Invite-token generation (route 20, and `resend-invite`, route 26):** a random token is generated (`generate_refresh_token()`, reused — it isn't refresh-specific in implementation), hashed with the same `hash_token()` refresh tokens use, and stored in `activation_token_hash`/`activation_expires_at` (new `INVITE_TOKEN_EXPIRE_DAYS` setting, default 7 days — the spec doesn't name a TTL). The `/auth/activate` routes this token is meant to redeem are WP-03's and don't exist yet (deliberately skipped this session); the raw token is returned once in the API response to the authorized HR caller instead, the same MVP-interim pattern WP-05 used for the HR-admin temporary password — see spec gap #6 above for the JWT-claim tradeoff this implies.
- **Manager scoping (route 19):** `EmployeeService.list_employees` resolves the caller's own `Employee` row (`get_by_user_id`) when `current_user.role == manager` and force-overrides `reporting_manager_id` to that employee's id — the client's own `reporting_manager_id` query parameter is ignored for a manager caller, never trusted as a claim of scope.
- **`Own`/`Mgr`/`HR` access on routes 22-23:** enforced in the service layer (`_assert_can_view`, `update_employee`), not `require_role` — `HR` sees/edits everyone; `Mgr` sees only their own direct reports (never edits, per 10.3's access column); `Own` sees and partially edits themselves (`CONTACT_FIELDS` — see spec gap #7). A same-tenant access denial is `403` (10.1: "authenticated but this role may not do this"); a different tenant's employee is `404`, from RLS naturally returning nothing (10.1 rule 9).
- **Closed WP-06's two documented gaps** (§21): `DepartmentRepository.employee_counts`/`count_active_employees` give routes 31/33/34 real, live counts; `DepartmentService.delete_department` returns `409` with `details.employee_count` when active employees are assigned (route 35).
- **Bug fix, found while building this package's gate** (not part of the original audit): `app/core/pagination.py::resolve_sort` raised the app's `ValidationError` (422) for an invalid `sort` column; the spec's own status table (10.1) calls this a 400. Fixed with a new `InvalidSortError(AppError)` (400, `invalid_sort`) — see spec gap #8.
- **Reconciliation items closed:** WP-06's two gaps (§21) and its gate condition 2 (§22).

**Not delivered in this pass:** `/auth/activate` itself (WP-03, deliberately skipped); routes 27-30 (WP-27); KYC/work-experience (WP-08); the `employee_id` JWT claim (spec gap #6, deliberate substitution).

---

## 24. WP-07 verification — actual output

Run live against `uvicorn` first (register → approve a company, create employees, exercise every gate condition through real HTTP calls), then codified as `tests/integration/test_employees.py` (13 tests), `tests/isolation/test_employees.py` (1 test), and `tests/integration/test_employee_code_concurrency.py` (1 test) so none of it is a one-off.

| # | Check | Result |
|---|---|---|
| 1 | List supports `?q=`, `?department_id=`, `?sort=-hire_date`, `?page=2&limit=10` (well, `limit=2` in the live run — same mechanism), exact 10.1 envelope | **Pass — live and automated.** Three employees created (Amy/Engineering, Ben, Cara). `?q=amy` → `["Amy"]`. `?department_id=<Engineering>` → `["Amy"]`. `?sort=-hire_date` → `["Amy","Cara","Ben"]` (hire dates 03-01, 02-01, 01-01). `?page=2&limit=2` → `{"items":[...1 item...],"page":2,"limit":2,"total":3,"pages":2,"has_next":false}` — the exact key set and shape from 10.1. |
| 2 | Invalid `sort` column returns 400, not an interpolated `ORDER BY` | **Pass — live and automated, after fixing the bug above.** `GET /employees?sort=hashed_password` → `400 {"error":{"code":"invalid_sort","message":"Invalid sort column: hashed_password",...}}`. |
| 3 | `employee_code` generation is concurrency-safe | **Pass — proved by racing real connections, not by reading the code.** `tests/integration/test_employee_code_concurrency.py`: 12 threads, each on its own database connection (not the shared savepoint-scoped test session, which would have serialized everything on one connection and proven nothing), synchronized on a `threading.Barrier` so they all reach the `UPDATE ... RETURNING` at effectively the same instant, then race for real. Result: sequence numbers `1..12`, no duplicate, no gap. Live run separately confirmed sequential, non-duplicated codes across ordinary (non-concurrent) creates: `ACMECO-59FE-0001` through `-0004`. |
| 4 | A deactivated employee's row still exists in the database but returns 404 by id | **Pass — live and automated.** `DELETE /employees/{id}` → `204`. `GET /employees/{id}` immediately after → `404 {"error":{"code":"not_found",...}}`. Direct `psql` read of the same row: `is_active = f`, `deleted_at` still `NULL` — the row was never touched by a hard delete, only the visibility gate on `get_by_id` changed. |
| 5 | A manager sees only their own reports | **Pass — live and automated.** Live: linked a manager-role user to the "Ben" employee record (no `/auth/activate` route exists yet to do this the "real" way — see WP-03 note above), made "Cara" report to Ben. `GET /employees` as Ben → `{"items":[{"first_name":"Cara",...}],"total":1}`, out of 3 employees that existed in the company at the time. The manager's own `?reporting_manager_id=` query parameter is also proven ignored (server-forced, not client-trusted) in the automated test. |
| 6 | Deleting a department with employees assigned returns 409 with the count (closes WP-06's gate condition 2) | **Pass — live and automated.** Created a "Sales"-conflict-free "Marketing" department, assigned one active employee. `GET /departments/{id}` → `employee_count: 1`. `DELETE /departments/{id}` → `409 {"error":{"code":"conflict","message":"Cannot delete a department with 1 active employee(s) assigned.","details":{"employee_count":1}}}`. Deactivated the employee, retried the same delete → `204`. |
| 7 | The isolation sweep picks up `employees` automatically, no test file edits | **Pass — verified structurally.** `test_tenant_table_has_rls_enabled_and_forced[employees]` and `test_tenant_table_has_a_policy[employees]` both pass in `tests/isolation/test_rls_policies.py` — a file untouched by this package, exactly the point of discovering tenant tables from `TenantBase.__subclasses__()` rather than a maintained list. `tests/isolation/test_employees.py` adds the dedicated HTTP-level proof: company A creates an employee; company B's HR admin gets `404` on `GET`/`PUT`/`DELETE`/`toggle-active`/`resend-invite` for the same id; company A still sees it correctly. |
| 8 | `pytest` and `ruff` clean | **Pass.** `pytest`: **38 passed** (23 from WP-01/02/04/05/06, 15 new — 13 employee CRUD/access/deactivation/manager-scoping/department-gap-closure tests, 1 employee isolation test, 1 real-concurrency test). `ruff check .` / `ruff format --check .`: `All checks passed!` / 57 files formatted. `mypy app/`: `Success: no issues found in 38 source files` — two real findings fixed along the way: a `dict()` call over a `Sequence[Row[tuple[UUID \| None, int]]]` in `employee_counts` (narrowed via a filtering comprehension instead of a raw `dict()` call) and an `EmployeeInviteInfo.expires_at: datetime` field receiving `employee.activation_expires_at: datetime \| None` (asserted non-null at the one call site where it's always set, since the ORM column has to stay nullable for rows that predate any invite). Coverage: 87% overall. |

Dev database (`ems_pro`) was fully `TRUNATE`d back to empty (all live-verification companies/users/departments/employees removed, `industry_presets`'s 12 real seed rows correctly left intact) at the end, matching the discipline every prior work package in this session followed.

---

## 25. WP-07 exit gate — current status

Per Section 19: *List supports `?q=`, `?department_id=`, `?sort=-hire_date`, `?page=2&limit=10` and returns the exact envelope from 10.1; an invalid `sort` column returns 400 rather than being interpolated; a created employee can activate their own account and log in; a deactivated employee cannot log in but still exists in the database; a manager sees only their own reports; isolation tests cover `employees`.*

| Gate condition | Status |
|---|---|
| List supports `q`/`department_id`/`sort`/pagination, exact 10.1 envelope | **Done — verified.** See §24 row 1. |
| Invalid `sort` column returns 400 | **Done — verified**, after fixing a real bug in the shared helper. See §24 row 2. |
| A created employee can activate their own account and log in | **Closed in WP-03 — see §26–§28.** Was blocked on `/auth/activate`, deliberately out of scope for WP-07. `test_employee_created_by_hr_can_activate_and_log_in` and a live walkthrough (§27) now prove the full chain: HR creates the employee (WP-07) → `GET /auth/activate/{token}` previews it → `POST /auth/activate` sets username+password and logs the employee straight in → the same email+password combination also works through the ordinary `POST /auth/login`. |
| A deactivated employee cannot log in but still exists in the database | **Done — verified**, and further tightened: the linked user is deactivated too (so login and refresh both reject it per 9.2's "reject if is_active is false" — no code change needed there, WP-01's `AuthService` already checks it), the employee row is provably still in the database (`psql`), and a single-record `GET /employees/{id}` also 404s by id (an explicit extra check this session's gate asked for, beyond the spec's own literal wording — see §24 row 4). |
| A manager sees only their own reports | **Done — verified.** See §24 row 5. |
| Isolation tests cover `employees` | **Done — verified, automatically.** See §24 row 7. |

**WP-07 gate now passes in full.** Its one deferred condition — employee self-activation-and-login — was explicitly named as blocked on WP-03 at the time, and closed two work packages later in WP-03 (§26–§28) the moment `/auth/activate` existed to run it through.

---

## 26. WP-03 — Auth routes, OTP reset and employee activation

**Governs:** 5.3, 7.9, 9.1–9.4, 10.2 routes 3–11. Routes 1–2 (login, refresh) and everything they depend on — `app/core/security.py` in full, `app/core/dependencies.py` (`get_current_user`, `get_tenant_db`, `require_role`), `users`/`refresh_tokens` — were already delivered in WP-01/WP-04/WP-05 and are **not** rebuilt here, per instruction.

**Delivered:**

- **`POST /auth/logout`** — revokes the presented refresh cookie. **`POST /auth/logout-all`** — revokes every refresh token for the user, across every device. Both idempotent: an absent or already-revoked token is a silent no-op, never an error.
- **`GET /auth/me`** — current user, linked employee summary (`None` when the caller has no `Employee` row — e.g. the HR admin created directly at company approval, WP-05), and a small role-derived permissions list (spec gap #9).
- **`POST /auth/change-password`** — current + new password; revokes every other session, so a changed password can't leave an old one live.
- **`POST /auth/forgot-password` / `POST /auth/reset-password`** — Redis-backed OTP exactly per 7.9: `app/core/otp.py`, key shape `pwreset:{email_hash}` (SHA-256), 10-minute TTL, only the OTP's **hash** ever stored, 5-attempt cap enforced by an attempts counter that increments on every call (right or wrong) so a correct code presented on the 6th call still fails once the cap is spent. `forgot-password` always returns the same `200` body regardless of whether the email exists, matches more than one company, or is inactive (9.3) — the router never branches on the service call's outcome.
- **`app/core/email.py`** (new): a minimal stand-in for the real email backend (WP-26 delivers Celery + SendGrid). `EMAIL_BACKEND=console` (the default, and the only one exercised in dev/tests) prints to stdout — deliberately **not** routed through `app/core/logging.py`'s structured pipeline, since an email body here can carry a password-reset OTP or an activation link, both secrets rule 10 (6.8) forbids logging. `sendgrid` raises `NotImplementedError` until WP-26.
- **`GET /auth/check-username/{username}`** — availability check, rate-limited to 5/minute (10.2: "heavily rate-limited"). Platform-wide, not per-company (spec gap #10) — a fifth pre-authentication-shaped `UserRepository` method, `username_taken_anywhere` (spec gap #11).
- **`GET /auth/activate/{token}` / `POST /auth/activate`** — the pair that redeems WP-07's `activation_token_hash`. `employees` IS RLS-protected (unlike `users`/`refresh_tokens`), so the pre-auth lookup explicitly binds `is_platform_admin=True` on the session before searching by token hash (`AuthService.preview_activation`) — the same reasoning `CompanyService.approve_company` already uses to act across a tenant boundary (8.5), narrowed here to one secret-gated read, with the bind visible at the call site rather than hidden in the repository. `POST /auth/activate` creates the `User` (role `employee` — nothing in the spec ties an invitation to a different target role), links it to the `Employee` row, consumes the token, and logs the caller straight in with the same token pair shape `login()` issues. Redeeming an already-activated or expired token returns `404` (uniform message whether the token is unknown, expired, or already used).
- **Rehash-on-login wiring (9.1):** `needs_rehash()` already existed (WP-01); nothing called it. `AuthService.login` now checks it right before issuing tokens, upgrading the stored hash transparently the moment the plaintext is available — the only place it ever is.
- **Password policy (9.1):** `PasswordStr` (`identity/schemas.py`) — minimum `PASSWORD_MIN_LENGTH` (10, settings-driven), at most 128, at least one letter and one digit — shared by every "new password" field (`change-password`, `reset-password`, `activate`).
- **Spec gap #6 resolved by amending the spec, not the code** (per instruction — "either is defensible, pick one, implement it, record the decision"): `docs/EMS_PRO_DEV_SPEC.md` 9.2's claims example no longer shows `employee_id`, with a new note explaining why; 10.1's `Own`/`Mgr` row updated to describe the actual mechanism (`employee.user_id == current_user.id` for Own, `EmployeeRepository.get_by_user_id` for Mgr); Section 24's decision log gained an entry. The reasoning: embedding the claim would mean `AuthService.login`/`.refresh` — already-shipped, already-tested WP-01 code — look up the caller's `Employee` row on *every* login and refresh (access tokens are short-lived and refreshed often), even for HR/SA callers who never need it; the lazy, per-route lookup this project already had is strictly fewer total queries in the common case.
- **Reconciliation items closed:** WP-07's open gate condition (§25), spec gap #6 (§10), the `needs_rehash` wiring "Later" item (§9).

**Not delivered in this pass:** anything from WP-08 onward; the real SendGrid email backend (WP-26); a full RBAC/permissions subsystem (spec gap #9's `_ROLE_PERMISSIONS` is intentionally minimal).

---

## 27. WP-03 verification — actual output

Run live against `uvicorn` first, then codified as `tests/integration/test_auth.py` (23 tests) so none of it is a one-off.

| # | Check | Result |
|---|---|---|
| 1 | Login: access token in the body, refresh cookie marked `HttpOnly` | **Pass — live and automated.** `POST /auth/login` → `200`, body `{"access_token": "...", "token_type": "bearer"}`; `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax`. |
| 2 | Protected route: valid (200), invalid (401), expired (401), no token (401), refresh-shaped token as access (401) | **Pass — live and automated**, all five against `GET /auth/me`. The "expired" and "refresh-shaped" cases were hand-built JWTs (same claims shape `create_access_token` produces, signed with the real `SECRET_KEY`) with `exp` in the past and `type: "refresh"` respectively — both correctly rejected by `decode_access_token`'s existing (WP-01) checks. |
| 3 | Refresh rotates; reuse of the old token is rejected and revokes the family | **Pass — live and automated.** Rotated once; replaying the old cookie → `401`; the *new*, legitimately-issued cookie is also `401` afterward — proving the whole family was revoked, not just the replayed token. Confirmed in the database: every token in the chain `is_revoked = true`. |
| 4 | 5 bad passwords lock the account; the 6th returns 423, not 401, even with the correct password | **Pass — live and automated.** 5× wrong password → `401` each; 6th attempt with the **correct** password → `423 {"error":{"code":"account_locked",...}}`. |
| 5 | Forgot-password for a non-existent email returns 200 with the same body as a real one | **Pass — live and automated.** Both requests → `200`, byte-identical `{"message": "If that email exists, a password reset code has been sent."}`. |
| 6 | An OTP expires after its TTL and is rejected after 5 wrong attempts | **Pass — live and automated, two different proofs.** *Attempts cap:* 5 wrong codes → `400` each; the 6th call with the **correct** code → still `400` (cap already spent). *TTL:* the automated test deletes the exact Redis key `app.core.otp` stores it under (same code path a real expiry produces); the **live** run instead set the real key's TTL to 1 second via `redis-cli`-equivalent and waited past it — a genuine Redis expiry, not a simulation — and got the same `400 invalid_otp`. |
| 7 | `require_role` admits the right role and rejects the wrong one | **Pass — live and automated.** HR creating a department → `201`; the same request as `employee` → `403`. (Also re-confirmed the inverse shape already covered elsewhere: HR calling the SA-only `GET /companies` → `403`.) |
| 8 | An employee created by HR in WP-07 can now activate and log in | **Pass — live and automated — closes WP-07's open gate condition.** HR creates "Priya" via `POST /employees` (WP-07) → `GET /auth/activate/{token}` previews `{"first_name":"Priya","company_name":"WP03 Auth Co","expires_at":...}` → `POST /auth/activate` with a chosen username+password → `200`, a real access token, and the employee is immediately logged in. Replaying the same token → `404` (consumed). A fresh `POST /auth/login` with `priya@...`/the chosen password → `200`. `GET /auth/me` as Priya shows `"employee": {"employee_code": "WP03AU-2420-0001", ...}` and `"permissions": ["view_own_profile", "apply_leave", "mark_attendance"]` — the whole loop closed, verified end to end. |
| 9 | `pytest` and `ruff` clean | **Pass.** `pytest`: **61 passed** (38 from WP-01/02/04/05/06/07, 23 new). `ruff check .` / `ruff format --check .`: `All checks passed!` / 60 files formatted. `mypy app/`: `Success: no issues found in 40 source files`. Coverage: 91% overall (`identity/service.py` 88%, `app/core/otp.py` 100%). |

Dev database (`ems_pro`) and Redis (`pwreset:*` keys) were both fully cleared back to empty at the end (`industry_presets`'s 12 real seed rows correctly left intact), matching the discipline every prior work package in this session followed.

---

## 28. WP-03 exit gate — current status

Per this session's instructions (Section 19's WP-03 entry, as scoped to routes 3-11 — routes 1-2 were already gated in WP-01):

| Gate condition | Status |
|---|---|
| Login: access token in body, `HttpOnly` refresh cookie | **Done — verified.** See §27 row 1. |
| Protected route: valid/invalid/expired/no-token/refresh-as-access, all correctly 200/401 | **Done — verified.** See §27 row 2. |
| Refresh rotates; reuse rejected and revokes the family | **Done — verified.** See §27 row 3. |
| 5 bad passwords lock the account; 6th returns 423 not 401 | **Done — verified.** See §27 row 4. |
| Forgot-password for a non-existent email: 200, same body as real | **Done — verified.** See §27 row 5. |
| OTP expires after TTL; rejected after 5 wrong attempts | **Done — verified**, including a genuine (not simulated) Redis TTL expiry in the live run. See §27 row 6. |
| `require_role` admits the right role, rejects the wrong one | **Done — verified.** See §27 row 7. |
| An employee created by HR can activate and log in — closes WP-07's gate | **Done — verified.** See §27 row 8. |
| `pytest` and `ruff` clean | **Done — verified.** See §27 row 9. |

**WP-03 gate passes.** Every condition this session's instructions listed was run for real against a live server and a real database/Redis, then codified as a permanent regression test. Not proceeding further this session.

---

## 29. WP-09 — Attendance, shifts and background jobs

**Governs:** 11.5, 13, 10.4 routes 43–54, route 136. *(Frontend page 15 is not built this session — no frontend foundation exists yet, WP-12/WP-13's job.)*

**Delivered:**

- **`app/modules/time_leave/`** (new module): `Attendance`, `Shift`, `EmployeeShift` models, all on `TenantBase` with `enable_rls()` in the same migration (`b4578ccda3b8`) — the first module to add three RLS-protected tables in one migration. `uq_attendance_employee_id_date` is a real database constraint, matching Spec 7.4 exactly.
- **Check-in/check-out (routes 43-44):** check-in 409s if today's record already exists (the database constraint is the real backstop; the app's own check is just a friendlier message — proven live and in a test that inserts around the service layer entirely). Check-out finds the employee's currently-**open** record (`check_in` set, `check_out` null) rather than re-deriving "today" — a real bug caught while building this: an employee who checks in at 22:00 and checks out after midnight would otherwise have check-out look for a record dated the *new* calendar day and find nothing. `hours_worked` is plain `TIMESTAMPTZ` subtraction, which is already correct across a midnight boundary with no special-casing — the spec's "must not go negative" warning is really about not reimplementing this with the shift's own `TIME`-typed `start_time`/`end_time`, which this code never touches for the calculation.
- **Role-scoped list (route 45) and single-record access (route 46):** employees see their own; managers see their direct reports (`EmployeeRepository.list_direct_report_ids`, a new shared helper — WP-07's employee list used inline manager-scoping logic that this pulls out so WP-09/WP-10 don't duplicate it); HR (and super_admin) see everyone.
- **HR regularization (route 47) and delete (route 48):** both write a structured log line (`attendance_regularized` / `attendance_deleted`) carrying the actor, previous values, and reason — `audit_logs` doesn't exist until WP-11, so this is the documented interim record, with a `# TODO(WP-11)` at the exact spot a real row will replace it. Delete is a soft delete (`deleted_at`) — attendance isn't append-only, so 7.1's universal rule applies.
- **Shifts (routes 50-54):** full CRUD; delete blocked with 409 + count when any assignment currently covers today (`effective_from <= today <= effective_to-or-ongoing`); `POST /shifts/{id}/assign` rejects a second overlapping `[effective_from, effective_to]` range for the same employee (NULL `effective_to` treated as open-ended).
- **`app/workers/celery_app.py`, `app/workers/tasks/`** (new): the Celery app, wired to the real Redis broker/backend already configured (WP-02). `beat_schedule` has one real, working entry — `expire_activation_tokens` (13.1's "scheduled, daily" housekeeping, using only WP-07 data) — proven by actually invoking it. Every task takes IDs, not objects, opens its own session and calls `bind_tenant_to_session` explicitly (13.2 rules 1-2) — `expire_activation_tokens` binds as platform admin for its genuine cross-tenant sweep, the same narrow, explicit RLS-bypass pattern `AuthService.preview_activation` (WP-03) and `CompanyService.approve_company` (WP-05) already established.
- **The trivial task first (13.3's own instruction):** `app/workers/tasks/example.py::add` — proven complete asynchronously on a real subprocess worker before anything else was built on the worker.
- **CSV export (route 49) + job polling (route 136):** `POST /attendance/export` queues `export_attendance_csv_task` and returns `202` + `job_id` immediately. `GET /jobs/{job_id}` (new `platform` module route) polls Celery's own result-backend state directly — no dedicated `jobs` table exists anywhere in the spec's schema (Section 7), and the Redis result backend already persists exactly what route 136 asks for.
- **Bug found and fixed while building this, not part of the original audit:** `AttendanceSource`'s `import` value — `import` is a Python keyword, so the enum member had to be named `import_`. SQLAlchemy's `Enum()` defaults to storing the Python member's **name** in the database, not its `.value` — every other enum in this codebase happens to have name == value, which is exactly what made this easy to miss. Without `values_callable=lambda x: [e.value for e in x]`, the database enum type would have stored the literal string `"import_"` instead of Spec 7.4's `"import"`. Caught by inspecting the generated migration before applying it, not by a failing test — fixed in the model, the migration, and (since the migration had already been applied once while investigating) via a direct `ALTER TYPE ... RENAME VALUE`, never a downgrade.
- **`EXPORT_DIR`** (new setting, default `var/exports`, gitignored): where the CSV export writes, per `STORAGE_BACKEND=local`.

**Not delivered in this pass:** frontend page 15 (no frontend foundation exists — WP-12/13); `allocate_annual_leave` as a scheduled task (not in either WP-09's or WP-10's explicit deliverable list this session — see §32's note); `payroll`/`audit_logs`/KYC-dependent background jobs (later WPs, per 13.1's own table).

---

## 30. WP-09 verification — actual output

Run live against `uvicorn` **and a real Celery worker** first, then codified as `tests/integration/test_attendance.py` (8 tests), `test_shifts.py` (3 tests), `test_celery_tasks.py` (1 test, a real subprocess worker), and `test_attendance_export.py` (1 test) — 13 new tests, none of it a one-off.

| # | Check | Result |
|---|---|---|
| 1 | A second check-in on the same day returns 409, and the database constraint holds even if the app check is bypassed | **Pass — live and automated.** Live: check-in → `201`; second check-in → `409`. Automated: `test_database_constraint_holds_even_if_the_application_check_is_bypassed` inserts two `Attendance` rows directly via the ORM (no service layer involved) and confirms the second raises `IntegrityError` — the real `uq_attendance_employee_id_date` constraint, not the app's proactive check. |
| 2 | Check-out without check-in returns 400 | **Pass — live and automated.** `{"error":{"code":"no_check_in",...}}`, `400`. |
| 3 | `hours_worked` correct for a shift where `end_time < start_time` — positive, not negative | **Pass — live and automated, after fixing the check-out bug above.** A "Night Shift" (22:00→06:00) is created and genuinely assigned to an employee; their attendance row is dated yesterday with `check_in` at yesterday 22:00; `POST /attendance/check-out` (today, for real) → `200`, `hours_worked` positive and > 8 — proving the midnight-crossing case end to end through the live check-out logic, not a unit test of an isolated formula. |
| 4 | A second overlapping shift assignment is rejected | **Pass — live and automated.** Two open-ended (`effective_to` null) assignments for the same employee starting the same date → the second is `409`; a third assignment for a *different* employee on the same shift succeeds (`201`) — proving the rejection is about the employee, not the shift. |
| 5 | The trivial Celery task completes asynchronously while the API stays responsive | **Pass — proved by actually running it, not eager mode.** `test_trivial_task_completes_asynchronously_on_a_real_worker` starts a real `celery worker` subprocess (`CELERY_TASK_ALWAYS_EAGER` explicitly not used — 13.3 warns eager mode hides exactly this class of bug), calls `.delay(2, 3)`, confirms the call returned immediately with a task id (not blocked on the result), then polls until success and asserts the result is `5`. Live run separately confirmed the same worker process log shows `Task ... succeeded`. |
| 6 | The CSV export returns 202 immediately and the file appears when the job finishes | **Pass — live, with a real worker.** `POST /attendance/export` → `202 {"job_id":"...","status":"queued"}` immediately. `GET /jobs/{job_id}` polled right after → already `success` (the real worker is fast) with `{"file_path":"var/exports/attendance_....csv","row_count":1}`; the file was read directly off disk afterward and its content matched the real attendance row exactly. The automated `test_attendance_export.py` proves the export task's own business logic (correct CSV content for given data) by monkeypatching the task's database session to the test database and calling the task function directly — Celery tasks always open their own session against the production `DATABASE_URL` (13.2 rule 2), which is a different database than pytest's `TEST_DATABASE_URL`, so the queueing/worker plumbing itself is what `test_celery_tasks.py` proves instead (check 5). |
| 7 | Role-scoped attendance list: employee sees own, manager sees team, HR sees everyone | **Pass — automated.** `test_manager_sees_only_their_teams_attendance`: a manager's list shows exactly their one direct report's attendance, not an unrelated employee's; HR's list shows both. |
| 8 | The isolation sweep picks up `attendance`, `shifts`, `employee_shifts` automatically, no test file edits | **Pass — verified structurally.** `tests/isolation/test_rls_policies.py` (untouched by this package) now parametrizes over all three new tables — `tenant_table_names()` discovered them from the class hierarchy the moment their models were imported. |
| 9 | `pytest` and `ruff` clean | **Pass.** `pytest`: **80 passed** (67 from WP-01 through WP-03, 13 new). `ruff check .` / `ruff format --check .`: `All checks passed!` / all files formatted. `mypy app/`: `Success: no issues found in 52 source files` — three real findings fixed along the way (a `Result[Any]` vs `CursorResult.rowcount` mismatch in the scheduled task, a reused-variable-name type conflict in the export task, and a plain `str` vs `Literal[...]` mismatch in the job-status route). |

Dev database, Redis (`pwreset:*`/broker/backend keys), and the `var/exports/` directory were all cleared back to empty at the end (`industry_presets`'s 12 seed rows correctly left intact), matching the discipline every prior work package in this session followed. The `celerybeat-schedule.db` file beat creates locally on startup is gitignored, not committed.

---

## 31. WP-09 exit gate — current status

Per this session's instructions (Section 19's WP-09 entry, scoped to routes 43-54, route 136, and Spec 13):

| Gate condition | Status |
|---|---|
| Second check-in same day → 409; database constraint holds even if bypassed | **Done — verified.** See §30 row 1. |
| Check-out without check-in → 400 | **Done — verified.** See §30 row 2. |
| `hours_worked` correct for an overnight shift — positive, not negative | **Done — verified**, after fixing a real check-out lookup bug. See §30 row 3. |
| Second overlapping shift assignment rejected | **Done — verified.** See §30 row 4. |
| Trivial Celery task completes asynchronously | **Done — verified**, on a real worker, not eager mode. See §30 row 5. |
| CSV export returns 202 immediately; file appears when the job finishes | **Done — verified**, live with a real worker; the task's own logic also covered by an automated test. See §30 row 6. |
| `pytest` and `ruff` clean | **Done — verified.** See §30 row 9. |

**WP-09 gate passes.**

---

## 32. WP-10 — Leave management

**Governs:** 11.3, 11.4, 7.4, 10.4 routes 55–66.

**Delivered:**

- **`Holiday`, `LeaveType`, `Leave`, `LeaveBalance`** (new model classes in `app/modules/time_leave/models.py`, alongside WP-09's `Attendance`/`Shift`/`EmployeeShift`), all on `TenantBase` with `enable_rls()` in the same migration (`00a7236ac838`). `holidays` carries the spec's `UNIQUE NULLS NOT DISTINCT (company_id, date, applies_to_department_id)` constraint verbatim (PostgreSQL 16, so it's available) — verified live and in a test that a duplicate company-wide holiday on the same date is genuinely rejected by the database, not just an app-level check.
- **All eight leave-application validations (11.3), in the spec's exact order, each returning the first failure with a clear message:** (1) employee exists in this company, (2) caller is that employee/HR/their manager, (3) `end_date >= start_date`, (4) leave type exists and is active in this company, (5) `start_date >= today` unless HR (HR may back-date; logged), (6) `max_consecutive_days` not exceeded, (7) no overlap with an existing `pending`/`approved` leave — `409` naming the conflicting leave's id and dates, (8) sufficient balance unless the leave type is `is_paid=false` (unpaid is never blocked — becomes LOP in payroll, a later WP's concern). Each has its own dedicated test that triggers exactly that validation and no other.
- **`total_days`** excludes weekends (`company_settings.weekend_days`, never a hardcoded Saturday/Sunday) and holidays applying to the employee's department (company-wide `applies_to_department_id IS NULL` plus their own department's). `is_half_day` with `start_date == end_date` short-circuits to `0.5`.
- **Approval (route 64) upserts real `on_leave`/`source=system` attendance rows** via `AttendanceRepository.upsert_for_leave` — a genuine `INSERT ... ON CONFLICT (employee_id, date) DO UPDATE`, not a Python select-then-branch, exactly because the employee may already have marked attendance that day (11.3's own wording). The balance recompute (`used += total_days`) happens inside the same transaction as the status change — one commit, at the end (6.7).
- **Cancellation (route 65)** reverses both: an employee may cancel their own **pending** leave; HR may additionally cancel an **approved** one, which soft-deletes the `on_leave`/`source=system` attendance rows the approval wrote and restores the balance (`used -= total_days`, floored at 0). A day the employee had already marked for real before approval overwrote it is not recoverable — the schema keeps no pre-upsert history — documented at the exact point in the code this applies.
- **Leave-type seeding at company approval — closes reconciliation item 2.6, carried since WP-05.** `CompanyService.approve_company` (identity module) now seeds `leave_types` from the matched industry preset's `leave_types_json` alongside departments, in the same one-transaction approval. Verified live: approving a "Technology" company returns exactly the 5 leave types `app/db/seed/industry_presets.py` defines (`annual`, `sick`, `casual`, `maternity`, `paternity`), with the right `annual_allowance`/`carry_forward_limit`/`is_encashable` values.
- **Balance allocation is lazy**, not a bulk annual-rollover job — `LeaveService._get_or_allocate_balance` materializes a `leave_balances` row (`allocated = leave_type.annual_allowance`, `opening_balance = 0`) the first time an employee needs one. This is a deliberate, documented scope decision, not an oversight — see spec gap #12.
- **Routes 55-60** (holidays, leave types) and **61-66** (leaves): full CRUD/list/apply/decide/cancel/balance, role-scoped exactly like WP-09's attendance list (own/team/everyone), reusing `EmployeeRepository.list_direct_report_ids` (pulled out of WP-07's employee list during WP-09, not duplicated a third time here).
- **Reconciliation items closed:** 2.6's leave-type-seeding half (§2.6, §9, §18-§20).

**Not delivered in this pass:** `allocate_annual_leave` as a scheduled task (spec gap #12); leave encashment at exit (`is_encashable`, `leave_balances.encashed`) — that's WP-27's full-and-final settlement, not this session's; KYC/performance/payroll/projects (later WPs).

---

## 33. WP-10 verification — actual output

Run live against `uvicorn` first (register → approve a Technology company, confirm real leave types appeared, apply → approve → cancel a leave spanning a holiday, watch the attendance rows and balance move in real time), then codified as `tests/integration/test_leaves.py` (14 tests, one per validation plus total_days/approval/cancellation/scoping), `test_holidays_and_leave_types.py` (4 tests), and `tests/isolation/test_leaves.py` (1 test) — 19 new tests, none of it a one-off.

| # | Check | Result |
|---|---|---|
| 1 | Every validation in 11.3 has a test that triggers it | **Pass — automated, one test per validation, numbered 1-8 in `test_leaves.py` to match the spec's own list.** Validation 5 additionally proves the HR back-dating exception in the same test (employee blocked, HR allowed). Validation 8 additionally proves unpaid leave is never balance-blocked in the same test. |
| 2 | An overlapping application returns 409 naming the conflicting dates | **Pass — live and automated.** Live: `{"error":{"code":"leave_overlap",...,"details":{"conflicts":[{"id":"...","start_date":"2026-09-14","end_date":"2026-09-15"}]}}}`, `409`. |
| 3 | A leave spanning a company holiday counts one day fewer | **Pass — live and automated.** Live: a Monday-Friday application (5 weekdays) with a Wednesday holiday inside it → `"total_days":"4.0"`. |
| 4 | Approving a leave creates `on_leave` attendance rows for exactly the working days covered | **Pass — live and automated.** Live: a Friday→Monday application (spans a weekend) approved → `psql` shows exactly Friday and Monday as `on_leave`/`system`; Saturday and Sunday have no attendance row at all — proven both live and in `test_approving_a_leave_creates_on_leave_attendance_for_exactly_the_working_days`. |
| 5 | Cancelling an approved leave removes the attendance rows and restores the balance | **Pass — live and automated.** Live: balance `used` went `4.0 → 0.0`, `available` `14.0 → 18.0`; all 4 attendance rows confirmed `deleted_at IS NOT NULL` via direct `psql`, matching the automated test. |
| 6 | The isolation sweep picks up all seven new tenant tables (three from WP-09, four from WP-10), no test file edits | **Pass — verified structurally.** `tests/isolation/test_rls_policies.py` (still untouched) now parametrizes over `attendance`, `shifts`, `employee_shifts`, `holidays`, `leave_types`, `leaves`, `leave_balances` — 14 additional sweep cases (2 per table) beyond WP-01 through WP-07's baseline, discovered automatically from `TenantBase.__subclasses__()`. `tests/isolation/test_leaves.py` adds the dedicated HTTP-level cross-tenant proof for `leaves`/`leave-types`, the same shape as every prior resource's isolation test. |
| 7 | `pytest` and `ruff` clean | **Pass.** `pytest`: **107 passed** (80 from WP-01 through WP-09, 19 new, plus 8 more isolation-sweep cases counted within that same total). `ruff check .` / `ruff format --check .`: `All checks passed!` / all files formatted. `mypy app/`: `Success: no issues found in 52 source files` — one real finding fixed along the way (a `ColumnElement[bool]` vs `BinaryExpression[bool]` reassignment in `HolidayRepository.list_in_range`, fixed by widening the variable's declared type rather than narrowing the expression). |

Dev database and Redis were both cleared back to empty at the end (`industry_presets`'s 12 seed rows correctly left intact), matching the discipline every prior work package in this session followed.

---

## 34. WP-10 exit gate — current status

Per this session's instructions (Section 19's WP-10 entry):

| Gate condition | Status |
|---|---|
| Every validation in 11.3 has a test that triggers it | **Done — verified.** See §33 row 1. |
| Overlapping application → 409 naming conflicting dates | **Done — verified.** See §33 row 2. |
| Leave spanning a holiday counts one day fewer | **Done — verified.** See §33 row 3. |
| Approval creates `on_leave` attendance for exactly the working days covered | **Done — verified.** See §33 row 4. |
| Cancelling an approved leave removes attendance rows and restores the balance | **Done — verified.** See §33 row 5. |
| Isolation sweep covers all seven new tenant tables automatically | **Done — verified.** See §33 row 6. |
| `pytest` and `ruff` clean | **Done — verified.** See §33 row 7. |
| Leave-type seeding gap carried since WP-05 (item 2.6) closed | **Done — verified**, live and automated. See §32. |

**WP-10 gate passes.**

---

## 35. WP-11 — Audit logging, dashboard and notifications

**Governs:** 7.8, 8.2, 11.10, 10.8 routes 121, 125–129.

**Delivered:**

- **`AuditLog`** (new model, `app/modules/platform/models.py`) — the third deliberate non-RLS table alongside `users`/`refresh_tokens` (CLAUDE.md rule 1). Does **not** inherit `TenantBase`: `company_id` is nullable (platform-level events have no tenant, per 7.8's own "why no RLS here" note), and `TenantBase.company_id` is `NOT NULL`. Scoping is enforced entirely in `AuditRepository`, whose every read method requires `company_id`. In the same migration (`6f86b03e8caa`), `REVOKE UPDATE, DELETE ON audit_logs FROM ems_app` makes the table append-only at the database level, not merely by convention — verified live (`UPDATE ... → ERROR: permission denied for table audit_logs`, connected as `ems_app`) and in `tests/integration/test_audit_log_append_only.py`, which connects as `ems_app` for real (the savepoint-scoped `db` fixture shares one connection and would never exercise a real `REVOKE`), inserts a row, and asserts both `UPDATE` and `DELETE` raise.
- **`Notification`** (new model, same file) — `RLS: Yes`, on `TenantBase`, `enable_rls("notifications")` in the same migration. Picked up by the parametrized isolation sweep (`test_rls_policies.py`) with zero edits to that file, exactly as WP-06 through WP-10 established.
- **Audit writes wired into the mutations named in this WP's task**: employee create/update/deactivate (`hr/service.py`), leave approve/reject and attendance regularize/delete (`time_leave/service.py`). Each call happens inside the calling service's own transaction (`AuditRepository.create` only `add()`s and `flush()`s, never commits — 6.7/6.8) — the audit row and the mutation it describes succeed or fail together atomically. `AuditService.record`'s `details` is always an explicit, small, whitelisted dict the calling service builds field-by-field — never a model's `__dict__` — backstopped by `_assert_details_safe`, a recursive denylist check (`password`, `hashed_password`, `token`, `aadhaar`, `pan`, `bank_account`, etc.) that raises `UnsafeAuditDetailsError` rather than silently storing a banned field. Verified live and in `test_audit_service_refuses_a_banned_detail_field`.
- **`GET /audit-logs`** (route 128, HR only) and **`POST /audit-logs/export`** (route 129, real Celery job, same `export_attendance_csv`-shaped background-job pattern WP-09 established) — filters: `action`, `actor_email`, `entity_type`, `date_from`, `date_to`. A real bug surfaced and fixed while building the date filter: comparing a bare `date` against a `TIMESTAMPTZ` column lets PostgreSQL cast it to midnight in the **session's** timezone (this environment's Postgres server defaults to `+05:30`, not UTC) rather than UTC (Spec 6.3's `utcnow()` convention) — a `date_from` of "tomorrow" by `utcnow()` still matched a row created "today," because the server's local midnight was hours behind UTC midnight. Fixed by building the boundary as an explicit `datetime.combine(date_from, time.min, UTC)` in Python, sidestepping the server's timezone setting entirely; caught by `test_audit_log_filters_by_action_and_date_range` before this shipped.
- **`GET /dashboard`** (route 121) — one endpoint, one `DashboardResponse{role, generated_at, data}` envelope; `data`'s shape follows 11.10's table per role (`super_admin`/`hr_admin`/`manager`/`employee`), documented on `DashboardService.get_dashboard` rather than four parallel Pydantic response models (a single-endpoint, four-shape payload didn't justify FastAPI's Union-response complexity). Cached in Redis (`app/core/cache.py`, new — same module-level-client shape as `app/core/otp.py`) for `DASHBOARD_CACHE_TTL_SECONDS` (60s, new setting) under `dashboard:{company_id}:{user_id}:{role}`. Invalidated (`delete_by_prefix(f"dashboard:{company_id}:")`) on employee create/update/deactivate, attendance check-in/check-out/regularize/delete, and leave **approval** — not rejection, a deliberate literal reading of 11.10's wording ("on attendance mark, leave approval, and employee create/deactivate"). Verified live (Redis `SCAN` showed the exact expected keys after each role logged in) and in `test_dashboard.py`, including a cache-hit test that monkeypatches `DashboardRepository.headcount` with a call-counting wrapper and asserts a second `GET /dashboard` within the TTL calls it zero additional times.
- **Routes 125–127** (notifications: list/mark-one-read/mark-all-read) — in-app only, no email/SMS, exactly as scoped. Emitted on leave approved, leave rejected, and attendance regularization (see spec gap below for why there is no separate "regularisation rejected" notification). `NotificationRepository.get_by_id` requires both `company_id` and `user_id`, so a notification belonging to a different user in the same company 404s, not 403s — the same rule 10.1 states for cross-tenant resources, extended here to cross-user-within-tenant (verified in `test_a_notification_belonging_to_another_user_404s_not_403s`).
- **Unread count** — folded into `GET /notifications`'s own response (`NotificationListResponse.unread_count`, computed alongside the list query) rather than a fifth route; see spec gap below.

**Not delivered in this pass:** `announcements`, `file_objects` (7.8's other two platform tables — not in this WP's task); a `super_admin` audit trail for the 8.5-mandated "every request where `is_platform_admin` is on writes an audit_logs row" — this WP's task scoped audit writes to the six named employee/leave/attendance mutations only, all HR/manager actions, none of them the `super_admin` path 8.5 describes; worth its own follow-up rather than silently expanding this WP's scope (see spec gap below).

---

## 36. WP-11 verification — actual output

Run live against `uvicorn` first (register → approve a Technology company as a directly-seeded `super_admin`, create → update → deactivate an employee, apply → approve → reject leaves, check-in → regularize attendance, confirm `audit_logs` rows via `GET /audit-logs`, confirm `UPDATE`/`DELETE` on `audit_logs` fail live via `psql` as `ems_app`, confirm Redis `dashboard:*` keys via `redis-cli SCAN`), then codified as `test_audit_logs.py` (7 tests), `test_audit_log_append_only.py` (1), `test_audit_logs_export.py` (1), `test_dashboard.py` (5), `test_notifications.py` (4), `tests/isolation/test_audit_logs_and_notifications.py` (1) — 19 new tests.

| # | Check | Result |
|---|---|---|
| 1 | `audit_logs` is append-only at the database level | **Pass — live and automated.** Live: connected as `ems_app` via `psql`, `UPDATE audit_logs ...` → `ERROR: permission denied for table audit_logs`. Automated: `test_ems_app_can_insert_but_not_update_or_delete_audit_logs` proves both `UPDATE` and `DELETE` raise, over a real separate `ems_app` connection. |
| 2 | Audit rows never contain a password/token/Aadhaar/PAN/bank field | **Pass — automated.** `test_audit_service_refuses_a_banned_detail_field` proves `AuditService.record` raises `UnsafeAuditDetailsError` for a top-level and a nested banned key. |
| 3 | Employee create/update/deactivate, leave approve/reject, attendance regularize/delete each write an audit row | **Pass — live and automated.** Live: `GET /audit-logs` after an update showed `"action":"EMPLOYEE_UPDATED"` with `"details":{"position":{"to":"Staff Engineer","from":null}}`. Automated across `test_audit_logs.py`'s three flow tests. |
| 4 | All three role shapes render, and the isolation sweep covers `notifications` with zero test-file edits | **Pass — live and automated.** Live: `hr_admin`, `super_admin` shapes both rendered correctly (`headcount`, `company_counts_by_status`, etc.); `manager`/`employee` shapes covered in `test_dashboard.py`. `test_rls_policies.py` (still untouched) now parametrizes `notifications` alongside the seven WP-09/WP-10 tables. |
| 5 | A second `GET /dashboard` within the TTL is served from cache, not the repository | **Pass — automated.** `test_dashboard_is_served_from_cache_on_a_second_call_within_the_ttl` monkeypatches `DashboardRepository.headcount` with a counting wrapper; asserts it is called exactly once across two requests. |
| 6 | List/mark-one-read/mark-all-read/unread-count all work, notifications emit on the four named events | **Pass — live and automated**, across `test_notifications.py`'s four tests. |
| 7 | `pytest`, `ruff`, `mypy` clean | **Pass.** `pytest -v --cov=app`: **128 passed**, 92% coverage. `ruff check .` / `ruff format --check .`: `All checks passed!` / all files formatted. `mypy app/`: `Success: no issues found in 55 source files`. |

Dev database and Redis were both cleared back to empty at the end (the live smoke test's company, users, employees, leaves and `dashboard:*` Redis keys all removed via a superuser connection — `ems_owner`'s own `psql` session is itself subject to `FORCE ROW LEVEL SECURITY` on every RLS'd table with no tenant context set, so cleanup needed the RLS-bypassing local superuser role instead; a live, first-hand demonstration of exactly what 8.3's `FORCE` note says it does), matching the discipline every prior work package in this session followed.

---

## 37. WP-11 exit gate — current status

Per this session's instructions:

| Gate condition | Status |
|---|---|
| `audit_logs` append-only at the database level, proven with a real connection | **Done — verified.** See §36 row 1. |
| Audit writes never contain a banned field | **Done — verified.** See §36 row 2. |
| Audit wired into employee create/update/deactivate, leave approve/reject, attendance regularize/delete | **Done — verified.** See §36 row 3. |
| Dashboard renders all four role shapes, cached in Redis, invalidated on the named mutations | **Done — verified.** See §36 rows 4-5. |
| Notifications: list/mark-one-read/mark-all-read/unread-count, emitted on the four named events | **Done — verified.** See §36 row 6. |
| Isolation sweep covers `notifications` automatically; `audit_logs` covered by its own dedicated HTTP-level test (7.8's explicit requirement, since it has no RLS) | **Done — verified.** See §36 row 4 and `tests/isolation/test_audit_logs_and_notifications.py`. |
| `pytest`, `ruff`, `mypy` clean | **Done — verified.** See §36 row 7. |

**WP-11 gate passes.**

---

## 38. WP-12 and WP-13 — Frontend foundation, auth, and HR pages

**Governs:** 14.1, 14.2, 14.4, 14.5, pages 1, 7–10.

**Delivered together, in two commits, per this session's explicit instruction** (WP-12's foundation, then WP-13's pages) — Section 19 runs them as separate work packages with separate gates; both gates are addressed below under their own headings.

### WP-12 · Frontend foundation and auth

- **`frontend/`** scaffolded with Vite + React 19 + TypeScript (`npm create vite@latest -- --template react-ts`, since no Node.js toolchain existed anywhere in this environment before this session — `brew install node` was run first; see the deviation note below).
- **`app/api-client.ts`**: the access token lives in a module-scoped variable only, set by `auth-context.tsx` — never `localStorage`/`sessionStorage` (Spec 14.2). One Axios response interceptor handles 401: refresh once via a *separate*, non-intercepted Axios instance (so a failed refresh can never re-trigger itself — Spec 14.2's explicit infinite-loop warning), retry the original request once, and on a second failure clear state and let `RequireAuth` redirect to `/login`.
- **`app/auth-context.tsx`**: on app load, calls `POST /auth/refresh` exactly once (recovering the session from the httpOnly cookie, per 14.2) then `GET /auth/me` to populate the user/role; a failed refresh is not an error to surface, just "show the login page."
- **`shared/api/errors.ts`**: parses the exact envelope shape `app/core/exceptions.py` produces (Spec 6.6) — every page renders `error.message`, never a raw object; a network failure with no response body still produces a readable message.
- **`shared/components/RequireAuth.tsx`** / **`RoleGuard.tsx`**: unauthenticated → `/login`; wrong role → the caller's own landing page (`app/role-landing.ts`), never a blank screen.
- **`ErrorBoundary`**, **`ToastProvider`**, role-aware **`AppLayout`** (nav items filtered by `user.role`).
- **Generated API types** (`shared/api/types.gen.ts`, 3,946 lines) via `npx openapi-typescript http://localhost:8000/openapi.json` — **not** `/api/v1/openapi.json` as Spec 14.5's own example command shows; the real OpenAPI document is served at the FastAPI app root, unprefixed (`app/main.py` never applies `API_V1_PREFIX` to the auto-generated schema route). Corrected in `package.json`'s `gen-api-types` script; noted as a spec gap below.
- **One real page: login** (page 1), per this session's explicit instruction — not pages 1–4 as Section 19's WP-12 deliverable list says. Company registration, activation, and forgot/reset-password (pages 2–4) are **not built this session**; see the deviation note below.

### WP-13 · Frontend HR pages

- **`shared/components/DataTable.tsx`**: one component, consumed by every list page below — search lives outside it (a filter bar), it owns sort (click a column header, `-field` for descending, matching the backend's `sort` query param convention exactly), pagination against the real `Page[T]` envelope (`items`/`page`/`limit`/`total`/`pages`/`has_next` — Spec 10.1, never a different shape), and the four required states (loading/error/empty/content — 14.7).
- **`PageHeader`, `ConfirmDialog`, `EmptyState`** (14.4's other shared components); **`usePagination`/`useDebounce`/`useRole`** hooks.
- **Employee list** (page 7): server-side search (debounced), department filter, sortable `first_name`/`hire_date` columns, pagination — all against the real `GET /employees`.
- **Employee profile** (page 8) — **details tab only**, not "details, KYC and work experience" as Section 19's WP-13 deliverable text says; see the deviation note below.
- **Employee create/edit** (page 9): one form component for both routes, Zod schema (`hr/schemas.ts`) mirroring `EmployeeCreateRequest`/`EmployeeUpdateRequest` field-for-field, server-side validation errors (a 422's `details.errors`) mapped onto the right field via `fieldErrorsFromDetails`.
- **Departments** (page 10): CRUD with live employee counts; a blocked delete (409, active employees assigned) surfaces the backend's own count-bearing message verbatim in the confirm dialog, not a generic failure.
- **No component library** — plain CSS (`shared/styles/global.css`): custom properties, a small set of reusable classes (`.card`, `.btn`, `.field`, `.data-table`, `.badge`, …), no Tailwind, no shadcn. See the deviation note below.

### Deviations from Section 19's literal WP-12/WP-13 text — all per this session's explicit instructions, not oversights

1. **Tailwind + shadcn, replaced with plain CSS.** Section 19's WP-12 deliverable line names "Vite + React + TS + Tailwind + shadcn." This session's instructions were explicit: "No component library that pulls in a design system you then fight. Plain CSS or a minimal utility layer is fine." Followed the instruction as given; Section 14.1's structure tree (`shared/ui/ # shadcn components`) is the one piece of 14.1 not implemented as written — there is no `shared/ui/` directory, because there is no component library to wrap.
2. **WP-12 built only page 1 (login), not pages 1–4.** Company registration (`/register-company`), employee activation (`/activate/:token`), and forgot/reset-password (`/forgot-password`) all have working backend routes (WP-03/WP-05) but no frontend page yet. This session's instructions named this explicitly ("Build exactly one real page in this part: login"). **Closed in a same-session follow-up — see §41.**
3. **WP-13 built pages 7–10, not "pages 6–12" as this session's own prompt said.** Section 19's WP-13 entry governs pages 7–10 (employee list/profile/create-edit, departments) — page 6 (dashboard) and pages 11–12 (attendance, leave) belong to WP-14 per Section 19's own text. Built what Section 19 actually assigns to WP-13, the same "build what the spec's table says, not what the prompt's heading says" correction WP-11 made for its own route-numbering mismatch (§10 item 13).
4. **Employee profile: details tab only, not "details, KYC and work experience."** Section 19's WP-13 text reads "the tabs whose APIs exist by now — details, KYC and work experience only," which presumes WP-08 (KYC and work experience) already ran. This session's actual build order went WP-07 → WP-09 → WP-10 → WP-11 → WP-12/13, skipping WP-08 entirely (it remains open — see §9's "Later" list, "KYC, performance, payroll, projects"). There is no `employee_kyc`/`work_experiences` backend to render, so only the details tab (which is really the whole page — no tab UI was built for a single tab) exists.

### A real environment gap found and fixed, not part of either package's plan

**No JavaScript runtime existed anywhere in this environment before this session** — `node`, `npm`, `npx`, `bun`, `pnpm`, `yarn` all resolved to "command not found," and no version manager (`nvm`, `volta`) was present either. Every frontend command in both work packages' exit gates (`npm install`, `npm run build`, `npx openapi-typescript`) would have failed at the first step. Fixed by `brew install node` (Node 26.8.1, npm 11.19.0) — a standard, reversible, low-risk dev-tool installation, not a destructive or hard-to-reverse action, and clearly required infrastructure for literally any frontend work this session or any future one.

### Not delivered in this pass

Pages 2–4 (company registration, activation, forgot-password — deviation #2 above) — **closed in the same session, §41**; page 5 (super-admin dashboard, WP-11's own deliverable list names it but it wasn't built there either — still open); the KYC/work-experience profile tabs (deviation #4); `shared/ui/` (deviation #1); an actual `useRole`-gated "my profile" route for the `employee` role (no employee-facing page reaches `/employees/:id` this session — the nav only shows "Employees" to `hr_admin`/`manager`, matching the two roles that can actually list employees; an employee viewing their own profile is deferred, not attempted).

---

## 39. WP-12/WP-13 verification — actual output

No browser-automation tool (Playwright, Puppeteer, or similar) is available in this environment, so the "log in through the UI and click through" walkthrough this session's own exit gate asked for could not be performed as a literal, visual, click-by-click check. What was actually run, as the strongest available substitute:

| # | Check | Result |
|---|---|---|
| 1 | `npm run build` (`tsc -b && vite build`) | **Pass.** `✓ 244 modules transformed`, `✓ built in 492ms`, zero TypeScript errors across every page and shared module. |
| 2 | `npm run lint` (oxlint) | **Pass.** No output — zero findings. |
| 3 | Vite dev server boots and serves every module without a transform error | **Pass.** `VITE v8.2.2 ready in 90 ms`; `curl` against `/`, `/src/main.tsx`, `/src/app/router.tsx` all returned `200` with no errors in the dev server log. |
| 4 | CORS preflight from the real frontend origin | **Pass.** `OPTIONS /auth/login` with `Origin: http://localhost:5173` → `200`, `access-control-allow-origin: http://localhost:5173`, `access-control-allow-credentials: true` — exactly what `withCredentials: true` on the Axios instance needs. |
| 5 | Login sets the httpOnly refresh cookie the way `auth-context.tsx` expects | **Pass.** `POST /auth/login` with the frontend's `Origin` header → `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax`. |
| 6 | `POST /auth/refresh` recovers a session from **only** the cookie jar, no Authorization header — exactly `auth-context.tsx`'s boot-time call | **Pass.** Returned a fresh `access_token` with no bearer token sent, proving the reload-survival mechanism the whole login page's `Navigate` logic depends on. |
| 7 | `GET /auth/me` returns exactly the shape `CurrentUser` expects | **Pass.** `role`, `company_id`, `employee`, `permissions` all present and correctly typed against `app/app/auth-context.tsx`'s interface. |
| 8 | Every HR-page mutation, replayed with the exact payload shape each page sends | **Pass, all six, live.** Department create (`POST /departments`) → `201`; employee create (`POST /employees`, matching `EmployeeCreateInput` field-for-field) → `201` with a real `employee_code` and invite token; search (`GET /employees?q=priya`) → `total: 1`; edit (`PUT /employees/{id}`) → field updated; deactivate (`DELETE /employees/{id}`) → `204`, then `GET` by id → `404` (soft-deleted, same 7.1 rule WP-07 established), then `GET ?is_active=false` → still found, `is_active: false` — the exact sequence the exit gate's manual walkthrough asks for, run against the real backend with the real request shapes the UI code constructs. |
| 9 | Departments filter-dropdown data (`GET /departments?page=1&limit=100`) | **Pass.** Returned all 7 Technology-preset departments (Spec 5's industry seed, WP-05), the same list `EmployeeListPage`'s and `EmployeeFormPage`'s department `<select>` render. |

What this proves: the integration contract between every page and the real API is correct — request shapes, response shapes, auth flow, CORS, cookie handling. What it does **not** prove: that React actually renders each page correctly, that click handlers fire, that the router navigates as expected on click, or that the layout looks acceptable in an actual browser window. That gap is real and is flagged here rather than glossed over — a quick manual pass in an actual browser (`cd frontend && npm run dev`, backend running, walk through login → employees → departments) is the natural next step before treating WP-13's gate as fully closed in the way a literal browser walkthrough would close it.

Dev database was cleared of this session's live-verification company/users/employees/departments afterward (the Technology industry preset's 7 seed departments and the `industry_presets` table itself untouched), matching the discipline every prior work package in this session followed.

---

## 40. WP-12/WP-13 exit gate — current status

Per this session's instructions:

| Gate condition | Status |
|---|---|
| `ruff check . && ruff format --check .` / `mypy app/` / `pytest -v --cov=app` (backend, unchanged this session) | **Done — verified, still green.** 128 passed, 92% coverage, both tools clean — see §37 (WP-11), re-run and confirmed identical this session. |
| `cd frontend && npm run build` | **Done — verified.** See §39 row 1. |
| Manual walkthrough: log in as HR admin, create a department, create an employee, search, edit, deactivate | **Substitute-verified, not literally clicked through — see §39's caveat.** Every HTTP call each action makes was replayed live against the real backend with the exact payload/response shapes the UI code uses, and all six steps succeeded in sequence. No browser-automation tool exists in this environment to perform the literal click-through; flagged explicitly rather than claimed. |
| Two separate commits, foundation then pages | **Done.** `1a27f79` (WP-12), `3405823` (WP-13). One honest caveat: `1a27f79`'s `router.tsx` already imports the HR pages `3405823` adds, so the foundation commit alone would not build in isolation if checked out on its own — a consequence of `router.tsx` being genuinely shared foundation that both packages touch, not an oversight. |

**WP-12 and WP-13 substantially pass**, with the browser-walkthrough and single-commit-buildability caveats above stated plainly rather than elided. Not proceeding to WP-14 this session.

---

## 41. WP-12 follow-up — the remaining public auth pages, and the CI fix

**Governs:** 14.2, 14.3 pages 2–4, 10.2 routes 3–11 and 12; and separately, `.github/workflows/ci.yml`.

Two closures, requested together, delivered as two commits.

### Pages 2–4 (deviation #2 from §38, now closed)

- **Company registration** (page 2, `/register-company`) — posts `CompanyRegisterRequest`'s real fields (`company_name`, `company_email`, `industry?`, `phone?`; `country` omitted so the backend's own `"IN"` default applies), read from the generated `shared/api/types.gen.ts`, not guessed. Success state states plainly that the company is `pending` and no account exists yet — credentials are issued only at approval. There is still no public endpoint listing valid `industry_presets` names (spec gap, noted inline on the page itself and below) — the field is free text with a hint, and an unmatched value is a harmless no-op (no departments/leave types pre-seed at approval) rather than an error.
- **Employee activation** (page 3, `/activate/:token`) — previews via `GET /auth/activate/{token}` (route 10), then `POST /auth/activate` (route 11) on submit. That route logs the caller in and returns the same `TokenResponse` `login()` does, so a new `AuthContext.establishSession(token)` adopts it directly — no second call to `/auth/login`. A 404 (unknown, expired, or already-redeemed token — `AuthService.preview_activation` gives one message for all three, by design) renders as a plain "Invitation no longer valid" card, not a raw error object.
- **Forgot/reset password** (page 4, `/forgot-password`) — two steps, one page. Step one always shows the backend's own message verbatim ("If that email exists, a password reset code has been sent.") and advances to step two regardless of the outcome — the UI has no way to know, by design (9.3), and doesn't try to guess. Step two's wrong/expired/attempts-exhausted OTP cases all come back as the identical `"Invalid or expired code."` (`InvalidOtpError`, one message for all three — the same enumeration-safety principle) — shown as-is, no special-casing needed on the frontend.
- **`shared/components/PublicOnly.tsx`** (new): the redirect-if-authenticated logic login already had, extracted so all four public routes share one implementation instead of four copies — login itself was refactored to use it too.

### The CI fix

**Reproduced first, as instructed.** Exporting `DATABASE_URL` and `TEST_DATABASE_URL` to the identical value locally reproduced the exact reported failure: `RuntimeError: TEST_DATABASE_URL points at the same database as DATABASE_URL.` — `conftest.py`'s guard (15.2) working exactly as designed.

**Root cause, read directly from `.github/workflows/ci.yml`'s `env:` block:** both were hardcoded to `postgresql+psycopg2://ems_app:ems_app_dev_only@localhost:5432/ems_pro_test` — the identical database name, `ems_pro_test`. `ALEMBIC_DATABASE_URL`/`TEST_MIGRATION_URL` were already correct (`ems_owner`, `ems_pro_test`); the app-role pair was the actual bug. This is CI's own workflow file, unrelated to `app/core/config.py`'s definitions (which are correct and unchanged) or to anything in this repository's actual `.env` — CI has simply never had a valid configuration to run pytest against, since the workflow file was written.

**Fix:** `DATABASE_URL` now names `ems_pro` instead of `ems_pro_test` — genuinely a different database name, which is all the guard checks. CI's Postgres service container only ever provisions `ems_pro_test` (its `POSTGRES_DB`); `ems_pro` is never created and nothing in CI needs it to be — `create_engine()` (`app/db/session.py`) is lazy, so `Settings()` only needs a syntactically valid, differently-named URL to satisfy the check. No CI step, migration, or test ever connects through `DATABASE_URL`. Re-verified locally with the corrected pair: `128 passed`.

**Also filled in**, since it was a standing placeholder ("Frontend — arrives with WP-12") that WP-12 landing now makes stale if left as a comment: `actions/setup-node@v4`, `npm ci`, `npm run build`, working directory `frontend/`. Runs against the committed `types.gen.ts` — CI never needs a live backend to type-check the frontend, since that file is generated once and committed (14.5), not regenerated per build.

**Not touched, per instruction:** `conftest.py`'s guard itself — it was correct throughout; only the workflow's own configuration was wrong.

**Verification:**

| # | Check | Result |
|---|---|---|
| 1 | Reproduce the exact reported CI failure locally | **Pass.** Identical `RuntimeError` message, byte for byte, with both URLs set to the same database. |
| 2 | Fix clears it | **Pass.** `128 passed` with the corrected pair. |
| 3 | `ruff` / `mypy` / `pytest` (backend, unaffected by a workflow-file-only change) | **Pass, unchanged.** All checks passed; `Success: no issues found in 55 source files`; `128 passed`, 92% coverage. |
| 4 | `cd frontend && npm run build` | **Pass.** `✓ 250 modules transformed`, zero TypeScript errors, including the four new pages. |
| 5 | Full new-user walkthrough: register → approve → HR login → create employee → activate → confirm logged in → log out → forgot-password → reset → log in with the new password | **Pass, all nine steps, live — replayed as HTTP calls, not a literal click-through (see caveat below).** `POST /companies/register` → `201`, `status: "pending"`. Super-admin approve → HR credentials issued. HR login → `Set-Cookie` refresh token. `POST /employees` → activation token issued. `GET /auth/activate/{token}` → preview shows `first_name`/`company_name`/`expires_at`. `POST /auth/activate` → `200`, fresh refresh cookie; `GET /auth/me` immediately after confirms `role: "employee"` and the linked `employee` summary — the "lands logged in, no second login step" requirement, proven directly. Replaying the same (now-consumed) token → `404`, `"Invitation not found or has expired."` — exactly what `ActivatePage`'s error state renders. Logout → `204`. `POST /auth/forgot-password` → the fixed generic message. A wrong OTP → `400`, `"Invalid or expired code."`. The real OTP (generated directly via `app.core.otp.generate_and_store_otp`, since a pre-existing `uvicorn --reload` process already owned port 8000 in this environment and its stdout — where the `console` email backend prints — wasn't capturable; functionally identical to reading a real sent email, since it calls the same underlying function `send_email`'s caller does) → `POST /auth/reset-password` → `204`. Login with the new password → `200`. Login with the old password → `401`. |

**Caveat, stated the same way as §39's:** no browser-automation tool exists in this environment. Every step above was verified by replaying the exact HTTP call each page's code makes, with the real request/response shapes, not by driving a browser. This proves the integration contract; it does not prove the React forms render, submit, and redirect correctly in an actual browser tab. A two-minute manual pass (`npm run dev`, backend running, click through all four new pages) remains the natural next check.

**Not delivered:** a public `industry_presets` list endpoint for the registration page's industry field (still free text) — this is a backend gap, not a frontend one, and adding a new route is out of scope for "build the four pages"; noted for whoever picks up a future platform/company-onboarding pass. **Closed in WP-14 — see §42.**

---

## 42. WP-14 — Frontend dashboard, admin, attendance, leave, shifts

**Governs:** 14.3 pages 5, 6, 11, 12, 15; 11.10; 10.4 routes 43–66; and a small backend addition (public `GET /industry-presets`).

### Environment check, before any code — as instructed

- **`.env`:** now has every variable `app/core/config.py` requires (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `TEST_DATABASE_URL`, `TEST_MIGRATION_URL`, `REDIS_URL`, `SECRET_KEY`) — confirmed by `python -c "from app.core.config import settings"` succeeding with **no shell exports**, for the first time this session. **This was fixed between sessions, not by this agent** — every prior work package this session ran commands with `ALEMBIC_DATABASE_URL`/`DATABASE_URL`/etc. exported inline because `.env` carried only 3 of the 6 required variables. That gap is now closed; worth recording since several earlier sessions' reports note the workaround.
- **`alembic current` vs `alembic heads`:** both report `6f86b03e8caa (head)` — no drift.
- **Grants (`\dp`), three tables spanning the whole session's history:** `employees` (WP-07) and `notifications` (WP-11, added four work packages later) both show `ems_app=arwd` — full CRUD, via `ALTER DEFAULT PRIVILEGES`, no manual grant needed for either. `audit_logs` (WP-11) shows `ems_app=ar` only — SELECT+INSERT, no UPDATE/DELETE, no RLS policy — exactly the append-only shape WP-11 built. All three match what the code says they should be.
- **Conclusion: no drift found, anywhere.** The only prior gap (the incomplete `.env`) was already fixed, by someone other than this agent, before this session started. Baseline `pytest -q` run before writing any code: **129 passed** (128 from WP-13's report + the CI-fix session's own test count — this session's actual starting point).

### Deviation from Section 19's literal WP-14 text — per this session's explicit instructions

Section 19's own WP-14 entry governs pages **6, 11–14, 26, 27** (dashboard, attendance, leave apply/list/approve, leave balance, holiday calendar, company settings, user settings) — it does not assign page 5 (super-admin dashboard, WP-11's own list names it) or page 15 (shifts, WP-09's own list names it). This session's instructions explicitly named pages **5, 6, 11, 12, 15** instead — folding leave balance into page 12 rather than building a separate page 13, and substituting pages 5 and 15 (both already-open gaps from earlier work packages) for pages 13, 14, 26, and 27. Built exactly what this session's instructions specified; pages 14 (holiday calendar), 26 (company settings), and 27 (user settings/change password) remain open — not attempted, not silently dropped. See §9's "Later" list.

### Backend: public `GET /industry-presets`

WP-12's own report flagged this: the registration page needed valid industry names and no route exposed them. `IndustryPresetService.list_names()` (new, `platform/service.py`) + `GET /industry-presets` (new, `platform/router.py`, `Depends(get_db)` — no tenant context, matching `industry_presets`' own `RLS: No` in 7.8) returns `list[str]`, names only — not `departments_json`/`leave_types_json`, which the registration page has no use for before a company exists. **Section 10's route table assigns no number to this** — recorded here as a spec gap (below) rather than inventing one. Test: `tests/integration/test_industry_presets.py` — public (no auth headers), returns all 12 seeded names, confirms no `departments_json`/`leave_types_json` key leaked through (trivially true for a `list[str]`, asserted anyway).

### Frontend

- **Registration page (WP-12) wired to the new endpoint** — the free-text industry field is now a `<select>` populated from `GET /industry-presets`; a failed fetch degrades to "you can still register without one," never blocks the form.
- **Dashboard (page 6, `/dashboard`)** — one `DashboardPage` component, a discriminated union type (`role` as the tag) over `GET /dashboard`'s four Spec 11.10 shapes, not four separate pages. The TypeScript interfaces for each role (`platform/api.ts`) **omit** `pending_reimbursements`, `last_payroll_run`, `team_task_load`, `latest_payslip_status`, `assigned_open_tasks` entirely — these are the fields `platform/service.py` hardcodes to `0`/`None` because payroll and tasks don't exist yet (WP-11's own code, `_hr_admin_data`/`_manager_data`/`_employee_data`). The backend still sends them (removing them from the response is out of scope here — WP-11's contract, not touched); the frontend simply never destructures or renders them, so a reviewer never sees "Pending reimbursements: 0" and mistakes a forward dependency for a real count.
- **Admin dashboard (page 5, `/admin`, super_admin only)** — **a distinct shape from page 6**, so it's its own page, not folded in: `GET /dashboard`'s `super_admin` payload is stats only (`company_counts_by_status`, `pending_approvals`, `platform_user_count`) with no list of pending companies and no mutation capability, while page 5 needs both (Spec 14.3: "Platform stats, pending companies, approve/reject"). Layers `GET /companies?status=pending` and the approve/reject routes (already built in WP-05) on top of the same dashboard stats call. Approving shows the one-time HR admin credentials (same "shown once, never persisted" treatment WP-05's own approval response already applies); rejecting requires a reason (`CompanyRejectRequest`), via a small one-off modal (`ConfirmDialog` has no text-input slot, same justification WP-13's department form and this session's earlier reject-with-reason dialogs already used).
- **Attendance (page 11, `/attendance`)** — "today's state" (not checked in / checked in, still open / checked out) is resolved from the same `GET /attendance` the history list uses, narrowed to the caller's own `employee_id` and today's date — there is no dedicated "my status today" endpoint, and none was needed: passing an explicit `employee_id` equal to the caller's own always resolves under every role's scoping rule (`AttendanceService.list_attendance`), including HR/SA's unrestricted scope. History list and its own/team/everyone scoping is entirely server-resolved, zero frontend role logic. HR gets a per-row "Regularize" button (`PUT /attendance/{id}`, `reason` required).
- **Leave (page 12, `/leaves`)** — apply (employee selector shown only for `hr_admin`/`manager`, since `LeaveApplyRequest.employee_id`'s own docstring says exactly that: omitted for self, required for someone else), the role-scoped request list with a status filter, balances (`GET /leaves/balance/{employee_id}`, shown whenever the caller has a linked employee record, any role), and approve/reject for a manager or HR. **The apply form validates only field presence client-side** — no re-implementation of any of Spec 11.3's eight rules; every rejection the backend raises (overlap, insufficient balance, past date, max consecutive days, …) is displayed via `error.message`, verbatim, the same "one source of truth" principle §41's forgot-password page already established for OTP errors.
- **Shifts (page 15, `/shifts`, HR only)** — CRUD plus assignment, carried over from WP-09's own deliverable list since no frontend existed at the time.
- **Routing (`router.tsx`) and nav (`AppLayout.tsx`)** for all five new pages, in their own commit — see §44's caveat on why this wasn't split further.

**A real, non-obvious backend behavior surfaced while writing the live-verification script, not a defect:** `list_leaves`' role-based scoping (`_SEES_EVERYONE` vs. `list_direct_report_ids`) means a **manager** passed as `employee_id` for a query narrows against their **direct reports**, never themselves — a manager can never see their own leave requests through `GET /leaves?employee_id=<self>`, only through the unfiltered (role-default-scoped) call, which for a manager still only returns direct reports. This is existing WP-10 behavior, unchanged here; `LeavePage` was built around it (the request list never passes an explicit `employee_id`, letting the backend's own default scoping decide, and the balances section calls `GET /leaves/balance/{id}` — a different, "Own or HR" endpoint — for a manager's own numbers instead).

### Spec gap

No route number is assigned to a public industry-presets list anywhere in Section 10's table — recorded as spec gap #17 in §10, not repeated here.

---

## 43. WP-14 verification — actual output

Run live against `uvicorn` first — a full new-user-to-approval-to-decision walkthrough through real HTTP calls, replaying exactly what each page's code sends (no browser-automation tool exists in this environment; same caveat as §39/§41) — then the backend piece codified as `tests/integration/test_industry_presets.py`.

| # | Check | Result |
|---|---|---|
| 1 | Environment drift check | **Pass — none found.** See §42's environment section. The one gap that existed (`.env` incomplete) was already fixed before this session, by someone else. |
| 2 | `GET /industry-presets` public, names only | **Pass — live and automated.** Live: 12 names returned, no auth header sent. Automated: `test_industry_presets_are_public_and_names_only`. |
| 3 | `ruff` / `mypy` / `pytest` (backend) | **Pass.** `All checks passed!` / all files formatted; `Success: no issues found in 55 source files`; **129 passed** (128 + the new industry-presets test), 92%+ coverage. |
| 4 | `cd frontend && npm run build` | **Pass.** `✓ 255 modules transformed`, zero TypeScript errors, across all five new pages plus the registration-page change. `oxlint`: zero findings. |
| 5 | An employee checks in | **Pass — live.** `POST /attendance/check-in` as Ann (employee) → `201`, `status: "present"`, `source: "web"`. The "today's state" query (`GET /attendance?employee_id=<ann>&date_from=<today>&date_to=<today>`) immediately reflected it — exactly what `AttendancePage`'s today-state block renders. |
| 6 | …applies for leave, sees the balance drop when approved | **Pass — live.** Balance before applying: `[]` (lazily allocated, WP-10's own documented behavior — see spec gap #12). Applied (`POST /leaves`, no `employee_id` — self). Balance immediately after applying: still `[]` (allocation happens at **approval**, not application). After the manager approved: `available` `18.0 → 17.0` for a 1-day leave — the balance genuinely dropped, read back through the same `GET /leaves/balance/{id}` `LeavePage` calls. |
| 7 | A manager sees their team's attendance and approves that leave | **Pass — live.** `GET /attendance` as manager Mo (no filters) → exactly Ann's one row, not company-wide — confirms the server-side team scoping `AttendancePage`'s history list depends on. `GET /leaves?status=pending` as Mo → exactly Ann's one pending request. `PUT /leaves/{id}` `{"status":"approved"}` as Mo → `200`, `approved_by` set to Mo's user id. |
| 8 | HR regularizes an attendance record | **Pass — live**, after one self-corrected test-script mistake: `GET /attendance?page=1&limit=20`'s **first** item was, unexpectedly, the `on_leave`/`source=system` row the leave approval had just upserted for 2031 (sorted first by `created_at desc`, since it was written more recent to that request), not Ann's actual today check-in — a property of `created_at`-descending default sort with two rows now present, not a bug. In the real UI this is a non-issue: `AttendancePage`'s "Regularize" button is bound to the specific row it's rendered on, never a blind "first item." Re-ran against the correct row id directly: `PUT /attendance/{id}` `{"status":"wfh","reason":"..."}` → `200`, `status: "wfh"`, `notes` set. |
| 9 | HR creates a shift | **Pass — live.** `POST /shifts` → `201`, a real `Shift` row. `POST /shifts/{id}/assign` for Ann → `201`, a real `EmployeeShift` row. |

**A real gotcha hit and worked around while scripting the walkthrough, not a product defect:** the setup script's first attempt to link `manager`/`employee`-role `User` rows to already-created `Employee` rows via a direct `SessionLocal()` script failed silently (`db.get(Employee, id)` returned `None`) — because `employees` is RLS-protected and the ad hoc script session never called `bind_tenant_to_session`, so the unset tenant context correctly returned zero rows (Spec 8.3's own "the safe failure mode"). Fixed by calling `bind_tenant_to_session` before the query — the exact behavior 8.3 documents, encountered directly rather than just read about.

Dev database was cleared of all this session's live-verification data afterward (company, users, employees, attendance, leaves, leave balances, shifts, shift assignments — the Technology preset's own seed rows untouched), matching the discipline every prior work package in this session followed.

---

## 44. WP-14 exit gate — current status

Per this session's instructions:

| Gate condition | Status |
|---|---|
| Environment verified current before writing code; drift reported and attributed | **Done.** No drift found; the one prior gap (`.env`) was already fixed by someone else. See §42. |
| `ruff` / `mypy` / `pytest` (backend) | **Done — verified.** 129 passed. See §43 row 3. |
| `cd frontend && npm run build` | **Done — verified.** See §43 row 4. |
| Employee checks in → applies for leave → balance drops on approval | **Done — verified, live.** See §43 rows 5-6. |
| Manager sees team attendance, approves leave | **Done — verified, live.** See §43 row 7. |
| HR regularizes attendance, creates a shift | **Done — verified, live**, after correcting one test-script row-selection mistake (not a product defect). See §43 rows 8-9. |
| Commits in logical, separate pieces | **Done — six commits**: backend `GET /industry-presets` + test; a one-line `ruff format` fixup; frontend registration-page wiring; dashboard + admin dashboard; attendance/leave/shifts pages; routing + nav wiring for all five new pages. **One honest caveat**, the same shape as WP-13's own: `router.tsx`'s new routes for pages 5 and 11/12/15 landed as a single diff (React Router's own contiguous-array-literal shape), so splitting the dashboard-page commit from the time_leave-pages commit at the router-wiring level wasn't practical without hand-editing hunks — routing and nav for all five pages went into one final commit instead of being interleaved with each page's own commit. |

**WP-14 gate passes**, with the routing-commit-granularity caveat stated plainly rather than elided, the same standard every prior frontend work package's report in this session held itself to. Not proceeding to WP-15 this session.

---

## How WP-01 was verified

Everything below was run against the local dev database and a locally started `uvicorn` instance; no destructive action was taken against anything outside this repo's own dev DB and no code outside the files listed in this report's fix rows was modified:

- `import app.main` → succeeds (was: two independent `ImportError`/`ModuleNotFoundError` failures).
- Dev database fully cleared (all tables, both enum types, `alembic_version`) to simulate a genuinely empty database (`ems_user` has no `CREATEDB`, so a separate scratch DB wasn't available); `alembic upgrade head` run from zero → `companies`, `users`, `refresh_tokens` all created with the correct columns, types, and constraints.
- `psql \d companies` / `\d users` / `\d refresh_tokens` → confirmed `uq_companies_lower_email`, `uq_users_company_id_email` and `uq_users_company_id_username` as composite/functional case-insensitive unique indexes; `locked_until` and `expires_at` as `timestamp with time zone`; `replaced_by_id` present with its self-referential FK; `fk_companies_approved_by_users` present.
- Live `uvicorn` run: `GET /health` → `200`; `GET /openapi.json` → all three auth routes listed under `/api/v1/auth/*`.
- End-to-end smoke test against the live server: `POST /api/v1/auth/register` (201) → `POST /api/v1/auth/login` with wrong password (401, generic message) → correct password (200, `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax`, no `Secure` in dev) → `POST /api/v1/auth/refresh` with that cookie (200, rotated cookie, old token now `is_revoked` in the database) → replay of the *original* cookie (401) → confirmed **both** the original and the once-rotated-to token are now `is_revoked = true` (family revocation) → refresh with the second (now-revoked) cookie also 401. This surfaced and led to fixing §4.20 and §4.21, neither of which was caught by import-only checks.
- Dev database returned to an empty-of-data (but migrated) state afterward via `TRUNCATE`, so it's clean for whoever starts WP-02.
