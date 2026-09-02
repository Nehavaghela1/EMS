import type { UserRole } from "./auth-context";

/** `super_admin` lands on the dedicated admin page (5, `/admin`) — the
 * actionable one, with pending companies and approve/reject. Every other
 * role lands on the role-shaped dashboard (6, `/dashboard`). Kept as a
 * function, not a redirect to a literal string everywhere, so a future
 * per-role landing page is a one-line change here. */
export function landingPathForRole(role: UserRole): string {
  return role === "super_admin" ? "/admin" : "/dashboard";
}
