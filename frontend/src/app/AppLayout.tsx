import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth, type UserRole } from "./auth-context";

interface NavItem {
  to: string;
  label: string;
  roles: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { to: "/admin", label: "Admin", roles: ["super_admin"] },
  { to: "/dashboard", label: "Dashboard", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/attendance", label: "Attendance", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/leaves", label: "Leave", roles: ["employee", "manager", "hr_admin", "super_admin"] },
  { to: "/employees", label: "Employees", roles: ["hr_admin", "manager"] },
  { to: "/departments", label: "Departments", roles: ["hr_admin"] },
  { to: "/shifts", label: "Shifts", roles: ["hr_admin"] },
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
