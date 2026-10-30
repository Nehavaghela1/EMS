"""Security Route Access Policy Specification.
Declares every HTTP endpoint in the application into:
- PUBLIC: No authentication required.
- AUTHENTICATED: Any logged-in user of the company.
- ROLES(...): Restricted to specific UserRoles via require_role(...).
"""

from typing import Any

from app.modules.identity.models import UserRole

PUBLIC = "PUBLIC"
AUTHENTICATED = "AUTHENTICATED"


def ROLES(*roles: UserRole) -> tuple[UserRole, ...]:
    return roles


# Exactly pinned list of PUBLIC routes
PUBLIC_ROUTES: set[tuple[str, str]] = {
    ("POST", "/api/v1/auth/activate"),
    ("GET", "/api/v1/auth/activate/{token}"),
    ("GET", "/api/v1/auth/check-username/{username}"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/reset-password"),
    ("POST", "/api/v1/companies/register"),
    ("GET", "/api/v1/files/download/{file_id}"),
    ("GET", "/api/v1/industry-presets"),
    ("GET", "/health"),
}


def extract_roles_from_route(route: Any) -> tuple[UserRole, ...] | None:
    """Extracts the tuple of UserRole passed to require_role(...) via closure inspection."""

    def _recurse(dependant: Any) -> list[UserRole]:
        extracted: list[UserRole] = []
        if dependant.call:
            if hasattr(dependant.call, "__closure__") and dependant.call.__closure__:
                for cell in dependant.call.__closure__:
                    val = cell.cell_contents
                    if isinstance(val, (list, tuple, set)):
                        items = list(val)
                        if items and all(isinstance(x, UserRole) for x in items):
                            extracted.extend(items)
        for sub_dep in dependant.dependencies:
            extracted.extend(_recurse(sub_dep))
        return extracted

    roles = _recurse(route.dependant)
    if not roles:
        return None

    deduped: list[UserRole] = []
    for r in roles:
        if r not in deduped:
            deduped.append(r)
    return tuple(deduped)


POLICY: dict[tuple[str, str], Any] = {
    ("GET", "/api/v1/announcements"): AUTHENTICATED,
    ("POST", "/api/v1/announcements"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("DELETE", "/api/v1/announcements/{announcement_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/attendance"): AUTHENTICATED,
    ("GET", "/api/v1/attendance/calendar"): AUTHENTICATED,
    ("POST", "/api/v1/attendance/check-in"): AUTHENTICATED,
    ("POST", "/api/v1/attendance/check-out"): AUTHENTICATED,
    ("POST", "/api/v1/attendance/export"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/attendance/export/{job_id}/download"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/attendance/regularizations/attachments/{filename}"): AUTHENTICATED,
    ("PUT", "/api/v1/attendance/regularizations/{regularization_id}/approve"): AUTHENTICATED,
    ("DELETE", "/api/v1/attendance/{attendance_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/attendance/{attendance_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/attendance/{attendance_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/attendance/{attendance_id}/regularization"): AUTHENTICATED,
    ("POST", "/api/v1/attendance/{attendance_id}/regularize"): AUTHENTICATED,
    ("GET", "/api/v1/audit-logs"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/audit-logs/export"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/audit-logs/export/{job_id}/download"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/auth/activate"): PUBLIC,
    ("GET", "/api/v1/auth/activate/{token}"): PUBLIC,
    ("POST", "/api/v1/auth/change-password"): AUTHENTICATED,
    ("GET", "/api/v1/auth/check-username/{username}"): PUBLIC,
    ("POST", "/api/v1/auth/forgot-password"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("POST", "/api/v1/auth/logout"): AUTHENTICATED,
    ("POST", "/api/v1/auth/logout-all"): AUTHENTICATED,
    ("GET", "/api/v1/auth/me"): AUTHENTICATED,
    ("POST", "/api/v1/auth/refresh"): PUBLIC,
    ("POST", "/api/v1/auth/reset-password"): PUBLIC,
    ("POST", "/api/v1/auth/switch-workspace"): AUTHENTICATED,
    ("GET", "/api/v1/auth/workspaces"): AUTHENTICATED,
    ("GET", "/api/v1/companies"): ROLES(UserRole.super_admin),
    ("GET", "/api/v1/companies/locations"): AUTHENTICATED,
    ("POST", "/api/v1/companies/locations"): ROLES(UserRole.owner, UserRole.hr_admin),
    ("PUT", "/api/v1/companies/locations/{location_id}"): ROLES(UserRole.owner, UserRole.hr_admin),
    ("DELETE", "/api/v1/companies/locations/{location_id}"): ROLES(
        UserRole.owner, UserRole.hr_admin
    ),
    ("POST", "/api/v1/companies/locations/{location_id}/reactivate"): ROLES(
        UserRole.owner, UserRole.hr_admin
    ),
    ("POST", "/api/v1/companies/locations/{location_id}/set-head-office"): ROLES(
        UserRole.owner, UserRole.hr_admin
    ),
    ("GET", "/api/v1/companies/me"): AUTHENTICATED,
    ("PUT", "/api/v1/companies/me"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/companies/notice-period-defaults"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("PUT", "/api/v1/companies/notice-period-defaults"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/companies/register"): PUBLIC,
    ("POST", "/api/v1/companies/workspaces"): ROLES(UserRole.owner, UserRole.hr_admin),
    ("GET", "/api/v1/companies/{company_id}"): ROLES(UserRole.super_admin),
    ("PUT", "/api/v1/companies/{company_id}"): ROLES(UserRole.super_admin),
    ("POST", "/api/v1/companies/{company_id}/approve"): ROLES(UserRole.super_admin),
    ("POST", "/api/v1/companies/{company_id}/deactivate"): ROLES(
        UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/companies/{company_id}/reactivate"): ROLES(UserRole.super_admin),
    ("POST", "/api/v1/companies/{company_id}/reject"): ROLES(UserRole.super_admin),
    ("GET", "/api/v1/dashboard"): AUTHENTICATED,
    ("GET", "/api/v1/departments"): AUTHENTICATED,
    ("POST", "/api/v1/departments"): ROLES(UserRole.hr_admin),
    ("DELETE", "/api/v1/departments/{department_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/departments/{department_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/departments/{department_id}"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/documents/{employee_id}"): AUTHENTICATED,
    ("GET", "/api/v1/documents/{employee_id}"): AUTHENTICATED,
    ("GET", "/api/v1/documents/{employee_id}/{document_id}/download"): AUTHENTICATED,
    ("DELETE", "/api/v1/documents/{employee_id}/{document_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.owner
    ),
    ("GET", "/api/v1/employees"): ROLES(UserRole.hr_admin, UserRole.manager, UserRole.super_admin),
    ("POST", "/api/v1/employees"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("GET", "/api/v1/employees/clearance-queue"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin
    ),
    ("GET", "/api/v1/employees/managers/search"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.super_admin
    ),
    ("GET", "/api/v1/employees/me"): AUTHENTICATED,
    ("GET", "/api/v1/employees/resignations"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/bulk/deactivate"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/bulk/reactivate"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/bulk/resend-invite"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/export"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.manager, UserRole.super_admin
    ),
    ("GET", "/api/v1/employees/export/{job_id}/download"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.manager, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/{employee_id}/reactivate"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("DELETE", "/api/v1/employees/{employee_id}"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("GET", "/api/v1/employees/{employee_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/employees/{employee_id}"): AUTHENTICATED,
    ("GET", "/api/v1/employees/{employee_id}/{section}"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/{section}"): AUTHENTICATED,
    ("PUT", "/api/v1/employees/{employee_id}/{section}/{entry_id}"): AUTHENTICATED,
    ("DELETE", "/api/v1/employees/{employee_id}/{section}/{entry_id}"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/education/{entry_id}/verify"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/education/{entry_id}/unverify"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/experience/{entry_id}/verify"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/experience/{entry_id}/unverify"): AUTHENTICATED,
    ("GET", "/api/v1/employees/{employee_id}/fnf"): AUTHENTICATED,
    ("PUT", "/api/v1/employees/{employee_id}/fnf/clearance"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/{employee_id}/resend-invite"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/{employee_id}/resignation"): AUTHENTICATED,
    ("POST", "/api/v1/employees/{employee_id}/resignation/withdraw"): AUTHENTICATED,
    ("PUT", "/api/v1/employees/{employee_id}/resignation/approve"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/{employee_id}/terminate"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("POST", "/api/v1/employees/{employee_id}/toggle-active"): ROLES(
        UserRole.hr_admin, UserRole.owner, UserRole.super_admin
    ),
    ("GET", "/api/v1/files/download/{file_id}"): PUBLIC,
    ("POST", "/api/v1/files/upload"): AUTHENTICATED,
    ("GET", "/api/v1/files/{file_id}/url"): AUTHENTICATED,
    ("GET", "/api/v1/holidays"): AUTHENTICATED,
    ("POST", "/api/v1/holidays"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/holidays/import-regional"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/holidays/regional-preview"): AUTHENTICATED,
    ("GET", "/api/v1/holidays/regions"): AUTHENTICATED,
    ("DELETE", "/api/v1/holidays/{holiday_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/industry-presets"): PUBLIC,
    ("GET", "/api/v1/jobs/{job_id}"): AUTHENTICATED,
    ("GET", "/api/v1/leave-types"): AUTHENTICATED,
    ("POST", "/api/v1/leave-types"): ROLES(UserRole.hr_admin),
    ("PUT", "/api/v1/leave-types/{leave_type_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/leaves"): AUTHENTICATED,
    ("POST", "/api/v1/leaves"): AUTHENTICATED,
    ("GET", "/api/v1/leaves/balance/{employee_id}"): AUTHENTICATED,
    ("POST", "/api/v1/leaves/balances/seed"): ROLES(UserRole.hr_admin),
    ("DELETE", "/api/v1/leaves/{leave_id}"): AUTHENTICATED,
    ("GET", "/api/v1/leaves/{leave_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/leaves/{leave_id}"): ROLES(UserRole.manager, UserRole.hr_admin),
    ("GET", "/api/v1/notifications"): AUTHENTICATED,
    ("PUT", "/api/v1/notifications/read-all"): AUTHENTICATED,
    ("PUT", "/api/v1/notifications/{notification_id}/read"): AUTHENTICATED,
    ("POST", "/api/v1/payroll/employees/{employee_id}/assign"): ROLES(
        UserRole.hr_admin, UserRole.super_admin
    ),
    ("GET", "/api/v1/payroll/employees/{employee_id}/salary"): AUTHENTICATED,
    ("GET", "/api/v1/payroll/payslips/me"): AUTHENTICATED,
    ("GET", "/api/v1/payroll/payslips/{employee_id}"): ROLES(
        UserRole.hr_admin, UserRole.super_admin
    ),
    ("GET", "/api/v1/payroll/pt-slabs"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("PUT", "/api/v1/payroll/pt-slabs"): ROLES(UserRole.super_admin),
    ("GET", "/api/v1/payroll/reimbursements"): AUTHENTICATED,
    ("POST", "/api/v1/payroll/reimbursements"): AUTHENTICATED,
    ("PUT", "/api/v1/payroll/reimbursements/{id}"): ROLES(UserRole.hr_admin, UserRole.manager),
    ("GET", "/api/v1/payroll/runs"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("POST", "/api/v1/payroll/runs"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("DELETE", "/api/v1/payroll/runs/{id}"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("GET", "/api/v1/payroll/runs/{id}"): ROLES(
        UserRole.hr_admin, UserRole.employee, UserRole.manager, UserRole.super_admin
    ),
    ("POST", "/api/v1/payroll/runs/{id}/approve"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("GET", "/api/v1/payroll/statutory-config"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("PUT", "/api/v1/payroll/statutory-config"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("GET", "/api/v1/payroll/structures"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("POST", "/api/v1/payroll/structures"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("DELETE", "/api/v1/payroll/structures/{structure_id}"): ROLES(
        UserRole.hr_admin, UserRole.super_admin
    ),
    ("GET", "/api/v1/payroll/structures/{structure_id}"): ROLES(
        UserRole.hr_admin, UserRole.super_admin
    ),
    ("PUT", "/api/v1/payroll/structures/{structure_id}"): ROLES(
        UserRole.hr_admin, UserRole.super_admin
    ),
    ("GET", "/api/v1/payroll/tax-slabs"): ROLES(UserRole.hr_admin, UserRole.super_admin),
    ("POST", "/api/v1/payroll/tax-slabs"): ROLES(UserRole.super_admin),
    ("GET", "/api/v1/performance/cycles"): AUTHENTICATED,
    ("POST", "/api/v1/performance/cycles"): ROLES(UserRole.hr_admin),
    ("PUT", "/api/v1/performance/cycles/{id}"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/performance/goals"): AUTHENTICATED,
    ("GET", "/api/v1/performance/goals/{employee_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager, UserRole.employee
    ),
    ("POST", "/api/v1/performance/goals/{goal_id}/manager-review"): ROLES(
        UserRole.hr_admin, UserRole.manager
    ),
    ("POST", "/api/v1/performance/goals/{goal_id}/self-review"): AUTHENTICATED,
    ("PUT", "/api/v1/performance/goals/{id}"): AUTHENTICATED,
    ("GET", "/api/v1/performance/pips"): AUTHENTICATED,
    ("POST", "/api/v1/performance/pips"): ROLES(
        UserRole.hr_admin, UserRole.super_admin, UserRole.manager
    ),
    ("GET", "/api/v1/performance/pips/active/{employee_id}"): AUTHENTICATED,
    ("POST", "/api/v1/performance/pips/{pip_id}/evaluate"): ROLES(
        UserRole.hr_admin, UserRole.super_admin, UserRole.manager
    ),
    ("GET", "/api/v1/performance/report"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/performance/summary/{employee_id}"): ROLES(
        UserRole.hr_admin, UserRole.manager, UserRole.employee
    ),
    ("POST", "/api/v1/performance/summary/{employee_id}"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/projects"): AUTHENTICATED,
    ("POST", "/api/v1/projects"): ROLES(UserRole.super_admin, UserRole.hr_admin, UserRole.manager),
    ("DELETE", "/api/v1/projects/milestones/{milestone_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("PUT", "/api/v1/projects/milestones/{milestone_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("DELETE", "/api/v1/projects/tasks/{task_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/projects/tasks/{task_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/projects/tasks/{task_id}"): AUTHENTICATED,
    ("GET", "/api/v1/projects/tasks/{task_id}/comments"): AUTHENTICATED,
    ("POST", "/api/v1/projects/tasks/{task_id}/comments"): AUTHENTICATED,
    ("GET", "/api/v1/projects/time-entries"): AUTHENTICATED,
    ("POST", "/api/v1/projects/time-entries"): AUTHENTICATED,
    ("DELETE", "/api/v1/projects/time-entries/{entry_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/projects/time-entries/{entry_id}"): AUTHENTICATED,
    ("POST", "/api/v1/projects/time-entries/{entry_id}/approve"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("DELETE", "/api/v1/projects/{project_id}"): ROLES(UserRole.super_admin, UserRole.hr_admin),
    ("GET", "/api/v1/projects/{project_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/projects/{project_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/projects/{project_id}/documents"): AUTHENTICATED,
    ("POST", "/api/v1/projects/{project_id}/documents"): AUTHENTICATED,
    ("DELETE", "/api/v1/projects/{project_id}/documents/{document_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/projects/{project_id}/documents/{document_id}/download"): AUTHENTICATED,
    ("GET", "/api/v1/projects/{project_id}/members"): AUTHENTICATED,
    ("POST", "/api/v1/projects/{project_id}/members"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("DELETE", "/api/v1/projects/{project_id}/members/{employee_id}"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/projects/{project_id}/milestones"): AUTHENTICATED,
    ("POST", "/api/v1/projects/{project_id}/milestones"): ROLES(
        UserRole.super_admin, UserRole.hr_admin, UserRole.manager
    ),
    ("GET", "/api/v1/projects/{project_id}/summary"): AUTHENTICATED,
    ("GET", "/api/v1/projects/{project_id}/tasks"): AUTHENTICATED,
    ("POST", "/api/v1/projects/{project_id}/tasks"): AUTHENTICATED,
    ("GET", "/api/v1/search"): AUTHENTICATED,
    ("GET", "/api/v1/shifts"): AUTHENTICATED,
    ("POST", "/api/v1/shifts"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/shifts/assigned/{employee_id}"): AUTHENTICATED,
    ("DELETE", "/api/v1/shifts/{shift_id}"): ROLES(UserRole.hr_admin),
    ("PUT", "/api/v1/shifts/{shift_id}"): ROLES(UserRole.hr_admin),
    ("POST", "/api/v1/shifts/{shift_id}/assign"): ROLES(UserRole.hr_admin),
    ("GET", "/api/v1/users/administrators"): ROLES(UserRole.owner, UserRole.hr_admin),
    ("PATCH", "/api/v1/users/{user_id}/role"): ROLES(UserRole.owner, UserRole.hr_admin),
    ("GET", "/health"): PUBLIC,
}
