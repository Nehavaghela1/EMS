import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoginPage } from "../modules/identity/pages/LoginPage";
import { RegisterCompanyPage } from "../modules/identity/pages/RegisterCompanyPage";
import { ActivatePage } from "../modules/identity/pages/ActivatePage";
import { ForgotPasswordPage } from "../modules/identity/pages/ForgotPasswordPage";
import { DashboardPage } from "../modules/platform/pages/DashboardPage";
import { EmployeeListPage } from "../modules/hr/pages/EmployeeListPage";
import { EmployeeProfilePage } from "../modules/hr/pages/EmployeeProfilePage";
import { EmployeeFormPage } from "../modules/hr/pages/EmployeeFormPage";
import { DepartmentListPage } from "../modules/hr/pages/DepartmentListPage";
import { RequireAuth } from "../shared/components/RequireAuth";
import { RoleGuard } from "../shared/components/RoleGuard";
import { PublicOnly } from "../shared/components/PublicOnly";
import type { UserRole } from "./auth-context";
import { AppLayout } from "./AppLayout";

/** Composes the three layers every protected page needs, in order:
 * signed-in at all (`RequireAuth`) → permitted for this role (`RoleGuard`,
 * optional) → the shell (`AppLayout`). */
function Protected({ roles, children }: { roles?: UserRole[]; children: ReactNode }) {
  const withLayout = <AppLayout>{children}</AppLayout>;
  return <RequireAuth>{roles ? <RoleGuard roles={roles}>{withLayout}</RoleGuard> : withLayout}</RequireAuth>;
}

/** Every public route (Spec 14.3 pages 1-4) is wrapped the same way: a
 * signed-in user hitting it is sent to their landing page instead of
 * seeing a form for a session they already have. */
function Public({ children }: { children: ReactNode }) {
  return <PublicOnly>{children}</PublicOnly>;
}

const ALL_ROLES: UserRole[] = ["employee", "manager", "hr_admin", "super_admin"];

export function AppRouter() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <Public>
            <LoginPage />
          </Public>
        }
      />
      <Route
        path="/register-company"
        element={
          <Public>
            <RegisterCompanyPage />
          </Public>
        }
      />
      <Route
        path="/activate/:token"
        element={
          <Public>
            <ActivatePage />
          </Public>
        }
      />
      <Route
        path="/forgot-password"
        element={
          <Public>
            <ForgotPasswordPage />
          </Public>
        }
      />

      <Route
        path="/dashboard"
        element={
          <Protected roles={ALL_ROLES}>
            <DashboardPage />
          </Protected>
        }
      />

      <Route
        path="/employees"
        element={
          <Protected roles={["hr_admin", "manager"]}>
            <EmployeeListPage />
          </Protected>
        }
      />
      <Route
        path="/employees/new"
        element={
          <Protected roles={["hr_admin"]}>
            <EmployeeFormPage />
          </Protected>
        }
      />
      <Route
        path="/employees/:id/edit"
        element={
          <Protected roles={["hr_admin"]}>
            <EmployeeFormPage />
          </Protected>
        }
      />
      <Route
        path="/employees/:id"
        element={
          <Protected roles={["hr_admin", "manager"]}>
            <EmployeeProfilePage />
          </Protected>
        }
      />

      <Route
        path="/departments"
        element={
          <Protected roles={["hr_admin"]}>
            <DepartmentListPage />
          </Protected>
        }
      />

      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
