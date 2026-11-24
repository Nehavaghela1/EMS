# PROJECT MAP: Comprehensive Architecture, Roles, Pages, Modals, and APIs

This document is the authoritative single source of truth for the entire EMS application. It maps every user role, dashboard entry point, frontend page, interactive modal, and backend API route across all system modules.

---

## 1. User Roles & Permission Hierarchy

| Role Code (`UserRole`) | Role Name | Authority & Scope | Landing Route & Component |
| :--- | :--- | :--- | :--- |
| `super_admin` | Platform Super Administrator | Multi-tenant platform operations: approve/reject tenant companies, view platform cross-tenant health, cross-tenant payroll metrics, activity logs. No tenant employee-level access. | `/admin`<br>`frontend/src/modules/identity/pages/AdminDashboardPage.tsx` |
| `owner` | Workspace Owner / Org Head | Company root authority: full organizational governance, company profile, legal details, admin delegation, departments, employees, shifts, leave policies, payroll processing & unlocks, performance cycles & summaries, project financials. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` (delegates to `OwnerHrDashboard.tsx`) |
| `hr_admin` | HR Administrator | Human resources operations: full employee lifecycle (onboarding, edits, offboarding, FnF), shift scheduling, leave policy enforcement, attendance locks & unlock audits, payroll setup, pay runs, salary assignments, performance reviews & cycle configuration. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` (delegates to `OwnerHrDashboard.tsx`) |
| `manager` | Department / Team Manager | People & project leadership: manage project tasks, milestone timelines, review & approve member timesheets, per-project member hourly rates, team goals & appraisals, team PIP check-ins, team leave approvals. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` (renders `ManagerDashboardContent`) |
| `employee` | Standard Employee | Self-service operations: clock-in/out attendance, submit regularizations, apply for leaves, view payslips & salary structure breakdown, direct deposit bank account self-service, expense claims, personal goals, log project timesheet hours, resignation. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` |

---

## 2. Dashboard Resolution by Role

When an authenticated user lands on the application, their role determines the experience:

| Authenticated Role | Landed Route | Extracted / Child Components | Primary Backend Services & Routes |
| :--- | :--- | :--- | :--- |
| `super_admin` | `/admin` | `AdminDashboardPage.tsx`, `PlatformPayrollPage.tsx`, `PlatformHealthPage.tsx`, `PlatformActivityPage.tsx` | `app/modules/identity/router.py`<br>`app/modules/platform/router.py`<br>`GET /api/v1/companies`, `POST /api/v1/companies/{id}/approve`, `GET /api/v1/platform/stats/*` |
| `owner` & `hr_admin` | `/dashboard` | `OwnerHrDashboard.tsx`<br>(extracted from `DashboardPage.tsx`) | `app/modules/platform/router.py`, `app/modules/payroll/router.py`<br>`GET /api/v1/dashboard`<br>`GET /api/v1/payroll/runs`<br>`GET /api/v1/leaves`<br>`GET /api/v1/employees` |
| `manager` | `/dashboard` | `ManagerDashboardContent`<br>(in `DashboardPage.tsx`) | `app/modules/platform/router.py`, `app/modules/projects/router.py`<br>`GET /api/v1/dashboard`<br>`GET /api/v1/projects/time-entries`<br>`GET /api/v1/leaves` |
| `employee` | `/dashboard` | `TodayAttendanceCard`, `QuickLeaveCard`<br>(in `DashboardPage.tsx`) | `app/modules/platform/router.py`, `app/modules/time_leave/router.py`<br>`GET /api/v1/dashboard`<br>`POST /api/v1/attendance/punch`<br>`GET /api/v1/leaves/balances` |

---

## 3. Comprehensive Master Route & Endpoint Map

