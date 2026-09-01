import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth, type UserRole } from "../../app/auth-context";
import { landingPathForRole } from "../../app/role-landing";

interface Props {
  roles: UserRole[];
  children: ReactNode;
}

/** Wraps a route; a signed-in user whose role isn't permitted is sent to
 * their own landing page, never a blank screen (Spec 14.4). Must be used
 * inside a route already covered by `RequireAuth`, which handles the
 * unauthenticated case. */
export function RoleGuard({ roles, children }: Props) {
  const { user } = useAuth();
  if (!user) return null;
  if (!roles.includes(user.role)) {
    return <Navigate to={landingPathForRole(user.role)} replace />;
  }
  return children;
}
