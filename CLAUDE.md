# EMS Pro

Multi-tenant HRMS + Payroll + Projects SaaS platform.
FastAPI · PostgreSQL 16 (FORCE RLS) · SQLAlchemy 2.0 (sync) · Alembic · Redis · Celery · React + TypeScript + Vite.

## How we work (read first)

The owner is Bhavdeep, a junior Python developer. Claude coordinates; coding agents write code; Bhavdeep runs, pushes and merges.
- Be direct and evidence-based. Check every claim against the real code or raw command output. Say "I cannot confirm" when you cannot.
- Keep replies short and scannable. Never cut accuracy. Explain each command in plain words and say what its output proves.
- After an agent report give a per-rule YES/NO with a confidence. Only Bhavdeep's own terminal runs count as proof.
- Decide industry-standard technical and security rules yourself (Zoho-class multi-tenant HRMS). Ask only business questions.
- Max about 3 rounds per sub-feature. Include everything related in one round. Nothing small stays open when a sub-feature is Done.
- Backend-first: a sub-feature is Done when its backend is complete and tested. Frontend problems go to the "frontend to fix later" list.
- Never `git push`. Never touch `.env`. Never print secrets. Never `git checkout/switch/restore/reset/stash` unless Bhavdeep asks.
- Agent prompts live in the repo root as `ws_*.md` (excluded from git). Read the newest ones for the exact standing rules.

## The specification

**`docs/EMS_PRO_DEV_SPEC.md` is the single source of truth.** If code and spec disagree, the spec wins, or the spec is amended first.
Do not invent a schema, route or convention the spec already defines. If something is missing, propose it for the spec first.

## Where the build is (2 Nov 2026)

Backend: 19 of 45 sub-features done (modules 1, 2, 3). Modules 4 to 7 are not started (26 sub-features, 0%). Latest checks on main: `ruff check .`, `ruff format --check .`, `mypy app`,
one alembic head `a1b2c3d4e5f6`, full pytest 968 passed + 1 skipped. The tracker's "Me / Claude / Senior" tick columns are still unticked for every row; they are Bhavdeep's to tick.

**Who to ask:** Bhavdeep is the only person to ask. There is no other reviewer in the loop. Ask him business questions only, in plain words, one at a time.
Technical choices are made by you and written in the report. Tracker items marked "senior question" are open business decisions: list them for Bhavdeep, do not guess.

### Module 1 Identity / workspace: DONE (7 of 7). Tests in `tests/rules/test_1_*`

| ID | Sub-feature | PR / proof |
|---|---|---|
| 1.1 | Login and tokens | #14 (4de4e1e), 1.1b #16 (e3cd950); 31 rule tests |
| 1.2 | Company registration and approval | #15 (5c17059); 24 tests |
| 1.3 | Activation and invites | #17 (c8ce7c9); 11 tests |
| 1.4 | Password reset | commits b38c886 to ed892ac, CI fixes c1de94a, 15d6992; 44 tests |
| 1.5 | Workspaces | #21 (69931f2), #22 (ae79b40); 27 tests |
| 1.6 | Locations and branches | #23 (5b4d086); 39 tests. Tracker PR cell still has the placeholder "[copy 1.6 test counts here]" |
| 1.7 | Roles and role change | #24 (9e7cb84); follow-ups #25 (8f8d5eb: reserved subdomains, country by platform admin only, reactivation), #26 (c14b95b: manager role) |

Frontend tests for module 1 are done (LoginPage, RegisterCompanyPage, ActivatePage, ForgotPasswordPage, CreateWorkspacePage, LocationListPage, SettingsPage).

### Module 2 HR: DONE (6 of 6)

