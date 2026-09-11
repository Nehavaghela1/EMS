import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth, type UserRole } from "./auth-context";

interface NavItem {
  to: string;
  label: string;
  roles: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { to: "/admin", label: "Companies", roles: ["super_admin"] },
  { to: "/dashboard", label: "Dashboard", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/attendance", label: "Attendance", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/leaves", label: "Leave", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/employees", label: "Employees", roles: ["hr_admin", "manager"] },
  { to: "/departments", label: "Departments", roles: ["hr_admin"] },
  { to: "/shifts", label: "Shifts", roles: ["hr_admin"] },
  { to: "/payroll/setup", label: "Payroll Setup", roles: ["hr_admin"] },
  { to: "/payroll/run", label: "Payroll Run", roles: ["hr_admin"] },
  { to: "/payroll/payslip", label: "My Payslips", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/payroll/reimbursements", label: "Reimbursements", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/performance", label: "Performance Cycles", roles: ["hr_admin"] },
  { to: "/performance/goals", label: "My Goals", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/projects", label: "Projects", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/timesheets", label: "Timesheets", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/settings", label: "Settings", roles: ["employee", "manager", "hr_admin", "super_admin"] },
];

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const items = NAV_ITEMS.filter((item) => user && item.roles.includes(user.role));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">EMS</div>
        {user && (user.role === "hr_admin" || user.role === "super_admin" || user.role === "manager") && (
          <div style={{ padding: "0.25rem 0.5rem 0.75rem" }}>
            <input
              type="text"
              className="input input-sm"
              placeholder="Search..."
              onKeyDown={async (e) => {
                if (e.key === "Enter") {
                  const q = e.currentTarget.value.trim();
                  if (q.length >= 2) {
                    try {
                      const { globalSearch } = await import("../modules/platform/api");
                      const res = await globalSearch(q);
                      if (res.results.length > 0) {
                        navigate(res.results[0].url);
                      } else {
                        alert(`No results found for "${q}"`);
                      }
                    } catch (err) {
                      console.error("Search error:", err);
                    }
                  }
                }
              }}
            />
          </div>
        )}
        <nav className="sidebar-nav">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => "sidebar-link" + (isActive ? " active" : "")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer stack">
          <div>{user?.email}</div>
          <div className="badge badge-muted" style={{ width: "fit-content" }}>
            {user?.role}
          </div>
          <button className="btn btn-sm btn-ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