### 3.1 Authentication & Multi-Tenancy (Module: Identity)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Login** | `/login` | Public | `frontend/src/modules/identity/pages/LoginPage.tsx` | `POST /api/v1/auth/login` |
| **Register Tenant** | `/register-company` | Public | `frontend/src/modules/identity/pages/RegisterCompanyPage.tsx` | `POST /api/v1/companies/register`<br>`GET /api/v1/industry-presets` |
| **Activate Account** | `/activate/:token` | Public | `frontend/src/modules/identity/pages/ActivatePage.tsx` | `GET /api/v1/auth/activate/preview`<br>`POST /api/v1/auth/activate` |
| **Forgot Password** | `/forgot-password` | Public | `frontend/src/modules/identity/pages/ForgotPasswordPage.tsx` | `POST /api/v1/auth/forgot-password`<br>`POST /api/v1/auth/reset-password` |
| **New Workspace** | `/workspaces/new` | Authenticated | `frontend/src/modules/identity/pages/CreateWorkspacePage.tsx` | `POST /api/v1/auth/create-workspace` |
| **Company Settings** | `/settings` | All (`Admin/Branding`: `owner`, `hr_admin`) | `frontend/src/modules/identity/pages/SettingsPage.tsx` | `GET /api/v1/companies/me`<br>`PUT /api/v1/companies/me`<br>`GET /api/v1/users/administrators`<br>`PUT /api/v1/users/{id}/role`<br>`POST /api/v1/auth/change-password` |
| **Work Locations** | `/settings/locations` | `owner`, `hr_admin` | `frontend/src/modules/settings/pages/LocationListPage.tsx` | `GET /api/v1/companies/me/locations` |
| **Add Location** | `/settings/locations/new` | `owner`, `hr_admin` | `frontend/src/modules/settings/pages/LocationFormPage.tsx` | `POST /api/v1/companies/me/locations` |

### 3.2 Platform Administration (Super Admin)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Tenant Approval Console** | `/admin` | `super_admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx` | `GET /api/v1/companies`<br>`POST /api/v1/companies/{id}/approve`<br>`POST /api/v1/companies/{id}/reject`<br>`GET /api/v1/companies/{id}` |
| **Platform Payroll Stats** | `/admin/payroll` | `super_admin` | `frontend/src/modules/platform/pages/PlatformPayrollPage.tsx` | `GET /api/v1/platform/stats/payroll`<br>`GET /api/v1/platform/payroll-stats` |
| **Platform Activity Stream**| `/admin/activity` | `super_admin` | `frontend/src/modules/platform/pages/PlatformActivityPage.tsx` | `GET /api/v1/platform/stats/activity` |
| **Platform Health Metrics** | `/admin/health` | `super_admin` | `frontend/src/modules/platform/pages/PlatformHealthPage.tsx` | `GET /api/v1/platform/stats/platform-health`<br>`GET /api/v1/platform/stats/overview` |

