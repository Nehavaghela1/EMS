from app.modules.identity.models import UserRole

HR_LEVEL_ROLES: tuple[UserRole, ...] = (
    UserRole.hr_admin,
    UserRole.owner,
    UserRole.super_admin,
)

HR_OR_MANAGER_ROLES: tuple[UserRole, ...] = (*HR_LEVEL_ROLES, UserRole.manager)
