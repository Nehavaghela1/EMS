# PROJECT MAP: Roles, Dashboards, Pages, Modals, and Backend API Endpoints

This document is the single source of truth for all EMS frontend pages, role permissions, dashboard entry points, modals, and backend API routes. Whenever you need to know **which file to touch as per role and dashboard**, refer to this architecture guide.

---

## 1. User Roles & Permission Hierarchy

| Role Code (`UserRole`) | Role Name | Scope & Authority | Primary Dashboard Route & Component |
| :--- | :--- | :--- | :--- |
| `super_admin` | Platform Super Administrator | Multi-tenant governance: approves/rejects new tenant companies, platform health, global configuration, compliance enforcement across all companies. | `/admin`<br>`frontend/src/modules/identity/pages/AdminDashboardPage.tsx` |
| `owner` | Primary Workspace Owner / Org Head | Company root authority: full control over company profile, branding, administrators, billing, departments, employees, shifts, leave policies, payroll, performance, and projects. Can edit own profile including First Name, Phone, and Company Contact details. Company unique code and employee code are immutable. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` (extracted to `frontend/src/modules/platform/pages/OwnerHrDashboard.tsx`) |
| `hr_admin` | HR Administrator | Workspace administration: manages employee lifecycle (add, edit, invitations, terminations), departments, leave policies & approvals, shift scheduling, payroll setup & processing, expense reimbursements, and performance cycles. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` (extracted to `frontend/src/modules/platform/pages/OwnerHrDashboard.tsx`) |
| `manager` | Department / Team Manager | People & Project leadership: manages project boards, tasks, milestones, logs/approves timesheets, conducts employee performance appraisals & PIPs, reviews team attendance and leave requests. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` |
| `employee` | Standard Employee | Self-service portal: punch-in/out attendance, apply for leaves, regularize attendance, view payslips, claim expense reimbursements, manage self-goals, log project timesheet hours, update personal contact details, and voluntary resignation. | `/dashboard`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx` |

---

## 2. Dashboard Resolution by Role

When a user logs in, the platform navigates them based on their authenticated role:

| Authenticated Role | Landed Route | Frontend Page Component File | Backend Router & Endpoints |
| :--- | :--- | :--- | :--- |
| `super_admin` | `/admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx` | `app/modules/identity/router.py`<br>`GET /api/v1/companies`<br>`POST /api/v1/companies/{id}/approve`<br>`POST /api/v1/companies/{id}/reject`<br>`GET /health` |
| `owner` | `/dashboard` | `frontend/src/modules/platform/pages/DashboardPage.tsx`<br>-> `frontend/src/modules/platform/pages/OwnerHrDashboard.tsx` | `app/modules/platform/router.py`<br>`GET /api/v1/dashboard`<br>`GET /api/v1/announcements`<br>`GET /api/v1/payroll/runs`<br>`GET /api/v1/leaves`<br>`GET /api/v1/payroll/reimbursements`<br>`GET /api/v1/employees` |
| `hr_admin` | `/dashboard` | `frontend/src/modules/platform/pages/DashboardPage.tsx`<br>-> `frontend/src/modules/platform/pages/OwnerHrDashboard.tsx` | Same as above with full administrative quick links (Employees, Payroll Runs, Leave Requests, Probations, Separations). |
| `manager` | `/dashboard` | `frontend/src/modules/platform/pages/DashboardPage.tsx` | Same as above with Manager approval metrics (Pending Leaves, Timesheet reviews, Team Headcount). |
| `employee` | `/dashboard` | `frontend/src/modules/platform/pages/DashboardPage.tsx` | Self-service view: Today's punch card (Check-in/Check-out), quick leave balance, active announcements, and assigned tasks. |

---

## 3. Comprehensive Master Route & Endpoint Map

