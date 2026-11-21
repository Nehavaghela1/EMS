import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../../app/auth-context";
import { landingPathForRole } from "../../app/role-landing";

/** Shown for an address that matches no page (BUG-091), instead of a silent
 * redirect that hides the mistake. Signed-out visitors go to the login page. */
export function NotFoundPage() {
  const { status, user } = useAuth();
  if (status === "loading") {
    return (
      <div className="center-screen">
        <div className="spinner" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return (
    <div className="center-screen">
      <div className="card stack" style={{ maxWidth: 420, textAlign: "center", gap: "12px" }}>
        <h1 style={{ margin: 0 }}>Page not found</h1>
        <p className="text-muted" style={{ margin: 0 }}>
          This address does not match any page in EMS. Check the link, or go back to your home page.
        </p>
        <Link className="btn btn-primary" to={landingPathForRole(user.role)}>
          Go to my home page
        </Link>
      </div>
    </div>
  );
}
