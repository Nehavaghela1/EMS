# WP-01 — Reconciliation Report

**Governs:** Section 20 of `docs/EMS_PRO_DEV_SPEC.md` (in full).
**Method:** Every file under `app/` and `alembic/` was read in full and compared against the spec section that governs it, using the Section 20.2 checklist. Where the checklist implied a runnable check (does the app start, does `alembic upgrade head` actually create tables, is a package importable), that check was executed against the local dev database — read-only at audit time; the blocking items were then actually applied (this revision of the report) and re-verified the same way. See "How this was verified" at the end.

**Status: all 14 blocking items are fixed and re-verified. WP-02 is not yet started, per instruction.**

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
| 2.2 | `app/modules/identity/service.py` | Service "raises `AppError` subclasses ... never `HTTPException` directly" (5.2, 6.6) | Raises `HTTPException` throughout | **Later (WP-02)** — *reclassified from Blocking on 2026-08-31, before this fix pass.* | `app/core/exceptions.py` doesn't exist yet. Every raise site now carries `# TODO(WP-02): AppError` naming the specific subclass (`ConflictError`, `UnauthorizedError`, `AccountLockedError`, `AccountInactiveError`) so the WP-02 migration is mechanical. |
| 2.3 | `app/modules/identity/repository.py` | No `HTTPException`, no business decisions | Compliant | — | Unchanged. |
| 2.4 | `app/modules/identity/router.py` | Router body is 1–3 lines | Compliant | — | Unchanged; still true after the cookie-handling additions (the cookie helper is a private function, not inline route logic). |
| 2.5 | `app/modules/identity/schemas.py` | Response schemas must never expose a raw token (5.2) | Was: `TokenResponse.refresh_token: str` | **Fixed** | Field removed. `TokenResponse` now carries only `access_token` and `token_type`. |
| 2.6 | `app/modules/identity/service.py` — `register_company` | Route 12 (`POST /companies/register`): company self-registration → `status = pending`. The HR admin user is created only at approval (route 15), in one transaction with seeding `company_settings`, departments and leave types (10.2, 6.7). | `register_company` sets `status = active` immediately and creates an already-active `hr_admin` user from a client-supplied password, with no approval step | **Later (WP-05)** — *carried forward, not fixed.* | Correct behavior needs `company_settings` (WP-04) and the approval route + `industry_presets` seeding (WP-05); a partial fix now would mean starting WP-05 out of order, which contradicts the instruction to not start work past WP-01. `find_by_email`'s use inside this method was still updated to keep it *running* (see §4.22) — its *business behavior* is unchanged. Route path (`/auth/register` vs. the spec's `/companies/register`) is the same deferred item — company registration belongs in a `companies` router/module that doesn't exist yet. |

---