| What You See on Screen / Feature | Route Path / Trigger | Permitted Roles | Exact Frontend File | Backend Router & Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Login Page** (Tenant Email & Password Sign-in) | `/login` | Public | `frontend/src/modules/identity/pages/LoginPage.tsx` | `app/modules/identity/router.py`<br>`POST /api/v1/auth/login` |
| **Register Company Page** (Company onboarding & workspace creator) | `/register-company` | Public | `frontend/src/modules/identity/pages/RegisterCompanyPage.tsx` | `app/modules/identity/router.py`<br>`POST /api/v1/companies/register`<br>`GET /api/v1/industry-presets` |
| **Activate Account Page** (Employee invite password setup) | `/activate/:token` | Public | `frontend/src/modules/identity/pages/ActivatePage.tsx` | `app/modules/identity/router.py`<br>`GET /api/v1/auth/activate/preview`<br>`POST /api/v1/auth/activate` |
| **Forgot / Reset Password Page** (Password recovery request) | `/forgot-password` | Public | `frontend/src/modules/identity/pages/ForgotPasswordPage.tsx` | `app/modules/identity/router.py`<br>`POST /api/v1/auth/forgot-password`<br>`POST /api/v1/auth/reset-password` |
| **Create Additional Workspace Page** (Multi-tenant company addition) | `/workspaces/new` | Logged-in Users | `frontend/src/modules/identity/pages/CreateWorkspacePage.tsx` | `app/modules/identity/router.py`<br>`POST /api/v1/auth/create-workspace` |
| **Super Admin Platform Dashboard** (Tenant review & approval hub) | `/admin` | `super_admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx` | `app/modules/identity/router.py`<br>`GET /api/v1/companies`<br>`POST /api/v1/companies/{id}/approve`<br>`POST /api/v1/companies/{id}/reject` |
| **Platform Payroll Overview** (Super admin tenant payroll stats) | `/admin/payroll` | `super_admin` | `frontend/src/modules/platform/pages/PlatformPayrollPage.tsx` | `app/modules/platform/router.py`<br>`GET /api/v1/platform/stats/payroll`<br>`GET /api/v1/platform/payroll-stats` |
| **Platform Activity Overview** (Super admin tenant activity stream) | `/admin/activity` | `super_admin` | `frontend/src/modules/platform/pages/PlatformActivityPage.tsx` | `app/modules/platform/router.py`<br>`GET /api/v1/platform/stats/activity` |
| **Platform Health Overview** (Super admin platform service health) | `/admin/health` | `super_admin` | `frontend/src/modules/platform/pages/PlatformHealthPage.tsx` | `app/modules/platform/router.py`<br>`GET /api/v1/platform/stats/platform-health`<br>`GET /api/v1/platform/stats/overview` |
| **Main Platform Dashboard** (Punch card, metrics, announcements, tasks) | `/dashboard` | `owner`, `hr_admin`, `manager`, `employee` | `frontend/src/modules/platform/pages/DashboardPage.tsx`<br>`frontend/src/modules/platform/pages/OwnerHrDashboard.tsx` | `app/modules/platform/router.py`<br>`GET /api/v1/dashboard`<br>`GET /api/v1/announcements`<br>`app/modules/time_leave/router.py`<br>`POST /api/v1/attendance/punch` |
| **Employee Directory** (Employee list, status filters, search, bulk export/actions) | `/employees` | `owner`, `hr_admin`, `manager`, `employee` | `frontend/src/modules/hr/pages/EmployeeListPage.tsx` | `app/modules/hr/router.py`<br>`GET /api/v1/employees`<br>`POST /api/v1/employees/export` |
| **Add Employee Page** (Multi-step new hire onboarding form) | `/employees/new` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx` | `app/modules/hr/router.py`<br>`POST /api/v1/employees` |
| **Edit Employee Page** (Update existing employee information) | `/employees/:id/edit` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx` | `app/modules/hr/router.py`<br>`GET /api/v1/employees/{id}`<br>`PUT /api/v1/employees/{id}` |
| **Employee 360° Profile Page** (Overview, salary, documents, leaves, timeline & FnF) | `/employees/:id` | `owner`, `hr_admin`, `manager`, `employee` (Self) | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx` | `app/modules/hr/router.py`<br>`GET /api/v1/employees/{id}`<br>`PUT /api/v1/employees/{id}`<br>`app/modules/payroll/router.py` |
| **Department Management** (Departments list, head count, create & edit) | `/departments` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/DepartmentListPage.tsx` | `app/modules/hr/router.py`<br>`GET /api/v1/departments`<br>`POST /api/v1/departments`<br>`PUT /api/v1/departments/{id}` |
| **Attendance Tracking** (Monthly calendar matrix, logs, check-in/out timestamps) | `/attendance` | All authenticated | `frontend/src/modules/time_leave/pages/AttendancePage.tsx` | `app/modules/time_leave/router.py`<br>`GET /api/v1/attendance/matrix`<br>`POST /api/v1/attendance/punch` |
| **Leave Management** (Leave balance cards, request history, approvals & apply leave) | `/leaves` | All authenticated | `frontend/src/modules/time_leave/pages/LeavePage.tsx` | `app/modules/time_leave/router.py`<br>`GET /api/v1/leaves`<br>`POST /api/v1/leaves`<br>`PUT /api/v1/leaves/{id}/action` |
| **Shift Management** (Work shifts roster, timings, grace period & assignments) | `/shifts` | `owner`, `hr_admin` | `frontend/src/modules/time_leave/pages/ShiftsPage.tsx` | `app/modules/time_leave/router.py`<br>`GET /api/v1/shifts`<br>`POST /api/v1/shifts`<br>`PUT /api/v1/shifts/{id}` |
| **Holidays Calendar** (Company holiday list, optional leaves & holiday gallery) | `/holidays` | All authenticated (`edit`: `owner`/`hr_admin`) | `frontend/src/modules/time_leave/pages/HolidaysPage.tsx` | `app/modules/time_leave/router.py`<br>`GET /api/v1/holidays`<br>`POST /api/v1/holidays` |
| **Payroll Setup & Salary Structures** (Salary templates, statutory rules, PT & tax slabs) | `/payroll/setup` | `owner`, `hr_admin` | `frontend/src/modules/payroll/pages/PayrollSetupPage.tsx` | `app/modules/payroll/router.py`<br>`GET /api/v1/payroll/structures`<br>`POST /api/v1/payroll/structures` |
| **Payroll Processing & Runs** (Monthly payroll execution, approval & payout) | `/payroll/run` | `owner`, `hr_admin` | `frontend/src/modules/payroll/pages/PayrollRunPage.tsx` | `app/modules/payroll/router.py`<br>`GET /api/v1/payroll/runs`<br>`POST /api/v1/payroll/runs` |
| **My Payslips** (Employee self-service payslip history & PDF print view) | `/payroll/payslip` | All authenticated | `frontend/src/modules/payroll/pages/MyPayslipPage.tsx` | `app/modules/payroll/router.py`<br>`GET /api/v1/payroll/payslips/me` |
| **Reimbursements & Expense Claims** (Submit expense claims, receipts & manager approval) | `/payroll/reimbursements` | All authenticated (`approve`: `owner`/`hr_admin`/`manager`) | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx` | `app/modules/payroll/router.py`<br>`GET /api/v1/payroll/reimbursements`<br>`POST /api/v1/payroll/reimbursements` |
| **Performance Appraisal Cycles** (Annual / quarterly review cycles & PIP dashboard) | `/performance` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx` | `app/modules/performance/router.py`<br>`GET /api/v1/performance/cycles`<br>`POST /api/v1/performance/cycles` |
| **Performance Summaries** (End-of-year ratings distribution, salary revisions & roster) | `/performance/summaries` | `owner`, `hr_admin` | `frontend/src/modules/performance/pages/PerformanceSummariesPage.tsx` | `app/modules/performance/router.py`<br>`GET /api/v1/performance/summaries`<br>`GET /api/v1/performance/cycles` |
| **My Performance Goals (KRAs & KPIs)** (Self-goals, quarterly targets & self-appraisal) | `/performance/goals` | All authenticated | `frontend/src/modules/performance/pages/MyGoalsPage.tsx` | `app/modules/performance/router.py`<br>`GET /api/v1/performance/goals`<br>`POST /api/v1/performance/goals` |
| **Team Performance Goals** (Department & direct report goal tracking) | `/performance/team-goals` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/TeamGoalsPage.tsx` | `app/modules/performance/router.py`<br>`GET /api/v1/performance/goals/{employee_id}` |
| **Employee Performance Review** (Manager appraisal rating, scoring & promotion summary) | `/performance/review/:employeeId` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/performance/pages/PerformanceReviewPage.tsx` | `app/modules/performance/router.py`<br>`GET /api/v1/performance/reviews/{id}`<br>`POST /api/v1/performance/reviews`<br>`GET /api/v1/performance/summary/{employee_id}` |
| **Projects Overview** (Project directory, health status, budgets & client info) | `/projects` | All authenticated | `frontend/src/modules/projects/pages/ProjectsListPage.tsx` | `app/modules/projects/router.py`<br>`GET /api/v1/projects`<br>`POST /api/v1/projects` |
| **Project Workspace & Details** (Kanban tasks, milestones, project files, team & hours) | `/projects/:id` | All authenticated | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx` | `app/modules/projects/router.py`<br>`GET /api/v1/projects/{id}`<br>`POST /api/v1/projects/{id}/tasks` |
| **Timesheets & Time Tracking** (Weekly timesheet grid, task hour logging & approval) | `/timesheets` | All authenticated (`approve`: `owner`/`hr_admin`/`manager`) | `frontend/src/modules/projects/pages/TimesheetsPage.tsx` | `app/modules/projects/router.py`<br>`GET /api/v1/projects/time-entries`<br>`POST /api/v1/projects/time-entries` |
| **Company Settings & Profile** (Admin Delegation, Profile Edit, Password, Enterprise Security, Theme Branding) | `/settings` | All authenticated (`Admins & Branding`: `owner`/`hr_admin`) | `frontend/src/modules/identity/pages/SettingsPage.tsx` | `app/modules/identity/router.py`<br>`GET /api/v1/companies/me`<br>`PUT /api/v1/companies/me`<br>`GET /api/v1/users/administrators`<br>`PUT /api/v1/users/{id}/role`<br>`POST /api/v1/auth/change-password`<br>`app/modules/hr/router.py`<br>`GET /api/v1/employees/me`<br>`PUT /api/v1/employees/{id}` |
| **Work Locations Settings** (Office locations & branch list) | `/settings/locations` | `owner`, `hr_admin` | `frontend/src/modules/settings/pages/LocationListPage.tsx` | `app/modules/identity/router.py`<br>`GET /api/v1/companies/me/locations` |
| **Add Work Location** (Create office branch location) | `/settings/locations/new` | `owner`, `hr_admin` | `frontend/src/modules/settings/pages/LocationFormPage.tsx` | `app/modules/identity/router.py`<br>`POST /api/v1/companies/me/locations` |

---

## 4. Modals and Popups Reference Table

| Modal / Popup Name | Triggering Screen | Allowed Roles | Exact Component / File | Backend Endpoints |
| :--- | :--- | :--- | :--- | :--- |
| **Company Details & Review Modal** | Click company on `/admin` | `super_admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx` | `GET /api/v1/companies/{id}` |
| **Reject Company Modal** | "Reject" button on `/admin` | `super_admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx` | `POST /api/v1/companies/{id}/reject` |
| **Assign HR Admin Modal** | "+ Assign HR Admin" button on `/settings` | `owner` | `frontend/src/modules/identity/pages/SettingsPage.tsx` | `GET /api/v1/employees`<br>`PUT /api/v1/users/{id}/role` |
| **Revoke Admin Access Modal** | "Revoke Admin Access" button on `/settings` | `owner` | `frontend/src/modules/identity/pages/SettingsPage.tsx` | `PUT /api/v1/users/{id}/role` |
| **Quick Edit Designation Modal** | "Edit Designation" inside 360° Profile or Table on `/employees` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeListPage.tsx`<br>`frontend/src/modules/hr/pages/EmployeeProfilePage.tsx` | `PUT /api/v1/employees/{id}` |
| **Voluntary Resignation Modal** | "+ Request Resignation" on `/settings` | `employee`, `manager`, `hr_admin` (Non-owner) | `frontend/src/modules/identity/pages/SettingsPage.tsx` | `POST /api/v1/employees/me/resignation` |
| **Involuntary Termination Modal** | Exit / Terminate button on `/employees/:id` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx` | `POST /api/v1/employees/{id}/terminate` |
| **Salary Revision Modal** | "Revise Salary" button on `/employees/:id` | `owner`, `hr_admin` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx` | `POST /api/v1/payroll/employees/{id}/assign` |
| **Payslip Document Viewer Modal / Dialog** | "View Payslip" on `/payroll/payslip` or `/employees/:id` | All permitted | `frontend/src/modules/payroll/components/PayslipDocumentModal.tsx` | `GET /api/v1/payroll/payslips/{id}` |
| **Attendance Regularization Modal** | "Regularize" button on `/attendance` or `/dashboard` | All authenticated | `frontend/src/modules/time_leave/components/RegularizeAttendanceModal.tsx` | `POST /api/v1/attendance/regularize` |
| **Leave Approval / Rejection Modal** | Review action on `/leaves` | `owner`, `hr_admin`, `manager` | `frontend/src/modules/time_leave/pages/LeavePage.tsx` | `PUT /api/v1/leaves/{id}/action` |
| **Assign Shift Modal** | "Assign Shift" button on `/shifts` | `owner`, `hr_admin` | `frontend/src/modules/time_leave/pages/ShiftsPage.tsx` | `POST /api/v1/shifts/assign` |
| **Create / Edit Task Modal** | "+ Add Task" button on `/projects/:id` | All project members | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx` | `POST /api/v1/projects/{id}/tasks` |
| **Log Timesheet Hours Modal** | "+ Log Hours" on `/timesheets` | All authenticated | `frontend/src/modules/projects/pages/TimesheetsPage.tsx` | `POST /api/v1/projects/time-entries` |
| **Submit Reimbursement Claim Modal** | "+ New Claim" on `/payroll/reimbursements` | All authenticated | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx` | `POST /api/v1/payroll/reimbursements` |

