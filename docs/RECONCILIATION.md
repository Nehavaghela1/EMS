# Reconciliation Report

**Governs:** Section 20 of `docs/EMS_PRO_DEV_SPEC.md` (in full). Originally WP-01's output; kept current across later work packages per Section 21's table ("WP-01 output, kept current").
**Method:** Every file under `app/` and `alembic/` was read in full and compared against the spec section that governs it, using the Section 20.2 checklist. Where the checklist implied a runnable check (does the app start, does `alembic upgrade head` actually create tables, is a package importable), that check was executed against the local dev database — read-only at audit time; the blocking items were then actually applied (this revision of the report) and re-verified the same way. See "How this was verified" at the end.

**Status: WP-01's 14 blocking items are fixed and verified. WP-02 (foundation, config, errors, logging, role split) — §12–§14. WP-04 (multi-tenancy, RLS, the isolation suite, rate limiting) — §15–§17. WP-05 (company registration and approval workflow) — §18–§20. WP-06 (departments) — §21–§22. WP-07 (employees) — §23–§25. All delivered and verified. WP-03 is deliberately skipped for now (per instruction); routes 27–30 (resignation, full-and-final) belong to WP-27; the employee frontend pages are WP-13. Not proceeding further this session.**

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
| 2.6 | `app/modules/identity/service.py` — `register_company` | Route 12 (`POST /companies/register`): company self-registration → `status = pending`. The HR admin user is created only at approval (route 15), in one transaction with seeding `company_settings`, departments and leave types (10.2, 6.7). | Was: set `status = active` immediately and created an already-active `hr_admin` user from a client-supplied password, with no approval step | **Closed in WP-05.** | `POST /companies/register` (moved off `/auth/register`, onto its own `companies_router`) now does exactly the spec's route 12: creates the company with `status = pending` and **no user at all**. `POST /companies/{id}/approve` (route 15, SA-only) does the rest — seeds `company_settings`, applies the company's industry preset to `departments` (WP-06 extended this once that table existed), and creates the HR admin — all in one transaction, verified live and in an automated test (§18) by planting a conflicting `company_settings` row and confirming the whole approval rolls back, company left `pending`. Leave-type seeding is still deferred to WP-10 (the table doesn't exist). |

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

## 9. Everything correctly not built yet ("Later") — updated after WP-06

Delivered by WP-02: `pyproject.toml`/ruff/mypy config, `bootstrap_roles.sql` and the `ems_owner`/`ems_app` role split, `app/core/time.py`/`exceptions.py`/`logging.py`/`middleware.py`, `CORS_ORIGINS`/lockout settings/security headers, `docker-compose.yml`'s Postgres+Redis definition, `.github/workflows/ci.yml`, `.env.example`, the `.gitignore` fix (§12–§14).

Delivered by WP-04: `app/db/rls.py` (`enable_rls`, `set_tenant_context`, `bind_tenant_to_session`, the `after_begin` listener), `app/core/dependencies.py` (`get_current_user`, `get_tenant_db` — pulled forward from WP-03's list since WP-04's own Section 19 text requires them), `company_settings` (the first RLS'd table), `tests/conftest.py` (savepoint fixture, `company_a`/`company_b`, `client`, auto-provisioning `ems_pro_test`), `tests/isolation/` (the parametrized sweep plus `company_settings`-specific tests), rate limiting on `/auth/login` (§15–§17).

Delivered by WP-05: `industry_presets` (seed + repository), the real `pending → active/rejected` approval workflow (one transaction: `company_settings` + departments-from-preset + HR admin), `GET`/`PUT /companies/me`, `GET /companies`, `GET /companies/{id}`, `app/core/pagination.py` (pulled forward — needed for the company list envelope), `app/core/dependencies.py::require_role` (pulled forward for the first time SA/HR-only routes existed) (§18–§20).

Delivered by WP-06: `departments` (model, migration + RLS, full CRUD, `tests/isolation/test_departments.py`) — automatically covered by the parametrized sweep with no test file changes required, and the first route to close WP-04's "proven through the API" caveat (§21–§22).

Delivered by WP-07: `employees` (model, migration + RLS, full CRUD with search/filter/sort/pagination via the shared `app/core/pagination.py` helper, concurrency-safe `employee_code` generation, soft deactivate, invite-token generation, manager scoping on list) — plus the two WP-06 gaps this closed (live department employee counts, 409-blocked delete) and a genuine bug fix in the shared pagination helper (`resolve_sort` was raising a 422, not the spec's 400) (§23–§25).

Still correctly deferred:

- `app/core/encryption.py` (WP-08)
- `app/workers/celery_app.py`, `app/workers/tasks/` (WP-09)
- `Dockerfile` content, `README.md` content (WP-15)
- `frontend/` contents beyond the empty `src/` scaffold (WP-12)
- Leave-type seeding from the industry preset (`leave_types_json` is populated and seeded now, but the `leave_types` table itself doesn't exist until WP-10 — nothing consumes it yet)
- `POST /auth/activate` / `GET /auth/activate/{token}` (routes 10-11, WP-03, deliberately skipped this session) — `employees.activation_token_hash`/`activation_expires_at` are generated and stored correctly at create/resend-invite (WP-07), but nothing can redeem them yet. See spec gap #6 below.
- Routes 27-30 (resignation, full-and-final) — WP-27. The `employees` table already carries `resignation_status`/`resignation_date`/`last_working_date`/`notice_waived`/`notice_recovery_days` (created in WP-07's migration, per the spec's own column-for-column table), but no route in this session reads or writes them.
- HR-admin credential delivery at approval, and the employee invite-token hand-off in the `POST /employees`/`resend-invite` response, are both interim MVP substitutes (a secret returned once in the response body, never logged) — WP-26 replaces both with real email delivery via Celery + SendGrid once that infrastructure exists (§19, §23)
- Rehash-on-login wiring for `needs_rehash`, routes 3–9 (logout, logout-all, me, change-password, forgot/reset password, check-username) — WP-03, deliberately skipped this session per instruction
- Actual Sentry SDK initialization (WP-02 added the `SENTRY_DSN` setting; wiring `sentry_sdk.init(...)` is still not done)
- IP extraction behind a trusted proxy for rate limiting (9.5's caveat) — `slowapi`'s default direct-peer extraction is used; revisit when a reverse proxy is actually introduced
- KYC, attendance, leave, performance, payroll, projects, platform (audit logs, announcements, file uploads, search) — everything from WP-08 onward

---

## 10. Spec gaps

1. **~~Case-insensitive uniqueness on `users.email`~~ — RESOLVED.** Section 7.2 now explicitly specifies `(company_id, lower(email))` and `(company_id, lower(username))`, consistent with `companies.email`. Implemented in `models.py` and verified in the database (§4.6).
2. **~~Where `email-validator` is declared~~ — RESOLVED.** Section 3.1's stack table now names `email-validator` (or `pydantic[email]`) explicitly. Added to `requirements.txt`.
3. **New: a fourth pre-authentication-shaped repository method.** Section 7.2 names exactly three lookups exempt from requiring `company_id` (`find_active_by_email`, `get_by_activation_token`, `get_for_password_reset`). Implementing `refresh()`'s reuse-detection required a fourth: loading the `User` behind a refresh token, where — exactly as at login — there is no verified `company_id` yet. `get_by_id_for_token_refresh` was added, matching the same justification the spec gives for the other three (unreachable without the corresponding secret — here, a hashed, unexpired refresh token). This is implemented and documented in the code, not blocked on a spec answer, but it's worth Section 7.2 either naming it as a fourth exception or folding refresh-token lookups under a reworded version of the existing three, so the list stays authoritative.
4. **New: what a `super_admin` account's own `company_id` refers to.** `users.company_id` is `NOT NULL` for every role (7.2) — including `super_admin`, which is platform-wide by definition (1.3) and, per 8.5, only ever created by direct database action, never a route. The spec doesn't say what company a super_admin's own row should point at. This project's fixtures and manual test setup use an ordinary company row created for the purpose (e.g. "Platform Ops") — harmless in practice, since `is_platform_admin=True` bypasses RLS entirely regardless of what `company_id` is set to (8.3's policy `OR` clause), but worth Section 7.2 or 8.5 naming the convention explicitly (a real "platform" company seeded once, vs. any company being acceptable) so every future seed script agrees.
5. **New: industry names in the `industry_presets` seed are this project's own choice, not spec-verified.** Section 7.8 specifies the table's shape (`industry_name`, `departments_json`, `leave_types_json`) and says "seeded once with 12 industries," but not which 12 or what departments/leave types belong to each. The 12 chosen here (Technology, Manufacturing, Healthcare, Retail, Banking & Financial Services, Education, Hospitality, Construction, Real Estate, Logistics & Transportation, Media & Entertainment, Non-Profit) and their department lists are a structurally reasonable starting point — not verified against any real company's org chart, the same caveat Section 0.3 already applies to the statutory payroll figures. Worth a product decision before this seeds a real customer's departments.
6. **New: the access-token `employee_id` claim (9.2) was not added.** 9.2's worked example shows access tokens carrying `"employee_id": "<employee_uuid_or_null>"`, and 10.1's access-key table defines `Own`/`Mgr` as "a service check against `current_user.employee_id`" — implying the claim is how a request resolves "which employee is this caller." Adding it would mean changing `AuthService.login`/`AuthService.refresh`'s token-minting contract (both would need to look up the caller's `Employee` row before minting), touching the identity module's core, already-tested token shape from outside WP-07's scope. Instead, `EmployeeRepository.get_by_user_id(company_id, user_id)` resolves the same fact via one extra indexed query per `Own`/`Mgr`-scoped request (routes 19, 21, 22, 23) — functionally and security-equivalent, just not read from the token. Revisit if profiling ever shows the extra query matters; until then this is a deliberate, documented substitution, not an oversight.
7. **New: "contact fields" (route 23) is not itemized by the spec.** 10.3 route 23 says "employees may edit only contact fields; department, level, manager and dates are HR-only" without naming the fields. This project treats `last_name`, `personal_email` and `phone` as the contact fields an `Own` caller may set, and treats `email` (the work email) as HR-only alongside department/level/manager/dates/employment_type — reasoned as: `email` is the administrative identifier used for login and company communication, closer in kind to the HR-controlled fields than to personal contact details. `CONTACT_FIELDS` in `app/modules/hr/service.py` is the single place this list lives if it needs revisiting.
8. **Bug found and fixed during WP-07, not part of the original audit:** `app/core/pagination.py::resolve_sort` — used by every list endpoint's `sort` parameter (companies, departments, and now employees) — raised the app's `ValidationError` (422) for an invalid sort column. 10.1's status table reserves 422 for "request body failed schema validation (FastAPI default)" and defines 400 as "business rule violated," which an invalid `sort` query parameter is. WP-07's gate is the first one that actually asserts this status code (`?sort=hashed_password` → `400`), which is what surfaced it — companies' and departments' list endpoints had the same latent defect since WP-05/WP-06 but nothing tested it. Fixed by raising a new `InvalidSortError(AppError)` (400, `code: "invalid_sort"`) instead; verified live and in `test_invalid_sort_column_returns_400_not_an_interpolated_order_by`.

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

**Not delivered in this pass:** leave-type seeding (the `leave_types` table doesn't exist — WP-10); a real activation-email flow for the HR admin (WP-26).

---

## 19. WP-05 verification — actual output

All of this was run live against `uvicorn` first (to see the real behavior before writing permanent tests), then codified as `tests/integration/test_company_onboarding.py` (5 tests) so it isn't a one-off.

| # | Check | Result |
|---|---|---|
| 1 | Two companies register, land `pending`, no user created | **Pass.** `POST /companies/register` twice → both `201`, `status: "pending"`. `SELECT count(*) FROM users WHERE company_id = ...` → `0` for both, confirmed both live (`psql`) and in `test_register_creates_a_pending_company_with_no_user`. |
| 2 | Approved companies get preset departments, and a `company_settings` row | **Pass.** Registered a `super_admin` directly in the database (8.5 — never via a route), approved a Technology company through the real API → `GET /departments` as its new HR admin returned exactly the 7 Technology-preset departments (Design, DevOps, Engineering, Human Resources, Product, Quality Assurance, Sales); a Retail company returned its own 6. `GET /companies/me` succeeded, confirming `company_settings` exists (RLS would return nothing otherwise). Codified in `test_approve_seeds_company_settings_departments_and_hr_admin_in_one_transaction`. |
| 3 | A deliberately failing seed step rolls back the whole approval, company still `pending` | **Pass — proven by actually causing the failure.** Planted a `company_settings` row for a company before approving it (forces the real `UNIQUE` violation the seed step would hit), called `POST /companies/{id}/approve` → `409`, then confirmed: `status` still `pending`, `approved_at`/`approved_by` still `NULL`, zero `users` rows for that company. Live via `psql` first, then `test_a_failing_seed_step_rolls_back_the_whole_approval`. |
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
| Two companies register and are approved; preset departments + `company_settings` | **Done — verified.** See §19 rows 1–2. Leave types are not seeded — the table doesn't exist (WP-10); flagged, not silently skipped. |
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
| A created employee can activate their own account and log in | **Not deliverable this session.** `/auth/activate` is WP-03's and was deliberately skipped (per instruction). What WP-07 delivers instead, and what was actually verified: the activation token is generated, hashed, and stored correctly at create time (`activation_token_hash`, `activation_expires_at`), and handed to the HR caller in the response — ready for WP-03's route to redeem the moment it exists. Flagged explicitly rather than silently dropped, the same treatment every other forward dependency in this session got. |
| A deactivated employee cannot log in but still exists in the database | **Done — verified**, and further tightened: the linked user is deactivated too (so login and refresh both reject it per 9.2's "reject if is_active is false" — no code change needed there, WP-01's `AuthService` already checks it), the employee row is provably still in the database (`psql`), and a single-record `GET /employees/{id}` also 404s by id (an explicit extra check this session's gate asked for, beyond the spec's own literal wording — see §24 row 4). |
| A manager sees only their own reports | **Done — verified.** See §24 row 5. |
| Isolation tests cover `employees` | **Done — verified, automatically.** See §24 row 7. |

**WP-07 gate passes**, with one condition — employee self-activation-and-login — explicitly named as blocked on WP-03 (deliberately out of scope this session) rather than faked or silently skipped. Not proceeding to WP-08, WP-03, or WP-27 per instruction.

---

## How WP-01 was verified

Everything below was run against the local dev database and a locally started `uvicorn` instance; no destructive action was taken against anything outside this repo's own dev DB and no code outside the files listed in this report's fix rows was modified:

- `import app.main` → succeeds (was: two independent `ImportError`/`ModuleNotFoundError` failures).
- Dev database fully cleared (all tables, both enum types, `alembic_version`) to simulate a genuinely empty database (`ems_user` has no `CREATEDB`, so a separate scratch DB wasn't available); `alembic upgrade head` run from zero → `companies`, `users`, `refresh_tokens` all created with the correct columns, types, and constraints.
- `psql \d companies` / `\d users` / `\d refresh_tokens` → confirmed `uq_companies_lower_email`, `uq_users_company_id_email` and `uq_users_company_id_username` as composite/functional case-insensitive unique indexes; `locked_until` and `expires_at` as `timestamp with time zone`; `replaced_by_id` present with its self-referential FK; `fk_companies_approved_by_users` present.
- Live `uvicorn` run: `GET /health` → `200`; `GET /openapi.json` → all three auth routes listed under `/api/v1/auth/*`.
- End-to-end smoke test against the live server: `POST /api/v1/auth/register` (201) → `POST /api/v1/auth/login` with wrong password (401, generic message) → correct password (200, `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax`, no `Secure` in dev) → `POST /api/v1/auth/refresh` with that cookie (200, rotated cookie, old token now `is_revoked` in the database) → replay of the *original* cookie (401) → confirmed **both** the original and the once-rotated-to token are now `is_revoked = true` (family revocation) → refresh with the second (now-revoked) cookie also 401. This surfaced and led to fixing §4.20 and §4.21, neither of which was caught by import-only checks.
- Dev database returned to an empty-of-data (but migrated) state afterward via `TRUNCATE`, so it's clean for whoever starts WP-02.
