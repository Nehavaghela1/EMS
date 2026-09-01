import { useAuth, type UserRole } from "../../app/auth-context";

export function useRole(): UserRole | null {
  return useAuth().user?.role ?? null;
}

export function useHasRole(...roles: UserRole[]): boolean {
  const role = useRole();
  return role !== null && roles.includes(role);
}