| ID | Sub-feature | PR / proof |
|---|---|---|
| 2.1 | Departments | #27 (0dd0c08); suite 631 |
| 2.2 | Onboarding and directory | #28 (acf8562); suite 649; fixed manager loops |
| 2.3 | Profile and editing | #29 (ceea622) edit rules; #30 (855424f) five new profile-section tables with RLS, 22 routes |
| 2.4 | Bulk actions and export | #31 (7ec4374); #32 (5776050) export screen fix |
| 2.5 | Employee documents | #33 (59e32c2); suite 871 |
| 2.6 | Resignation, termination, F&F | #34 (eaf21bd) |

### Module 3 Platform: DONE (6 of 6)

| ID | Sub-feature | PR / proof |
|---|---|---|
| 3.1 | Announcements | #37 (d119490) |
| 3.2 | Notifications | #37 |
| 3.3 | Files and vault | #36 (1bf5f4b) |
| 3.4 | Global search | #37 |
| 3.5 | Audit logs | #35 (ce15656) |
| 3.6 | Background jobs | #35 |

The three known problems (file signing, jobs leak, dev-database leftovers) are closed with proof. The tracker "Known problems" block is up to date.

### Frontend vitest status: modules 1, 2 and 3 DONE

Module 3: PR #38 (merge 9aef204). Module 2: PR #40 (merge e8d3fd2). Date fix for backend tests: PR #39 (merge c628056).
On main: 16 test files passed + 2 skipped (`Module2Gaps`, `Module3Gaps`, only `it.todo` lines); 85 passed, 30 todo, identical on repeated runs. Lint 0 errors; build passes.
Frontend tests are proven by deliberate breaks (module 2: M1 to M12, module 3: M1 to M7). Missing screens are recorded as `it.todo("GAP: ...")`, never as red tests.
Modules 4 to 7 have no frontend tests yet. CI runs only `npm run build` for the frontend, not `npm test`; adding it is Bhavdeep's decision. Never touch `.github`.

### Module 4 Time and leave: NEXT, not started (0 of 7). Module folder `app/modules/time_leave/`

Tracker proof columns: Works, Bad input rejected, Own / team scope, Other company 404, Dates and overlaps, Balance, Approver = reporting chain, Status flow, Tests, CI green.