### 3.3 Core HR & Workforce (Module: HR)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Employee Directory** | `/employees` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/hr/pages/EmployeeListPage.tsx` | `GET /api/v1/employees`<br>`POST /api/v1/employees/export`<br>`POST /api/v1/employees/bulk-action` |
| **Add Employee Form** | `/employees/new` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx` | `POST /api/v1/employees`<br>`GET /api/v1/departments`<br>`GET /api/v1/companies/me/locations` |
| **Edit Employee Form** | `/employees/:id/edit` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx` | `GET /api/v1/employees/{id}`<br>`PUT /api/v1/employees/{id}` |
| **Employee 360° Profile** | `/employees/:id` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx` | `GET /api/v1/employees/{id}`<br>`PUT /api/v1/employees/{id}`<br>`GET /api/v1/payroll/employees/{id}/salary`<br>`GET /api/v1/payroll/employees/{id}/salary-history`<br>`GET /api/v1/payroll/employees/{id}/bank-account`<br>`PUT /api/v1/payroll/employees/{id}/bank-account`<br>`POST /api/v1/employees/{id}/terminate`<br>`GET /api/v1/employees/{id}/fnf` |
| **Department List** | `/departments` | All (`edit`: `owner`, `hr_admin`) | `frontend/src/modules/hr/pages/DepartmentListPage.tsx` | `GET /api/v1/departments`<br>`POST /api/v1/departments`<br>`PUT /api/v1/departments/{id}` |

### 3.4 Time & Leave Management (Module: Time & Leave)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Attendance Matrix** | `/attendance` | All authenticated | `frontend/src/modules/time_leave/pages/AttendancePage.tsx` | `GET /api/v1/attendance/matrix`<br>`POST /api/v1/attendance/punch`<br>`POST /api/v1/attendance/regularize` |
| **Leave Management** | `/leaves` | All authenticated | `frontend/src/modules/time_leave/pages/LeavePage.tsx` | `GET /api/v1/leaves`<br>`GET /api/v1/leaves/balances`<br>`POST /api/v1/leaves`<br>`PUT /api/v1/leaves/{id}/action` |
| **Work Shifts Roster** | `/shifts` | `owner`, `hr_admin`, `manager`, `employee` | `frontend/src/modules/time_leave/pages/ShiftsPage.tsx` | `GET /api/v1/shifts`<br>`POST /api/v1/shifts`<br>`PUT /api/v1/shifts/{id}`<br>`POST /api/v1/shifts/assign` |
| **Holidays Calendar** | `/holidays` | All (`edit`: `owner`, `hr_admin`) | `frontend/src/modules/time_leave/pages/HolidaysPage.tsx` | `GET /api/v1/holidays`<br>`POST /api/v1/holidays` |

### 3.5 Payroll & Compensation (Module: Payroll)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Payroll Setup & Configuration** | `/payroll/setup` | `owner`, `hr_admin` | `frontend/src/modules/payroll/pages/PayrollSetupPage.tsx` | `GET /api/v1/payroll/structures`<br>`POST /api/v1/payroll/structures`<br>`GET /api/v1/payroll/statutory-config`<br>`PUT /api/v1/payroll/statutory-config`<br>`POST /api/v1/payroll/employees/{id}/assign` |
| **Pay Runs & Processing** | `/payroll/run` | `owner`, `hr_admin` | `frontend/src/modules/payroll/pages/PayrollRunPage.tsx` | `GET /api/v1/payroll/runs`<br>`POST /api/v1/payroll/runs`<br>`GET /api/v1/payroll/runs/{id}`<br>`POST /api/v1/payroll/runs/{id}/approve`<br>`GET /api/v1/payroll/runs/{id}/payments`<br>`POST /api/v1/payroll/runs/{id}/payments`<br>`GET /api/v1/payroll/runs/{id}/payment-file`<br>`POST /api/v1/payroll/runs/{id}/send-payslips`<br>`POST /api/v1/payroll/runs/{id}/unlock-attendance`<br>`POST /api/v1/payroll/runs/{id}/lock-attendance` |
| **My Payslips & Bank Account** | `/payroll/payslip` | All authenticated | `frontend/src/modules/payroll/pages/MyPayslipPage.tsx` | `GET /api/v1/payroll/payslips/me`<br>`GET /api/v1/payroll/bank-account/me`<br>`PUT /api/v1/payroll/bank-account/me`<br>`GET /api/v1/employees/me/fnf` |
| **Reimbursements & Claims** | `/payroll/reimbursements` | All authenticated (`review`: `owner`, `hr_admin`, `manager`) | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx` | `GET /api/v1/payroll/reimbursements`<br>`POST /api/v1/payroll/reimbursements`<br>`PUT /api/v1/payroll/reimbursements/{id}`<br>`POST /api/v1/payroll/reimbursements/{id}/withdraw` |

### 3.6 Performance Management (Module: Performance)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Performance Cycles & PIPs** | `/performance` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx` | `GET /api/v1/performance/cycles`<br>`POST /api/v1/performance/cycles`<br>`PUT /api/v1/performance/cycles/{id}`<br>`GET /api/v1/performance/pips`<br>`POST /api/v1/performance/pips`<br>`POST /api/v1/performance/pips/{id}/checkins` |
| **Performance Summaries** | `/performance/summaries` | `owner`, `hr_admin` | `frontend/src/modules/performance/pages/PerformanceSummariesPage.tsx` | `GET /api/v1/performance/summaries`<br>`GET /api/v1/performance/cycles` |
| **My Goals (KRAs/KPIs)** | `/performance/goals` | All authenticated | `frontend/src/modules/performance/pages/MyGoalsPage.tsx` | `GET /api/v1/performance/goals`<br>`POST /api/v1/performance/goals`<br>`PUT /api/v1/performance/goals/{id}`<br>`GET /api/v1/performance/goals/{id}/history` |
| **Team Goals** | `/performance/team-goals` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/TeamGoalsPage.tsx` | `GET /api/v1/performance/goals/team`<br>`GET /api/v1/performance/goals/employee/{id}` |
| **Performance Appraisal Review** | `/performance/review/:employeeId`<br>`/performance/reviews` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/PerformanceReviewPage.tsx` | `GET /api/v1/performance/reviews/{id}`<br>`POST /api/v1/performance/reviews`<br>`PUT /api/v1/performance/reviews/{id}`<br>`POST /api/v1/performance/reviews/{id}/reopen`<br>`GET /api/v1/performance/summary/{employee_id}` |

### 3.7 Projects & Timesheets (Module: Projects)

