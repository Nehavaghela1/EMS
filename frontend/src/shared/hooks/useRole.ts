import { useAuth, type UserRole } from "../../app/auth-context";

export function useRole(): UserRole | null {
  return useAuth().user?.role ?? null;
}

export function useHasRole(...roles: UserRole[]): boolean {
  const role = useRole();
  if (role === null) return false;
  // Mirror the backend's require_role elevation: owner inherits all hr_admin rights.
  const effective = [...roles];
  if (roles.includes("hr_admin") && !effective.includes("owner")) {
    effective.push("owner");
  }
  return effective.includes(role);
}