| ID | Sub-feature | Suggested rules (tracker) | Open decisions for Bhavdeep |
|---|---|---|---|
| 4.1 | Shifts | HR-level manage; employee sees own assignment, manager sees team (no manager check today); no overlapping assignments | |
| 4.2 | Punch in / out | one punch-in per day before punch-out; server time, never device time; employee punches only for self | |
| 4.3 | Regularization | read only by requester, HR-level, approver (anyone today); approver = reporting chain, no self-approval; attachments protected (PR #12) | |
| 4.4 | Monthly attendance calendar | employee own, manager team, HR all; holidays and weekends shown correctly | |
| 4.5 | Leave types and balances | HR-level set policies; balance never negative unless policy allows | can a manager see team balance? |
| 4.6 | Leave requests and approvals | no overlap with leave or holiday; deduct on approve, restore on cancel; pending to approved / rejected / cancelled only | owner self-approve is allowed today: keep? |
| 4.7 | Holidays | HR-level manage; optional vs mandatory; same date not added twice | |

### Module 5 Payroll: not started (0 of 7). Folder `app/modules/payroll/`

Proof columns: Works, Bad input rejected, HR-only / own payslip, Other company 404, Money exact (Decimal, half-up), Official rates and dates, Salary and bank hidden, Locked after approval, Audit logged, Tests, CI green.

| ID | Sub-feature | Suggested rules (tracker) | Open decisions |
|---|---|---|---|
| 5.1 | Salary structures | HR-level only; components add up to CTC; changes never alter an approved run | |
| 5.2 | Statutory rates and tax slabs | every rate from an official source with link and effective date; old rates kept for past months; replace TaxGuru figures | verify each rate (see Accuracy note) |
| 5.3 | Salary assignment and revisions | effective dates never overlap; employee sees own, HR all, manager none; every change logged | |
| 5.4 | Payroll runs | initiate, process, approve only; employees and managers never see run totals (they do today); approved run locked | confirm LOP comes from attendance |
| 5.5 | Payslips | employee sees only own; breakdown adds up exactly | employer PAN/GST shown by design? (finance question) |
| 5.6 | Reimbursements | receipt required; approver = reporting chain; paid only once | |
| 5.7 | Payout accounts | masked to last 4 (PR #11); encrypted at rest (missing today) | full reveal only with audit? |

### Module 6 Performance: not started (0 of 5). Folder `app/modules/performance/`

Proof columns: Works, Bad input rejected, Own / team scope, Other company 404, Right employee looked up, Status flow, Tests, CI green.

| ID | Sub-feature | Suggested rules (tracker) | Open decisions |
|---|---|---|---|
| 6.1 | Appraisal cycles | HR-level create; goals only inside an active cycle; cycle dates do not overlap | |
| 6.2 | Goals | employee sets own, manager for team, HR any; fix swapped lookup (`service.py:126`) | must weightage total 100%? |
| 6.3 | Self and manager reviews | self-review only by the employee; manager review only by reporting chain; no edits after submit | |
| 6.4 | PIPs | manager only for team, HR any; mentor exists and active (PR #10); failed outcome exits the employee (broken today) | |
| 6.5 | Performance summary | employee own, manager team, HR all (any manager today) | |

### Module 7 Projects: not started (0 of 7). Folder `app/modules/projects/`

Proof columns: Works, Bad input rejected, Member / manager scope, Other company 404, Cost and salary hidden, Approved entries locked, Tests, CI green.

| ID | Sub-feature | Suggested rules (tracker) | Open decisions |
|---|---|---|---|
| 7.1 | Projects | archive keeps history | who creates / edits? who reads? |
| 7.2 | Tasks and board | members create and edit tasks in their projects; todo, in progress, review, done | |
| 7.3 | Milestones | project manager edits | complete only when its tasks are done? |
| 7.4 | Members and rates | project manager / HR add members; hourly rates hidden from members | |
| 7.5 | Time entries | employee logs only own hours, fails closed with no employee profile; approved entries cannot be edited or deleted; approver = reporting chain | |
| 7.6 | Comments and documents | only project members comment or upload; delete own items, or project manager | |
| 7.7 | Summary and budget | budget figures only for project manager / HR / owner (everyone today); cost uses the salary valid on the work date; money rounded half-up | |

Order of work: module 4 next, then 5, 6, 7 (the tracker order). Before starting any sub-feature, Bhavdeep writes "My rules" in the tracker; wait for them when they are empty.
For one sub-feature at a time, follow the same routine as modules 1 to 3: tests first (real red), build, fix round, mutation checks, gates, PR, tracker cells.
Where a sub-feature touches money, files or personal data, re-read the Rules that are never relaxed first.

## Structure: every module has exactly these five files

```
app/modules/<name>/
  models.py      SQLAlchemy tables only        no logic
  schemas.py     Pydantic request/response     no logic
  repository.py  database queries only         no business rules, no HTTP
  service.py     business rules only           no SQL, no HTTP
  router.py      HTTP routes only              no business rules, no SQL
```

Modules: `identity · hr · time_leave · performance · payroll · projects · platform`. Reference: `app/modules/identity/`.

## Rules that are never relaxed

1. Every tenant table inherits `TenantBase` and gets an RLS policy in the same migration (Spec §8). Exceptions: `users`, `refresh_tokens`, `audit_logs`. Do not "fix" them.
2. Every new tenant table gets an isolation test in the same change.
3. `company_id` comes from the verified JWT only, never from body, path, query or header.
4. Money is `Decimal` with explicit `ROUND_HALF_UP`. Never `float`.
5. No statutory rate, slab or threshold as a literal in Python. They live in tables (Spec §12).
6. UUID primary keys. `TIMESTAMPTZ`, UTC, via `app/core/time.py::utcnow()`.
7. Services raise `AppError` subclasses, never `HTTPException`.
8. Services own the commit. Repositories never commit.
9. Another tenant's resource returns 404, not 403. Missing and not-allowed give the same 404.
10. Never log or return passwords, tokens, Aadhaar, PAN or bank details. `AuditService.record` rejects unsafe `details`.
11. Tests are written first, in the same work package as the feature.
12. Never `alembic downgrade`. Agents never run `alembic upgrade` by hand: the test suite migrates its own test database.

## Conventions that already exist (reuse them)

- Roles: `require_role(...)` (adds owner when hr_admin is allowed). `HR_LEVEL_ROLES` = hr_admin, owner, super_admin.
- Rate limits: `@limiter.limit("N/minute", key_func=get_user_or_ip_key)` with `request: Request`. Every limited route has a 429 test.
- Errors: `ValidationError` 422, `ForbiddenError` 403, `NotFoundError` 404, `ConflictError` 409, `PayloadTooLargeError` 413.
- Audit: `AuditService.record(company_id, actor, action, entity_type, entity_id, details)` in the same commit as the change.
  IP, user agent and request id come from `app/core/audit_context.py` (set by `AuditContextMiddleware`).
- Jobs: `app/core/jobs.py` (`register_job`, `authorize_export_job`). Job status and download: starter or HR-level of the same company only.
  Exports expire after 24h (daily cleanup task). Audit export capped at 100,000 rows.
- Files: upload through `validate_document_upload` and `read_upload_file_capped` (pdf, jpg, jpeg, png, docx; 25 MB; 413/422);
  stored `{UPLOAD_DIR}/{company_id}/{uuid}.{ext}`; signed link 600 s; link only for uploader, HR-level, or someone who can see the attached project;
  employee-document files never open through the generic link. `build_signed_url` signs without audit; `generate_signed_url(user)` is audited and checked.
- Announcements: company-wide posts HR-level only; manager posts only to own or headed department (role must be `all`); soft-deleted department hides its posts.
- Notifications: own only; `action_url` must be a relative app path (no `//`, backslash, scheme, spaces, control characters); daily cleanup of read ones older than 90 days at 02:30 UTC.
- Search: 2 to 100 chars, escaped `% _ \`, limit 10 per kind in SQL; HR-level sees all with email/code, manager sees team with email/code, others see name + department only.

## Testing rules

- Tests never write into the dev database `ems_pro`. They use `ems_pro_test` (`TEST_DATABASE_URL`); `tests/conftest.py` refuses the dev database.
  Celery tasks open their own session: patch `get_task_db_session`. Upload folder is isolated per test (autouse fixture).
- No local paths in app or tests. Tests must not depend on `.env`. Never `monkeypatch.undo()`. Never run two pytest processes at once.
- Tests first with a real red result (the assertion failing, not a setup error). Then mutations one at a time: edit the real code, copy the raw `FAILED` line, revert, show it passes. `grep -rn MUTATION app tests` must print nothing at the end.
- Gates run once at the end on the whole repo: `ruff check .`, `ruff format --check .`, `mypy app`, `alembic heads`,
  CI-style `CELERY_TASK_ALWAYS_EAGER=false pytest <every new or changed test file> tests/security tests/unit -q -rs`, then full `pytest -q -rs`. `git status --short` empty.
- Dates: never type a date into a test when a rule compares it with today (resignation, leave start, "not in the future", exit dates). Compute it from `app.core.time.utcnow()`.
  A fixed date is fine only when it is just stored or compared with other fixed dates. (A hard-coded 2026-10-31 turned CI red on 1 Nov 2026, PR #39.)
- Frontend tests (vitest): render the real page, act with userEvent, assert what the user sees or the request sent. Mock only the network layer.
  Never define the rule inside the test, no `any`. Rules proven by backend tests do not belong there. A missing or wrong UI becomes `it.todo("GAP: ...")` and goes in the report; do not fix app code or commit red tests.

## Deploy steps

Production runs the `scripts/setup.sh` steps (migrate, then the reference-data seeds: industry presets, statutory rates, professional-tax and income-tax slabs) after every release, and a new tax year needs a new tax set (income-tax slabs, and PF/ESI/professional-tax rows if they changed) added before 1 April, or payroll runs for that year return 409. Production must also run the Celery beat process (one instance), which drives the daily rate check of the platform's rate sources.

## Commands

```bash
docker compose up -d                              # Postgres + Redis
alembic upgrade head                              # migrations (Bhavdeep runs this, as ems_owner)
uvicorn app.main:app --reload                     # API at localhost:8000/docs
celery -A app.workers.celery_app worker -l info   # worker
celery -A app.workers.celery_app beat -l info     # scheduler, ONE instance only
cd frontend && npm run dev                        # frontend at localhost:5173

ruff check . && ruff format --check .             # lint
mypy app/                                         # types
pytest -q -rs                                     # tests
cd frontend && npm run lint && npm run build && npm test
```

## Tracker sheet cells (Bhavdeep's EMS_Pro_Tracker_1)

Per sub-feature give, each in its own code box and numbered: Area (short names), Before (worded positively: what was already in place), After,
Rules (1 to 10 plain lines), PR (same number in both rows when one PR covers two sub-features), Commits (hash + one-line message, separate cell),
PR history (2 lines), and PR proof ticks (Works, Bad input rejected, Right roles only, Own record / own team only, Other company 404, Personal data hidden,
Manager chain valid, Status flow correct, Audit logged, Tests, CI green; use N/A with a reason).

## Frontend to fix later (running list, backend-first)

- Module 1/2: forgot/reset password company code, country editing, roles screen, head office active toggle, 2.3 profile section screens, 2.5 employee documents screens (upload broken, list/download routes new), 2.6 screens (withdraw button, clearance queue, limited view, "exit scheduled" status, reason/notes/remark fields, notice defaults screen, employee FnF view after exit), real-Celery export check, `EmployeeListPage` reads `result.file_name` (job result is now only `row_count`/`expires_at`; unverified), hand-typed vs generated API types.
- Module 3: announcement create form with department choice and poster delete button; search results screen (the Ctrl+K modal does not call `/search`; `url` may be null); notification `action_url` may be null; audit logs page and export/download buttons; job progress/failure messages; project document upload errors for wrong type (422) and size (413) and the allowed-types list; phone apostrophe in CSV.

- Found by the frontend test rounds: `DepartmentListPage.tsx` (about lines 199 and 202) appears to send the untrimmed name to the API (the backend trims it; unconfirmed whether `name` is trimmed earlier);
  the project upload picker (3.3) allows `.doc .xlsx .xls .zip` and its hint mentions XLSX and ZIP, but only pdf, jpg, jpeg, png, docx are valid; the upload `<label>` is not linked to its input;
  `NotificationBell`, `ProjectDetailPage` and `TodayAttendanceCard` swallow errors silently; the terminate flow (2.6) has no frontend test; two `catch (err: any)` in `ProjectDetailPage.tsx`;
  the Ctrl+K search modal does not call `/search`. All `it.todo` lines are in `Module2Gaps.test.tsx` (15) and `Module3Gaps.test.tsx` (13).

## Parked on purpose

Antivirus scanning, encryption at rest, S3 storage backend, ex-employee statement delivery, "correct settlement" after freeze, company timezone for exit date (UTC),
attendance/leave interplay for exited employees, employee PAN. Old fake test companies in the local `ems_pro` dev database are harmless and kept.

## Accuracy note

Indian statutory payroll rates in Spec §12 come from the project's research document and are not independently verified. Confirm every rate against its official source
(EPFO, ESIC, State PT authority, Income Tax Department) and record the `source_note` before it computes anyone's real pay. Never present an unverified rate as current law.
