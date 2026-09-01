import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoginPage } from "../modules/identity/pages/LoginPage";
import { DashboardPage } from "../modules/platform/pages/DashboardPage";
import { EmployeeListPage } from "../modules/hr/pages/EmployeeListPage";
import { EmployeeProfilePage } from "../modules/hr/pages/EmployeeProfilePage";
import { EmployeeFormPage } from "../modules/hr/pages/EmployeeFormPage";
import { DepartmentListPage } from "../modules/hr/pages/DepartmentListPage";
import { RequireAuth } from "../shared/components/RequireAuth";
import { RoleGuard } from "../shared/components/RoleGuard";
import type { UserRole } from "./auth-context";
import { AppLayout } from "./AppLayout";

/** Composes the three layers every protected page needs, in order:
 * signed-in at all (`RequireAuth`) → permitted for this role (`RoleGuard`,
 * optional) → the shell (`AppLayout`). */
function Protected({ roles, children }: { roles?: UserRole[]; children: ReactNode }) {
  const withLayout = <AppLayout>{children}</AppLayout>;
  return <RequireAuth>{roles ? <RoleGuard roles={roles}>{withLayout}</RoleGuard> : withLayout}</RequireAuth>;
}

const ALL_ROLES: UserRole[] = ["employee", "manager", "hr_admin", "super_admin"];

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

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
