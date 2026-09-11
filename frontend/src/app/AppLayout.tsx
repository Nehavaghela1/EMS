import { useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth, type UserRole } from "./auth-context";

interface SubItem {
  to: string;
  label: string;
  roles: UserRole[];
}

interface NavSection {
  id: string;
  label: string;
  icon: (active: boolean) => ReactNode;
  to?: string; // Direct link if no children
  children?: SubItem[];
  roles: UserRole[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    id: "admin",
    label: "Admin Console",
    to: "/admin",
    roles: ["super_admin"],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="16" height="20" x="4" y="2" rx="2" ry="2"/>
        <path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>
      </svg>
    ),
  },
  {
    id: "dashboard",
    label: "Dashboard",
    to: "/dashboard",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>
      </svg>
    ),
  },
  {
    id: "employees",
    label: "Employees",
    roles: ["hr_admin", "manager"],
    children: [
      { to: "/employees", label: "Directory", roles: ["hr_admin", "manager"] },
      { to: "/departments", label: "Departments", roles: ["hr_admin"] },
    ],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
    ),
  },
  {
    id: "time_attendance",
    label: "Leave & Attendance",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    children: [
      { to: "/attendance", label: "Attendance", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/leaves", label: "Leave Requests", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/shifts", label: "Shift Schedule", roles: ["hr_admin"] },
    ],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    ),
  },
  {
    id: "payroll",
    label: "Payroll",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    children: [
      { to: "/payroll/run", label: "Pay Runs", roles: ["hr_admin"] },
      { to: "/payroll/setup", label: "Payroll Setup", roles: ["hr_admin"] },
      { to: "/payroll/payslip", label: "My Payslips", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/payroll/reimbursements", label: "Reimbursements", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>
      </svg>
    ),
  },
  {
    id: "performance",
    label: "Performance",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    children: [
      { to: "/performance", label: "Cycles & Review", roles: ["hr_admin"] },
      { to: "/performance/goals", label: "My Goals", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
      </svg>
    ),
  },
  {
    id: "projects",
    label: "Projects & Timesheet",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    children: [
      { to: "/projects", label: "Projects", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/timesheets", label: "Timesheets", roles: ["employee", "manager", "hr_admin", "super_admin"] },
    ],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      </svg>
    ),
  },
  {
    id: "settings",
    label: "Settings",
    to: "/settings",
    roles: ["employee", "manager", "hr_admin", "super_admin"],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    ),
  },
];

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const role = user?.role ?? "employee";

  // Filter sections visible to current role
  const visibleSections = NAV_SECTIONS.filter((sec) => sec.roles.includes(role))
    .map((sec) => ({
      ...sec,
      children: sec.children?.filter((c) => c.roles.includes(role)),
    }))
    .filter((sec) => !sec.children || sec.children.length > 0);

  // Keep section open if current pathname matches any of its children
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {
      payroll: true,
      time_attendance: true,
      employees: true,
    };
    for (const sec of visibleSections) {
      if (sec.children?.some((c) => location.pathname.startsWith(c.to))) {
        initial[sec.id] = true;
      }
    }
    return initial;
  });

  function toggleSection(id: string) {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell" style={{ display: "flex", minHeight: "100vh" }}>
      {/* Zoho HRMS Style Dark Sidebar */}
      <aside
        className="sidebar"
        style={{
          width: "235px",
          background: "#1e293b",
          color: "#f8fafc",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
          borderRight: "1px solid #334155",
          padding: 0,
        }}
      >
        {/* Brand header */}
        <div
          style={{
            padding: "1rem 1.15rem",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            display: "flex",
            alignItems: "center",
            gap: "0.65rem",
          }}
        >
          <div
            style={{
              width: "32px",
              height: "32px",
              background: "#2563eb",
              borderRadius: "8px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontWeight: 800,
              fontSize: "1rem",
            }}
          >
            E
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: "0.95rem", color: "#f8fafc", letterSpacing: "-0.01em" }}>
              EMS Pro
            </div>
            <div style={{ fontSize: "0.68rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              HRMS & Payroll
            </div>
          </div>
        </div>

        {/* Search */}
        {user && (user.role === "hr_admin" || user.role === "super_admin" || user.role === "manager") && (
          <div style={{ padding: "0.6rem 0.85rem 0.4rem" }}>
            <input
              type="text"
              placeholder="Search..."
              style={{
                width: "100%",
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: "6px",
                color: "#e2e8f0",
                fontSize: "0.78rem",
                padding: "0.38rem 0.65rem",
                outline: "none",
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
        )}

        {/* Navigation items */}
        <nav style={{ flex: 1, overflowY: "auto", padding: "0.5rem 0.6rem" }}>
          {visibleSections.map((sec) => {
            const hasChildren = Boolean(sec.children && sec.children.length > 0);
            const isOpen = Boolean(openSections[sec.id]);
            const isChildActive = sec.children?.some((c) =>
              c.to === "/dashboard"
                ? location.pathname === "/dashboard"
                : location.pathname.startsWith(c.to)
            );
            const isSelfActive = sec.to ? location.pathname === sec.to : false;
            const isSectionActive = Boolean(isSelfActive || isChildActive);

            // Direct link item (like Dashboard or Settings)
            if (!hasChildren && sec.to) {
              return (
                <NavLink
                  key={sec.id}
                  to={sec.to}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.65rem",
                    padding: "0.48rem 0.75rem",
                    borderRadius: "6px",
                    color: isSelfActive ? "#ffffff" : "#94a3b8",
                    background: isSelfActive ? "#2563eb" : "transparent",
                    textDecoration: "none",
                    fontSize: "0.84rem",
                    fontWeight: isSelfActive ? 600 : 500,
                    marginBottom: "3px",
                    transition: "all 0.15s ease",
                  }}
                >
                  {sec.icon(isSelfActive)}
                  <span>{sec.label}</span>
                </NavLink>
              );
            }

            // Group / Parent item with sub-pages hidden inside
            return (
              <div key={sec.id} style={{ marginBottom: "3px" }}>
                <button
                  type="button"
                  onClick={() => toggleSection(sec.id)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.48rem 0.75rem",
                    borderRadius: "6px",
                    color: isSectionActive ? "#ffffff" : "#94a3b8",
                    background: "transparent",
                    border: "none",
                    fontSize: "0.84rem",
                    fontWeight: isSectionActive ? 600 : 500,
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.15s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.65rem" }}>
                    {sec.icon(isSectionActive)}
                    <span>{sec.label}</span>
                  </div>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{
                      transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
                      transition: "transform 0.2s ease",
                      color: "#64748b",
                    }}
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                {/* Sub-items (hidden until expanded) */}
                {isOpen && sec.children && (
                  <div
                    style={{
                      paddingLeft: "1.85rem",
                      paddingTop: "2px",
                      paddingBottom: "4px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "2px",
                    }}
                  >
                    {sec.children.map((child) => {
                      const isActive = location.pathname.startsWith(child.to);
                      return (
                        <NavLink
                          key={child.to}
                          to={child.to}
                          style={{
                            display: "block",
                            padding: "0.38rem 0.65rem",
                            borderRadius: "5px",
                            fontSize: "0.8rem",
                            color: isActive ? "#ffffff" : "#94a3b8",
                            background: isActive ? "rgba(37, 99, 235, 0.4)" : "transparent",
                            textDecoration: "none",
                            fontWeight: isActive ? 600 : 400,
                            transition: "background 0.15s ease",
                          }}
                        >
                          {child.label}
                        </NavLink>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* User footer */}
        <div
          style={{
            padding: "0.85rem",
            borderTop: "1px solid rgba(255, 255, 255, 0.08)",
            background: "#0f172a",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem" }}>
            <div
              style={{
                width: "30px",
                height: "30px",
                borderRadius: "50%",
                background: "#334155",
                color: "#e2e8f0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: "0.8rem",
              }}
            >
              {user?.email?.charAt(0).toUpperCase()}
            </div>
            <div style={{ minWidth: 0, overflow: "hidden" }}>
              <div
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 600,
                  color: "#f1f5f9",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {user?.email}
              </div>
              <div style={{ fontSize: "0.68rem", color: "#94a3b8" }}>
                {user?.role?.replace("_", " ")}
              </div>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={handleLogout}
            style={{
              width: "100%",
              color: "#ef4444",
              border: "1px solid rgba(239, 68, 68, 0.2)",
              fontSize: "0.75rem",
              padding: "0.3rem",
            }}
          >
            Log out
          </button>
        </div>
      </aside>

      {/* Main Page Content */}
      <main className="main" style={{ flex: 1, minWidth: 0, padding: "1.5rem 2rem", background: "var(--color-bg)" }}>
        {children}
      </main>
    </div>
  );
}