---

## 5. Quick Decision Guide: "Which file do I touch as per role and dashboard?"

1. **Super Admin Platform Features:**
   - Look at `frontend/src/modules/identity/pages/AdminDashboardPage.tsx`.
   - Platform stats pages: `frontend/src/modules/platform/pages/PlatformPayrollPage.tsx`, `PlatformActivityPage.tsx`, `PlatformHealthPage.tsx`.
   - Backend logic lives in `app/modules/identity/router.py` (Companies CRUD, platform admin queries) and `app/modules/platform/router.py`.

2. **Owner & HR Workspace Administration:**
   - Executive & HR Dashboard: `frontend/src/modules/platform/pages/OwnerHrDashboard.tsx`.
   - Performance Summaries: `frontend/src/modules/performance/pages/PerformanceSummariesPage.tsx`.
   - Employee lifecycle: `frontend/src/modules/hr/pages/EmployeeListPage.tsx` & `EmployeeFormPage.tsx`.
   - Settings & Admin Delegation: `frontend/src/modules/identity/pages/SettingsPage.tsx`.
   - Payroll Setup & Execution: `frontend/src/modules/payroll/pages/PayrollSetupPage.tsx` & `PayrollRunPage.tsx`.
   - Backend logic lives in `app/modules/hr/router.py`, `app/modules/payroll/router.py`, `app/modules/identity/router.py`, `app/modules/performance/router.py`.

3. **Manager People & Projects Portal:**
   - Team Goals: `frontend/src/modules/performance/pages/TeamGoalsPage.tsx`.
   - Performance Reviews: `frontend/src/modules/performance/pages/PerformanceReviewPage.tsx`.
   - Manager Dashboard content: `frontend/src/modules/platform/pages/DashboardPage.tsx` (`ManagerDashboardContent`).
   - Project & Timesheet approvals: `frontend/src/modules/projects/pages/ProjectDetailPage.tsx` & `TimesheetsPage.tsx`.

4. **Employee Self-Service Features:**
   - Attendance & Punch: `frontend/src/modules/time_leave/pages/AttendancePage.tsx` and `TodayAttendanceCard.tsx`.
   - Personal Profile & Password: `frontend/src/modules/identity/pages/SettingsPage.tsx` (`ProfileSection`).
   - Payslips: `frontend/src/modules/payroll/pages/MyPayslipPage.tsx`.
   - Leaves: `frontend/src/modules/time_leave/pages/LeavePage.tsx`.
   - My Goals: `frontend/src/modules/performance/pages/MyGoalsPage.tsx`.
