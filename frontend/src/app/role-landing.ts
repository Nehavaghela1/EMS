import type { UserRole } from "./auth-context";

/** Every role lands on the same placeholder dashboard for now — the
 * role-shaped `/dashboard` (page 6) and the dedicated super-admin page 5
 * are WP-14's job. Kept as a function, not a redirect to a literal string
 * everywhere, so wiring in real per-role landing pages later is a
 * one-line change here. */
export function landingPathForRole(_role: UserRole): string {
  return "/dashboard";
}
