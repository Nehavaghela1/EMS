# PROJECT MAP: Pages, Modals, and Backend API Routes

A complete reference mapping of every page, modal, and route across the EMS platform in a 3-column table.

| What I see on screen | Browser URL / Trigger | Exact file path in frontend/ and backend/ |
| :--- | :--- | :--- |
| **Login Page** (Tenant Email & Password Sign-in) | `/login` | `frontend/src/modules/identity/pages/LoginPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Register Company Page** (Company onboarding & workspace creator) | `/register-company` | `frontend/src/modules/identity/pages/RegisterCompanyPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Activate Account Page** (Employee invite password setup) | `/activate/:token` | `frontend/src/modules/identity/pages/ActivatePage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Forgot / Reset Password Page** (Password recovery request) | `/forgot-password` | `frontend/src/modules/identity/pages/ForgotPasswordPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Create Additional Workspace Page** (Multi-tenant company addition) | `/workspaces/new` | `frontend/src/modules/identity/pages/CreateWorkspacePage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Platform Dashboard** (Attendance punch card, metrics, announcements, task feed) | `/dashboard` | `frontend/src/modules/platform/pages/DashboardPage.tsx`<br>`backend/app/modules/platform/router.py`<br>`backend/app/modules/time_leave/router.py` |
| **Super Admin Dashboard** (Platform-wide tenant companies list & review) | `/admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Employee Directory** (Employee list table, status filter, search & export) | `/employees` | `frontend/src/modules/hr/pages/EmployeeListPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Add Employee Page** (Multi-step new hire onboarding form) | `/employees/new` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Edit Employee Page** (Update existing employee information) | `/employees/:id/edit` | `frontend/src/modules/hr/pages/EmployeeFormPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Employee 360° Profile Page** (Overview, salary, documents, leaves, timeline & FnF) | `/employees/:id` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx`<br>`backend/app/modules/hr/router.py`<br>`backend/app/modules/payroll/router.py` |
| **Department Management** (Departments list, head count, create & edit) | `/departments` | `frontend/src/modules/hr/pages/DepartmentListPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Attendance Tracking** (Monthly calendar, daily logs, check-in/out timestamps) | `/attendance` | `frontend/src/modules/time_leave/pages/AttendancePage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Leave Management** (Leave balance cards, request history, approvals & apply leave) | `/leaves` | `frontend/src/modules/time_leave/pages/LeavePage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Shift Management** (Work shifts roster, timings, grace period & assignments) | `/shifts` | `frontend/src/modules/time_leave/pages/ShiftsPage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Holidays Calendar** (Company holiday list, optional leaves & holiday gallery) | `/holidays` | `frontend/src/modules/time_leave/pages/HolidaysPage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Payroll Setup & Salary Structures** (Salary templates, statutory rules, PT & tax slabs) | `/payroll/setup` | `frontend/src/modules/payroll/pages/PayrollSetupPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Payroll Processing & Runs** (Monthly payroll execution, approval & disbursement) | `/payroll/run` | `frontend/src/modules/payroll/pages/PayrollRunPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **My Payslips** (Employee self-service payslip history & PDF print view) | `/payroll/payslip` | `frontend/src/modules/payroll/pages/MyPayslipPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Reimbursements & Expense Claims** (Submit expense claims, receipts & manager approval) | `/payroll/reimbursements` | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Performance Appraisal Cycles** (Annual / quarterly review cycles & PIP dashboard) | `/performance` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **My Performance Goals (KRAs & KPIs)** (Self-goals, quarterly targets & self-appraisal) | `/performance/goals` | `frontend/src/modules/performance/pages/MyGoalsPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Employee Performance Review** (Manager appraisal rating, scoring & promotion summary) | `/performance/review/:employeeId` | `frontend/src/modules/performance/pages/PerformanceReviewPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Projects Overview** (Project directory, health status, budgets & client info) | `/projects` | `frontend/src/modules/projects/pages/ProjectsListPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Project Workspace & Details** (Kanban tasks, milestones, project files, team & hours) | `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Timesheets & Time Tracking** (Weekly timesheet grid, task hour logging & approval) | `/timesheets` | `frontend/src/modules/projects/pages/TimesheetsPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Company Settings & Profile** (Organization info, branding, resignations, security) | `/settings` | `frontend/src/modules/identity/pages/SettingsPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Work Locations Settings** (Office locations & branch list) | `/settings/locations` | `frontend/src/modules/settings/pages/LocationListPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Add Work Location** (Create office branch location) | `/settings/locations/new` | `frontend/src/modules/settings/pages/LocationFormPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Company Details & Profile Modal** (View / edit company profile & contact info) | Popup on `/admin` or `/dashboard` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx`<br>`frontend/src/modules/platform/pages/DashboardPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Reject Company Modal** (Super Admin rejection reason popup) | Popup on `/admin` | `frontend/src/modules/identity/pages/AdminDashboardPage.tsx`<br>`backend/app/modules/identity/router.py` |
| **Quick Edit Designation Modal** (Inline title/designation updater) | Popup on `/employees` | `frontend/src/modules/hr/pages/EmployeeListPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Involuntary Termination Modal** (HR employee termination & exit date prompt) | Popup on `/employees/:id` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Salary Revision Modal** (Employee CTC change, hike percentage & revision date) | Popup on `/employees/:id` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Payslip Document Viewer Modal** (Printable salary slip modal view) | Popup on `/employees/:id` or `/payroll/run` | `frontend/src/modules/hr/pages/EmployeeProfilePage.tsx`<br>`frontend/src/modules/payroll/components/PayslipDocumentModal.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Voluntary Resignation Modal** (Employee self-resignation & notice period request) | Popup on `/settings` | `frontend/src/modules/identity/pages/SettingsPage.tsx`<br>`backend/app/modules/hr/router.py` |
| **Attendance Regularization Modal** (Employee apply / Manager review regularization) | Popup on `/attendance` or `/dashboard` | `frontend/src/modules/time_leave/components/RegularizeAttendanceModal.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Company Holiday Schedule Viewer Modal** (Calendar modal previewing all paid off-days) | Popup on `/attendance` | `frontend/src/modules/time_leave/components/AttendanceCalendar.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Leave Approval / Rejection Modal** (Manager decision note on leave request) | Popup on `/leaves` | `frontend/src/modules/time_leave/pages/LeavePage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Assign Shift Modal** (Assign shift timing to employee or department) | Popup on `/shifts` | `frontend/src/modules/time_leave/pages/ShiftsPage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Add Custom Holiday Modal** (HR new custom calendar holiday creation) | Popup on `/holidays` | `frontend/src/modules/time_leave/pages/HolidaysPage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Import Statutory Holidays Gallery Modal** (Regional holiday batch importer) | Popup on `/holidays` | `frontend/src/modules/time_leave/pages/HolidaysPage.tsx`<br>`backend/app/modules/time_leave/router.py` |
| **Create / Edit Project Modal** (Project code, name, dates, budget & manager) | Popup on `/projects` | `frontend/src/modules/projects/pages/ProjectsListPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Create / Edit Task Modal** (Project task title, assignee, priority & due date) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Task Comments & Discussion Modal** (Collaborative activity & comments thread) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Create / Edit Milestone Modal** (Project delivery milestones & deliverables) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Edit Project Workspace Modal** (Project metadata, status & description updater) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Assign Team Member Modal** (Add employee with role & hourly billing rate to project) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Log Project Hours Modal** (Quick timesheet entry for project task) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Upload Project Document Modal** (Attach specifications and deliverables) | Popup on `/projects/:id` | `frontend/src/modules/projects/pages/ProjectDetailPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Reject Timesheet Entry Modal** (Manager feedback & rejection note for logged hours) | Popup on `/timesheets` | `frontend/src/modules/projects/pages/TimesheetsPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Log Timesheet Hours Modal** (Submit daily / weekly billable hours) | Popup on `/timesheets` | `frontend/src/modules/projects/pages/TimesheetsPage.tsx`<br>`backend/app/modules/projects/router.py` |
| **Assign Salary Structure Modal** (Assign compensation template to employee) | Popup on `/payroll/setup` | `frontend/src/modules/payroll/pages/PayrollSetupPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Initiate Payroll Run Modal** (Select year, month & payment date to run payroll) | Popup on `/payroll/run` | `frontend/src/modules/payroll/pages/PayrollRunPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Submit Reimbursement Claim Modal** (Upload receipt, amount, category & claim description) | Popup on `/payroll/reimbursements` | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Review Reimbursement Claim Modal** (HR approve / reject claim with remarks) | Popup on `/payroll/reimbursements` | `frontend/src/modules/payroll/pages/ReimbursementsPage.tsx`<br>`backend/app/modules/payroll/router.py` |
| **Create Performance Cycle Modal** (Set evaluation window, cycle name & period) | Popup on `/performance` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Initiate PIP Modal** (Put underperforming employee on Performance Improvement Plan) | Popup on `/performance` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Evaluate PIP Modal** (Final outcome decision: Successful, Extended, or Terminated) | Popup on `/performance` | `frontend/src/modules/performance/pages/PerformanceCyclesPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Set Performance Goals Modal** (Employee / Manager define quarterly key goals) | Popup on `/performance/goals` | `frontend/src/modules/performance/pages/MyGoalsPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Self Evaluation Modal** (Employee self-appraisal rating & achievement notes) | Popup on `/performance/goals` | `frontend/src/modules/performance/pages/MyGoalsPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Edit Goal Modal** (Update goal parameters, metrics & weightage) | Popup on `/performance/goals` | `frontend/src/modules/performance/pages/MyGoalsPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Rate Goal Modal** (Manager scoring, competency review & feedback) | Popup on `/performance/review/:employeeId` | `frontend/src/modules/performance/pages/PerformanceReviewPage.tsx`<br>`backend/app/modules/performance/router.py` |
| **Generic Confirmation Dialog Modal** (Destructive action confirmation popup) | Global / Shared Popup | `frontend/src/shared/components/ConfirmDialog.tsx`<br>*(Client-side shared component)* |
| **Health Check Endpoint** (Database & Redis health status) | `/health` | `backend/app/main.py` |
| **API Documentation (Swagger UI)** | `/docs` | `backend/app/main.py` |
| **API Alternative Documentation (ReDoc)** | `/redoc` | `backend/app/main.py` |
| **OpenAPI Specification JSON** | `/openapi.json` | `backend/app/main.py` |
| **Auth APIs** (Login, refresh, logout, password change & switch workspace) | `/api/v1/auth/*` | `backend/app/modules/identity/router.py` |
| **Company & Location Management APIs** (Companies CRUD, approve/reject & locations) | `/api/v1/companies/*` | `backend/app/modules/identity/router.py` |
| **User Role Assignment APIs** (Role updates & admin user listings) | `/api/v1/users/*` | `backend/app/modules/identity/router.py` |
| **Department APIs** (Department CRUD & employee headcounts) | `/api/v1/departments/*` | `backend/app/modules/hr/router.py` |
| **Employee Directory & Lifecycle APIs** (CRUD, invite, toggle active, terminate, FnF) | `/api/v1/employees/*` | `backend/app/modules/hr/router.py` |
| **Attendance APIs** (Check-in, check-out, monthly matrix calendar & regularization) | `/api/v1/attendance/*` | `backend/app/modules/time_leave/router.py` |
| **Shift Management APIs** (Shift schedules CRUD & employee assignment) | `/api/v1/shifts/*` | `backend/app/modules/time_leave/router.py` |
| **Holiday Calendar APIs** (Holidays CRUD & statutory gallery importer) | `/api/v1/holidays/*` | `backend/app/modules/time_leave/router.py` |
| **Leave Management APIs** (Leave policy types, leave applications & balances) | `/api/v1/leave-types/*`<br>`/api/v1/leaves/*` | `backend/app/modules/time_leave/router.py` |
| **Salary Structure & Statutory Config APIs** (Templates, PF/ESI configs & PT/Tax slabs) | `/api/v1/payroll/structures/*`<br>`/api/v1/payroll/statutory-config`<br>`/api/v1/payroll/pt-slabs`<br>`/api/v1/payroll/tax-slabs` | `backend/app/modules/payroll/router.py` |
| **Payroll Processing APIs** (Payroll batch runs, approvals & slip generation) | `/api/v1/payroll/runs/*`<br>`/api/v1/payroll/employees/*/assign` | `backend/app/modules/payroll/router.py` |
| **Employee Payslip APIs** (My payslips & employee payslip records) | `/api/v1/payroll/payslips/*` | `backend/app/modules/payroll/router.py` |
| **Expense Reimbursement APIs** (Reimbursement claims submission & approvals) | `/api/v1/payroll/reimbursements/*` | `backend/app/modules/payroll/router.py` |
| **Performance Review & Appraisal APIs** (Cycles, goals, reviews & PIP evaluations) | `/api/v1/performance/*` | `backend/app/modules/performance/router.py` |
| **Projects & Tasks APIs** (Projects CRUD, members, tasks, milestones & files) | `/api/v1/projects/*` | `backend/app/modules/projects/router.py` |
| **Timesheets APIs** (Time entry logging, hours updates & manager approvals) | `/api/v1/projects/time-entries/*` | `backend/app/modules/projects/router.py` |
| **Platform Announcements & Notifications APIs** (Broadcasts & user notifications) | `/api/v1/announcements/*`<br>`/api/v1/notifications/*` | `backend/app/modules/platform/router.py` |
| **Platform Documents & Storage APIs** (File upload, secure download & document attach) | `/api/v1/files/*`<br>`/api/v1/documents/*` | `backend/app/modules/platform/router.py` |
| **Global Quick Search API** (Search employees, projects, departments) | `/api/v1/search` | `backend/app/modules/platform/router.py` |
| **Audit Logs APIs** (Audit trail log listings & CSV export) | `/api/v1/audit-logs/*` | `backend/app/modules/platform/router.py` |
| **Background Jobs API** (Async background tasks & worker status) | `/api/v1/jobs/*` | `backend/app/modules/platform/router.py` |
| **Industry Presets API** (Public industry presets & default roles configuration) | `/api/v1/industry-presets` | `backend/app/modules/platform/router.py` |