## 3. Database (Sections 6, 7)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 3.1 | `app/db/base.py` | Two shared base classes: `TimeStampedBase` **and** `TenantBase` (7.1) | Was: only `TimeStampedBase` | **Fixed** | `TenantBase(TimeStampedBase)` added exactly per 7.1 — `company_id` FK to `companies.id`, `ondelete="RESTRICT"`, indexed, `nullable=False`. Not yet used by any model (no tenant table exists yet — first use is `company_settings` in WP-04), but ready. |
| 3.2 | `app/db/base.py` | Every timestamp column `TIMESTAMPTZ` (6.3) | Compliant | — | Unchanged. |
| 3.3 | `app/modules/identity/models.py` — `User.locked_until` | `TIMESTAMPTZ` (6.3, "no exceptions") | Was: naive `DateTime`, and `Mapped[DateTime]` (wrong type hint) | **Fixed** | `DateTime(timezone=True)`, `Mapped[datetime | None]`. Verified via `psql \d users`: `timestamp with time zone`. |
| 3.4 | `app/modules/identity/models.py` — `RefreshToken.expires_at` | `TIMESTAMPTZ` (6.3) | Same defect as 3.3 | **Fixed** | Same fix. Verified via `psql \d refresh_tokens`: `timestamp with time zone`. |
| 3.5 | Primary keys, all models | UUID, generated in Python (6.4) | Compliant | — | Unchanged. |
| 3.6 | `datetime.utcnow()` / shared time helper | `app/core/time.py::utcnow()` (6.3) | `app/core/time.py` still doesn't exist; direct `datetime.now(timezone.utc)` calls remain, now in more places (repository lockout/rotation code) | **Later (WP-02)** | Every new direct call is commented `# app/core/time.py::utcnow() doesn't exist yet (WP-02)` so the eventual swap is a grep-and-replace, not a rediscovery. |
| 3.7 | `app/modules/identity/models.py` — `Company` | Spec's `companies` table (7.2), column for column | Was: wrong types (`code` 50 chars, `country` free text defaulting to `"India"`, `currency` 10 chars), missing `rejected` status, no `lower(email)` uniqueness, missing `gst_number`…`last_employee_seq`, missing `approved_by` | **Fixed** | Rewritten column-for-column against 7.2: `code VARCHAR(20)`, `country VARCHAR(2) DEFAULT 'IN'`, `currency VARCHAR(3) DEFAULT 'INR'`, `CompanyStatus` includes `rejected`, functional unique index on `lower(email)` (the plain column-level `UNIQUE` was deliberately *not* also kept — one enforcement mechanism, not two), plus every other column in the spec's table. `approved_by` added via the `use_alter=True` follow-up migration per the 7.2 cycle note (see §7). |
| 3.8 | `app/modules/identity/models.py` — `User` | `uq_users_company_id_email`, `uq_users_company_id_username`, `last_login_at` | Missing username uniqueness and `last_login_at` | **Fixed** | Both added. Uniqueness on both `email` and `username` is a composite `(company_id, lower(...))` index per the spec amendment resolving spec-gap #1 (see §10). |
| 3.9 | `app/modules/identity/models.py` — `RefreshToken` | `replaced_by_id`, `revoked_at`, `ip_address` (7.2) | None existed | **Fixed** | All three added. `replaced_by_id` is a self-referential nullable FK to `refresh_tokens.id`. Verified via `psql \d refresh_tokens`. |
| 3.10 | Money columns | `NUMERIC(14,2)` (7.1, 11.1) | No money columns exist yet | **Later** | N/A until payroll (WP-16+). |
| 3.11 | `app/db/session.py` | Runtime session as the non-owning `ems_app` role (8.2) | Single-role `DATABASE_URL`, no split yet | **Later (WP-02)** | `docker-compose.yml`/`bootstrap_roles.sql` are WP-02 deliverables. |

---

## 4. Multi-tenancy and security (Sections 8, 9)

| # | File | Spec requires | Code does | Status | Note |
|---|---|---|---|---|---|
| 4.1 | Every tenant table | RLS policy (8.3) | No tenant tables exist yet | — | Unchanged — no violation possible yet. First arrives with `company_settings` (WP-04). |
| 4.2 | `app/modules/identity/repository.py` — `UserRepository` | Every method except the pre-auth lookups requires `company_id` (7.2) | Was: `get_by_email`/`get_by_id` took no `company_id` at all | **Fixed** | `find_by_email(email, company_code=None)` is the pre-auth, cross-company lookup (returns `list[User]`, matching 5.3's worked example). `get_by_id(user_id, company_id)` now requires it. `get_by_id_for_token_refresh(user_id)` is a fourth, explicitly-documented exception beyond the three the spec names in 7.2 — see the note in §10 (spec gap #3, new). |
| 4.3 | `app/modules/identity/repository.py` + `service.py` | Multi-company email match → `409 company_required` with the company list (5.3, 7.2, 9.2 route 1) | Was: `.first()` — silently picked one company | **Fixed** | `find_by_email` returns every candidate; `login()` implements 5.3's worked example: 0 matches → constant-time `DUMMY_HASH` check, no match on password → generic 401 (with lockout bookkeeping), >1 match → `409` with `code: "company_required"` and the company name list, else the normal checks (lockout, active) in the spec's order. Verified live: registering one company and logging in behaves correctly; the >1-company branch is exercised by unit-level reasoning (no second company was registered in the smoke test — real coverage arrives with WP-03's test suite, per Section 15.5, tests land with their feature). |
| 4.4 | `app/db/rls.py`, `get_tenant_db` | (8.4) | Don't exist yet | **Later (WP-04)** | Unchanged. |
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
| 4.15 | `app/modules/identity/service.py` — `login` | Lockout after 5 failures → `423` (9.4); `DUMMY_HASH` timing defense (9.3) | Neither existed | **Fixed** | Both implemented as part of 5.3's worked example: `failed_attempts` increments per unmatched candidate, `locked_until` is set once `failed_attempts >= MAX_LOGIN_ATTEMPTS`, a locked account gets `423` with the unlock time, and a successful login resets both `failed_attempts` and `locked_until`. **New should-fix introduced by this fix:** `MAX_LOGIN_ATTEMPTS = 5` and `LOCKOUT_MINUTES = 15` are module-level constants in `service.py`, not `settings` fields — `app/core/config.py` isn't in this pass's scope and doesn't have them yet. Move to `settings.MAX_LOGIN_ATTEMPTS`/`settings.LOCKOUT_MINUTES` in WP-02 (both are already named in the spec's `.env.example`, 17.2). |
| 4.16 | `app/main.py` | CORS: explicit origin list from `settings.CORS_ORIGINS`, explicit method/header allowlist (9.7) | Hardcoded origin, `allow_methods=["*"]`, `allow_headers=["*"]` | **Should-fix (open)** | Not touched in this pass — `config.py` doesn't have `CORS_ORIGINS` yet and adding it is WP-02 scope. Still not a live risk today (single hardcoded dev origin, not a wildcard-with-credentials). |
| 4.17 | `app/main.py` | Rate limiting, security headers, request-ID middleware (9.5, 9.8, 16.2) | None present | **Later (WP-02/WP-04)** | Unchanged. |
| 4.18 | `.env`, git history | Never committed, no defaulted secret | Compliant | — | Unchanged. |
| 4.19 | `alembic.ini` | No casually-committed credential (spirit of 9.10) | Plaintext local DB URL committed | **Should-fix (open)** | Not touched — fixing this properly means `alembic/env.py` reading `ALEMBIC_DATABASE_URL` from settings/environment, which is WP-02's role-split work. Low real risk (local Docker Compose password only). |
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
| 6.4 | Structured JSON logging | Still doesn't exist. **Later (WP-02)**. |

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

## 9. Everything correctly not built yet ("Later") — updated

- `pyproject.toml`, ruff config, mypy config (WP-02)
- `app/db/seed/bootstrap_roles.sql`, the `ems_owner`/`ems_app` role split, `ALTER DEFAULT PRIVILEGES` (WP-02, 8.2)
- `app/core/time.py`, `exceptions.py`, `dependencies.py`, `pagination.py`, `rate_limit.py`, `middleware.py`, `logging.py`, `encryption.py` (WP-02/03/04/08)
- `app/db/rls.py`, `TenantBase` usage on a real table, `company_settings`, `tests/isolation/` (WP-04)
- `app/workers/celery_app.py`, `app/workers/tasks/` (WP-09)
- `Dockerfile`, `README.md` content, `docker-compose.yml`'s two-role setup (WP-02, WP-15)
- `frontend/` contents beyond the empty `src/` scaffold (WP-12)
- Company approval workflow (`pending` → `active`), `company_settings`/department/leave-type seeding, industry presets, HR-admin creation at approval rather than registration (WP-05 — see §2.6)
- `MAX_LOGIN_ATTEMPTS`/`LOCKOUT_MINUTES` moving from `service.py` constants to `settings` (WP-02 — new, §4.15)
- Rehash-on-login wiring for `needs_rehash` (WP-03 — the function itself now exists, §4.14)
- CORS from settings, security headers, rate limiting, request-ID middleware (WP-02/04)
- Sentry wiring (WP-02 per 16.3)

---

## 10. Spec gaps

1. **~~Case-insensitive uniqueness on `users.email`~~ — RESOLVED.** Section 7.2 now explicitly specifies `(company_id, lower(email))` and `(company_id, lower(username))`, consistent with `companies.email`. Implemented in `models.py` and verified in the database (§4.6).
2. **~~Where `email-validator` is declared~~ — RESOLVED.** Section 3.1's stack table now names `email-validator` (or `pydantic[email]`) explicitly. Added to `requirements.txt`.
3. **New: a fourth pre-authentication-shaped repository method.** Section 7.2 names exactly three lookups exempt from requiring `company_id` (`find_active_by_email`, `get_by_activation_token`, `get_for_password_reset`). Implementing `refresh()`'s reuse-detection required a fourth: loading the `User` behind a refresh token, where — exactly as at login — there is no verified `company_id` yet. `get_by_id_for_token_refresh` was added, matching the same justification the spec gives for the other three (unreachable without the corresponding secret — here, a hashed, unexpired refresh token). This is implemented and documented in the code, not blocked on a spec answer, but it's worth Section 7.2 either naming it as a fourth exception or folding refresh-token lookups under a reworded version of the existing three, so the list stays authoritative.

---

## 11. WP-01 exit gate — current status

Per Section 19: *the audit report exists; every item is fixed or assigned; `alembic upgrade head` runs clean on an empty database; the app starts and `/health` returns 200.*

| Gate condition | Status |
|---|---|
| `docs/RECONCILIATION.md` exists | **Done** |
| Every item fixed or assigned to a WP | **Done** — 14 blocking items fixed (§1–§4), 2 should-fix items remain intentionally open and are not blocking (§4.16, §4.19), everything else is assigned a work package by name |
| `alembic upgrade head` runs clean on an empty database, creating real tables | **Done — verified.** See §7.1. |
| App starts, `/health` returns 200 | **Done — verified.** `import app.main` succeeds; live server: `GET /health` → `200 {"status":"ok","environment":"development"}`. |

**WP-01 gate passes.** Not proceeding to WP-02 per instruction.

---

## How this was verified

Everything below was run against the local dev database and a locally started `uvicorn` instance; no destructive action was taken against anything outside this repo's own dev DB and no code outside the files listed in this report's fix rows was modified:

- `import app.main` → succeeds (was: two independent `ImportError`/`ModuleNotFoundError` failures).
- Dev database fully cleared (all tables, both enum types, `alembic_version`) to simulate a genuinely empty database (`ems_user` has no `CREATEDB`, so a separate scratch DB wasn't available); `alembic upgrade head` run from zero → `companies`, `users`, `refresh_tokens` all created with the correct columns, types, and constraints.
- `psql \d companies` / `\d users` / `\d refresh_tokens` → confirmed `uq_companies_lower_email`, `uq_users_company_id_email` and `uq_users_company_id_username` as composite/functional case-insensitive unique indexes; `locked_until` and `expires_at` as `timestamp with time zone`; `replaced_by_id` present with its self-referential FK; `fk_companies_approved_by_users` present.
- Live `uvicorn` run: `GET /health` → `200`; `GET /openapi.json` → all three auth routes listed under `/api/v1/auth/*`.
- End-to-end smoke test against the live server: `POST /api/v1/auth/register` (201) → `POST /api/v1/auth/login` with wrong password (401, generic message) → correct password (200, `Set-Cookie: refresh_token=...; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=lax`, no `Secure` in dev) → `POST /api/v1/auth/refresh` with that cookie (200, rotated cookie, old token now `is_revoked` in the database) → replay of the *original* cookie (401) → confirmed **both** the original and the once-rotated-to token are now `is_revoked = true` (family revocation) → refresh with the second (now-revoked) cookie also 401. This surfaced and led to fixing §4.20 and §4.21, neither of which was caught by import-only checks.
- Dev database returned to an empty-of-data (but migrated) state afterward via `TRUNCATE`, so it's clean for whoever starts WP-02.
