import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth, type UserRole } from "./auth-context";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  roles: UserRole[];
}

interface NavGroup {
  groupName: string;
  icon?: string;
  roles?: UserRole[];
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    groupName: "Main",
    items: [
      { to: "/admin", label: "Admin Console", icon: "🏢", roles: ["super_admin"] },
      { to: "/dashboard", label: "Dashboard", icon: "📊", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
  },
  {
    groupName: "People & Org",
    roles: ["hr_admin", "manager", "super_admin"],
    items: [
      { to: "/employees", label: "Employees", icon: "👥", roles: ["hr_admin", "manager"] },
      { to: "/departments", label: "Departments", icon: "🏛️", roles: ["hr_admin"] },
    ],
  },
  {
    groupName: "Time & Leave",
    items: [
      { to: "/attendance", label: "Attendance", icon: "⏱️", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/leaves", label: "Leave", icon: "🌴", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/shifts", label: "Shifts", icon: "🔄", roles: ["hr_admin"] },
    ],
  },
  {
    groupName: "Payroll & Compensation",
    items: [
      { to: "/payroll/run", label: "Pay Runs", icon: "💳", roles: ["hr_admin"] },
      { to: "/payroll/setup", label: "Payroll Setup", icon: "⚙️", roles: ["hr_admin"] },
      { to: "/payroll/payslip", label: "My Payslips", icon: "📄", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/payroll/reimbursements", label: "Reimbursements", icon: "🏷️", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
  },
  {
    groupName: "Performance & Work",
    items: [
      { to: "/performance", label: "Cycles & Reviews", icon: "🎯", roles: ["hr_admin"] },
      { to: "/performance/goals", label: "My Goals", icon: "⭐", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/projects", label: "Projects", icon: "📁", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/timesheets", label: "Timesheets", icon: "⏳", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
  },
  {
    groupName: "Configuration",
    items: [
      { to: "/settings", label: "Settings", icon: "⚙️", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
  },
];

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const role = user?.role ?? "employee";

  // Filter groups and items that the current user is permitted to see
  const visibleGroups = NAV_GROUPS.map((grp) => ({
    ...grp,
    items: grp.items.filter((item) => item.roles.includes(role)),
  })).filter((grp) => grp.items.length > 0);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span style={{ fontSize: "1.25rem" }}>⚡</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "1rem", lineHeight: "1.2" }}>EMS Pro</div>
              <div className="text-muted" style={{ fontSize: "0.68rem", letterSpacing: "0.02em" }}>
                PAYROLL & HR
              </div>
            </div>
          </div>
        </div>

        {user && (user.role === "hr_admin" || user.role === "super_admin" || user.role === "manager") && (
          <div style={{ padding: "0.35rem 0.6rem 0.65rem" }}>
            <div style={{ position: "relative" }}>
              <input
                type="text"
                className="input input-sm"
                placeholder="🔍 Search employee / page..."
                style={{
                  paddingLeft: "0.75rem",
                  fontSize: "0.8rem",
                  width: "100%",
                  borderRadius: "6px",
                }}
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
          </div>
        )}

        <nav className="sidebar-nav" style={{ overflowY: "auto", flex: 1, paddingRight: "4px" }}>
          {visibleGroups.map((grp) => (
            <div key={grp.groupName} className="nav-group-section" style={{ marginBottom: "14px" }}>
              <div
                className="nav-group-label"
                style={{
                  fontSize: "0.68rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--color-text-muted)",
                  fontWeight: 600,
                  padding: "0 0.65rem 0.35rem",
                }}
              >
                {grp.groupName}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                {grp.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      "sidebar-link flex items-center gap-2" + (isActive ? " active" : "")
                    }
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.55rem",
                      padding: "0.42rem 0.65rem",
                      borderRadius: "6px",
                      fontSize: "0.84rem",
                    }}
                  >
                    <span style={{ fontSize: "0.95rem", width: "1.1rem", textAlign: "center" }}>
                      {item.icon}
                    </span>
                    <span>{item.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer stack" style={{ marginTop: "auto", paddingTop: "0.75rem" }}>
          <div className="flex items-center gap-2" style={{ overflow: "hidden" }}>
            <div
              style={{
                width: "28px",
                height: "28px",
                borderRadius: "50%",
                background: "var(--color-primary-bg, #eff6ff)",
                color: "var(--color-primary, #2563eb)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: "0.75rem",
                flexShrink: 0,
              }}
            >
              {user?.email?.charAt(0).toUpperCase() ?? "U"}
            </div>
            <div style={{ minWidth: 0, overflow: "hidden" }}>
              <div
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {user?.email}
              </div>
              <div className="badge badge-muted" style={{ fontSize: "0.65rem", padding: "1px 5px" }}>
                {user?.role}
              </div>
            </div>
          </div>
          <button
            className="btn btn-sm btn-ghost"
            onClick={handleLogout}
            style={{ width: "100%", textAlign: "center", marginTop: "4px" }}
          >
            Log out
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