| Feature / Screen | Route | Permitted Roles | Frontend File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Projects List** | `/projects` | All authenticated | `frontend/src/modules/projects/pages/ProjectsListPage.tsx` | `GET /api/v1/projects`<br>`POST /api/v1/projects` |
| **Project Workspace** | `/projects/:id` | All authenticated | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx` | `GET /api/v1/projects/{id}`<br>`POST /api/v1/projects/{id}/tasks`<br>`PUT /api/v1/projects/{id}/tasks/{task_id}`<br>`POST /api/v1/projects/{id}/milestones`<br>`GET /api/v1/projects/{id}/members`<br>`PUT /api/v1/projects/{id}/members/{employee_id}/rate`<br>`GET /api/v1/projects/{id}/members/{employee_id}/rates` |
| **Timesheets & Logging** | `/timesheets` | All authenticated (`approve`: `owner`, `hr_admin`, `manager`) | `frontend/src/modules/projects/pages/TimesheetsPage.tsx` | `GET /api/v1/projects/time-entries`<br>`POST /api/v1/projects/time-entries`<br>`PUT /api/v1/projects/time-entries/{id}/status` |

---

## 4. Key Interactive Modals and Dialogs Reference

| Modal / Dialog Name | Triggering Screen | Allowed Roles | Component / Source | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Attendance Unlock Reason Modal** | Lock banner on `/payroll/run` | `owner`, `hr_admin` | `PayrollRunPage.tsx` | `POST /api/v1/payroll/runs/{id}/unlock-attendance` |
| **Attendance Re-Lock Modal** | Unlock banner on `/payroll/run` | `owner`, `hr_admin` | `PayrollRunPage.tsx` | `POST /api/v1/payroll/runs/{id}/lock-attendance` |
| **Bank Account Update Modal** | Salary Profile tab on `/employees/:id` | `owner`, `hr_admin` | `EmployeeProfilePage.tsx` | `PUT /api/v1/payroll/employees/{id}/bank-account` |
| **Bank Account Self-Service Card** | Bank Account tab on `/payroll/payslip` | All Employees | `MyPayslipPage.tsx` | `PUT /api/v1/payroll/bank-account/me` |
| **Salary Revision Modal** | Compensation tab on `/employees/:id` | `owner`, `hr_admin` | `EmployeeProfilePage.tsx` | `POST /api/v1/payroll/employees/{id}/assign` |
| **Project Member Rate Modal** | Users & Team on `/projects/:id` | `owner`, `hr_admin`, `manager` | `ProjectDetailPage.tsx` | `PUT /api/v1/projects/{id}/members/{employee_id}/rate` |
| **Payslip Document Viewer Dialog** | Pay run table or My Payslips | All Permitted | `PayslipDocumentModal.tsx` | `GET /api/v1/payroll/payslips/{id}` |
| **Send Payslip Email Dialog** | Approved pay run on `/payroll/run` | `owner`, `hr_admin` | `PayrollRunPage.tsx` | `POST /api/v1/payroll/runs/{id}/send-payslips` |
| **Performance Review Reopen Modal**| Submitted review on `/performance/reviews` | `owner`, `hr_admin` | `PerformanceReviewPage.tsx` | `POST /api/v1/performance/reviews/{id}/reopen` |
| **PIP Check-in Modal** | Active PIP card on `/performance` | `owner`, `hr_admin`, `manager` | `PerformanceCyclesPage.tsx` | `POST /api/v1/performance/pips/{id}/checkins` |
| **Cycle Deadline Edit Modal** | Cycle card on `/performance` | `owner`, `hr_admin` | `PerformanceCyclesPage.tsx` | `PUT /api/v1/performance/cycles/{id}` |

---

## 5. Architectural Conventions & Security Policies

1. **Precision & Money**:
   - All financial calculations use Python `Decimal` with explicit `ROUND_HALF_UP`. Floating point math is strictly forbidden.
   - Per-project rates take precedence over salary-level hourly rates; contractor fallbacks (`(CTC/12)/160`) are explicitly labeled on payslip breakdowns.
   - For freelancers lacking rates, pay run calculation is refused with a 409 conflict naming the missing rate and employee.
2. **Bank Account Masking**:
   - Account numbers are stored encrypted using AES-256-GCM.
   - Every API response masks account numbers to the last 4 digits (e.g. `••••4417`) across all roles (employee, HR, owner).
   - Any client payload containing bullet `•` characters is rejected with 422 to prevent accidental overwrite with masked strings.
3. **Route Guard Alignment**:
   - Every route in `router.py` matching a `require_company_role` or `require_platform_role` guard must have an exact entry in `tests/security/route_policy.py`.
   - Security test suite `TZ=UTC pytest tests/security/ -q` validates that the access matrix matches live router dependencies without discrepancies.
