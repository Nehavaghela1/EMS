import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../app/auth-context";

/** Redirects an unauthenticated visitor to `/login`, preserving where they
 * were headed so login can send them back. Renders nothing while the
 * boot-time refresh (Spec 14.2) is still in flight, rather than flashing
 * the login page for a user who is actually still signed in. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    );
  }
  if (status === "unauthenticated") {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return children;
}
