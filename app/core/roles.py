from app.modules.identity.models import UserRole

HR_LEVEL_ROLES: tuple[UserRole, ...] = (
    UserRole.hr_admin,
    UserRole.owner,
    UserRole.super_admin,
)
