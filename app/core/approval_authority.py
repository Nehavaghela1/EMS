import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError
from app.modules.hr.models import Employee
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import User, UserRole

DEFAULT_FORBIDDEN_MESSAGE = (
    "Unauthorized: You are not authorized to approve requests for this employee."
)


def can_approve_for(
    db: Session,
    actor: User,
    target_employee: Employee | None,
    allow_owner_super_admin_self: bool = False,
) -> bool:
    """Verifies whether `actor` has approval authority for `target_employee`.

    Rules:
    - Same 403 message whether target exists or not.
    - If target_employee is None -> ForbiddenError.
    - If actor is the target themselves:
        * If allow_owner_super_admin_self is True and actor.role in (
            UserRole.owner, UserRole.super_admin
          ): allowed.
        * Otherwise: denied.
    - hr_admin, owner, and super_admin of the same company: allowed.
    - Walk up target's reporting chain via reporting_manager_id:
        * Same company only.
        * Cycle-safe with visited set.
        * Depth limit of 20.
        * Skip inactive managers.
        * If actor's employee record matches any active manager in the chain: allowed.
    - Otherwise: denied with ForbiddenError.
    """
    if target_employee is None:
        raise ForbiddenError(DEFAULT_FORBIDDEN_MESSAGE)

    # Cross-company check: actor and target must belong to same company
    if actor.role != UserRole.super_admin and actor.company_id != target_employee.company_id:
        raise ForbiddenError(DEFAULT_FORBIDDEN_MESSAGE)

    # Self-approval check
    if target_employee.user_id == actor.id:
        if allow_owner_super_admin_self and actor.role in (UserRole.owner, UserRole.super_admin):
            return True
        raise ForbiddenError("Self-approval is forbidden. You cannot approve your own request.")

    # Executive override in same company: hr_admin, owner, super_admin
    if actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
        return True

    # Reporting hierarchy traversal
    emp_repo = EmployeeRepository(db)
    actor_emp = emp_repo.get_by_user_id(actor.company_id, actor.id)
    if actor_emp is None or not actor_emp.is_active:
        raise ForbiddenError(DEFAULT_FORBIDDEN_MESSAGE)

    curr_mgr_id = target_employee.reporting_manager_id
    visited: set[uuid.UUID] = {target_employee.id}
    depth = 0
    max_depth = 20

    while curr_mgr_id is not None and depth < max_depth:
        if curr_mgr_id in visited:
            # Cycle detected in chain, stop traversal
            break
        visited.add(curr_mgr_id)
        depth += 1

        mgr = emp_repo.get_by_id_any_status(curr_mgr_id, target_employee.company_id)
        if mgr is None:
            break

        # Active manager check
        if mgr.is_active and mgr.id == actor_emp.id:
            return True

        curr_mgr_id = mgr.reporting_manager_id

    raise ForbiddenError(DEFAULT_FORBIDDEN_MESSAGE)
