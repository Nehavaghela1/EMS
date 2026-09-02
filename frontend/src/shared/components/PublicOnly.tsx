import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../app/auth-context";
import { landingPathForRole } from "../../app/role-landing";

/**
 * Wraps a public route (login, register, activate, forgot-password) — a
 * signed-in user hitting one is sent to their own landing page instead of
 * seeing a form for a session they already have. Mirrors `RequireAuth`'s
 * loading-state handling so the boot-time refresh (Spec 14.2) doesn't
 * flash the wrong screen while it's still in flight.
 */
export function PublicOnly({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();

  if (status === "loading") {
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    );
  }
  if (status === "authenticated" && user) {
    return <Navigate to={landingPathForRole(user.role)} replace />;
  }
  return children;
}
