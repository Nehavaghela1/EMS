import { useState, useEffect, useRef, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth, type UserRole } from "./auth-context";
import { useTimer } from "./timer-context";
import { getUserWorkspaces, switchWorkspace } from "../modules/identity/api";
import { NotificationBell } from "../shared/components/NotificationBell";

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
    roles: ["hr_admin", "manager", "super_admin"],
    children: [
      { to: "/employees", label: "Directory", roles: ["hr_admin", "manager", "super_admin"] },
      { to: "/departments", label: "Departments", roles: ["hr_admin", "super_admin"] },
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
      { to: "/shifts", label: "Shift Schedule", roles: ["employee", "manager", "hr_admin", "super_admin"] },
      { to: "/holidays", label: "Holidays", roles: ["employee", "manager", "hr_admin", "super_admin"] },
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
      { to: "/payroll/run", label: "Pay Runs", roles: ["hr_admin", "super_admin"] },
      { to: "/payroll/setup", label: "Payroll Setup", roles: ["hr_admin", "super_admin"] },
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
      { to: "/performance", label: "Cycles & Review", roles: ["hr_admin", "super_admin"] },
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
  const { user, logout, establishSession } = useAuth();
  const { activeTimer, elapsedSeconds, formatTime, stopTimer } = useTimer();
  const navigate = useNavigate();
  const location = useLocation();

  const role = user?.role ?? "employee";

  const [selectedWorkspace, setSelectedWorkspace] = useState<string>(user?.company_id || "");
  const [isWorkspaceDropdownOpen, setIsWorkspaceDropdownOpen] = useState(false);
  const workspaceDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (user?.company_id && !selectedWorkspace) {
      setSelectedWorkspace(user.company_id);
    }
  }, [user?.company_id, selectedWorkspace]);

  // Close workspace dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (workspaceDropdownRef.current && !workspaceDropdownRef.current.contains(event.target as Node)) {
        setIsWorkspaceDropdownOpen(false);
      }
    }
    if (isWorkspaceDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isWorkspaceDropdownOpen]);

  const workspacesQuery = useQuery({
    queryKey: ["user-workspaces"],
    queryFn: () => getUserWorkspaces(),
    enabled: !!user,
  });

  const activeCompanyName =
    workspacesQuery.data?.find((c) => c.id === selectedWorkspace)?.name ||
    user?.company_name ||
    "EMS Workspace";

  const activeCompanyCode =
    workspacesQuery.data?.find((c) => c.id === selectedWorkspace)?.code ||
    user?.company_code ||
    "";

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

  // Derive breadcrumb context for top navbar
  let currentSectionLabel = "";
  let currentPageLabel = "";

  for (const sec of visibleSections) {
    if (sec.to && (location.pathname === sec.to || (sec.to !== "/" && location.pathname.startsWith(sec.to)))) {
      currentSectionLabel = sec.label;
      break;
    }
    if (sec.children) {
      const matchChild = sec.children.find((c) =>
        c.to === location.pathname || (c.to !== "/" && location.pathname.startsWith(c.to))
      );
      if (matchChild) {
        currentSectionLabel = sec.label;
        currentPageLabel = matchChild.label;
        break;
      }
    }
  }

  if (!currentSectionLabel && location.pathname.startsWith("/employees/")) {
    currentSectionLabel = "Employees";
    currentPageLabel = location.pathname.includes("/edit") ? "Edit Employee" : "Profile Details";
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell" style={{ display: "flex", height: "100vh", width: "100vw", overflow: "hidden" }}>
      {/* Zoho HRMS Style Dark Sidebar - fixed height 100% */}
      <aside
        className="sidebar"
        style={{
          width: "235px",
          height: "100%",
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

        {/* Docked Workspace Switcher (Slack / Linear / Notion style) */}
        {user && (
          <div
            ref={workspaceDropdownRef}
            style={{
              padding: "0.55rem 0.75rem",
              borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              background: "rgba(15, 23, 42, 0.45)",
              position: "relative",
            }}
          >
            <div style={{ fontSize: "0.62rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "#94a3b8", fontWeight: 700, marginBottom: "5px", paddingLeft: "2px" }}>
              Active Workspace
            </div>
            {user.role !== "employee" ? (
              <>
                <button
                  type="button"
                  onClick={() => setIsWorkspaceDropdownOpen((prev) => !prev)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "6px 10px",
                    background: isWorkspaceDropdownOpen ? "#1e293b" : "rgba(30, 41, 59, 0.7)",
                    border: `1px solid ${isWorkspaceDropdownOpen ? "#6366f1" : "rgba(255, 255, 255, 0.12)"}`,
                    borderRadius: "6px",
                    color: "#f1f5f9",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.15s ease",
                    boxShadow: isWorkspaceDropdownOpen ? "0 0 0 2px rgba(99, 102, 241, 0.25)" : "none",
                  }}
                  title="Switch or manage active workspace"
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        width: "22px",
                        height: "22px",
                        borderRadius: "5px",
                        background: "#3b82f6",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "0.75rem",
                        fontWeight: 700,
                        color: "#fff",
                        flexShrink: 0,
                      }}
                    >
                      {activeCompanyName.charAt(0).toUpperCase()}
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#f8fafc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {activeCompanyName}
                      </div>
                      {activeCompanyCode && (
                        <div style={{ fontSize: "0.65rem", color: "#94a3b8", fontFamily: "monospace" }}>
                          {activeCompanyCode}
                        </div>
                      )}
                    </div>
                  </div>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="#94a3b8"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{
                      flexShrink: 0,
                      marginLeft: "6px",
                      transform: isWorkspaceDropdownOpen ? "rotate(180deg)" : "rotate(0deg)",
                      transition: "transform 0.15s ease",
                    }}
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {isWorkspaceDropdownOpen && (
                  <div
                    style={{
                      position: "absolute",
                      top: "calc(100% + 4px)",
                      left: "0.75rem",
                      right: "0.75rem",
                      background: "#0f172a",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)",
                      zIndex: 100,
                      overflow: "hidden",
                      animation: "fadeIn 0.12s ease-out",
                    }}
                  >
                    <div
                      style={{
                        padding: "8px 10px 6px",
                        fontSize: "0.65rem",
                        fontWeight: 700,
                        color: "#64748b",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
                      }}
                    >
                      Organizations & Workspaces
                    </div>

                    <div style={{ maxHeight: "200px", overflowY: "auto", padding: "4px" }}>
                      {/* Active / Current Company */}
                      <div
                        onClick={() => {
                          setSelectedWorkspace(user.company_id);
                          setIsWorkspaceDropdownOpen(false);
                        }}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "7px 9px",
                          borderRadius: "6px",
                          background: selectedWorkspace === user.company_id ? "rgba(99, 102, 241, 0.15)" : "transparent",
                          cursor: "pointer",
                          transition: "background 0.15s ease",
                        }}
                        onMouseEnter={(e) => {
                          if (selectedWorkspace !== user.company_id) {
                            e.currentTarget.style.background = "rgba(255, 255, 255, 0.05)";
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (selectedWorkspace !== user.company_id) {
                            e.currentTarget.style.background = "transparent";
                          }
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                          <span style={{ fontSize: "0.85rem" }}>🏢</span>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "#f8fafc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {user.company_name || "Primary Tenant"}
                            </div>
                            {user.company_code && (
                              <div style={{ fontSize: "0.64rem", color: "#94a3b8", fontFamily: "monospace" }}>
                                {user.company_code}
                              </div>
                            )}
                          </div>
                        </div>
                        {selectedWorkspace === user.company_id && (
                          <span style={{ color: "#38bdf8", fontWeight: 700, fontSize: "0.85rem", paddingLeft: "6px" }} title="Currently Active">
                            ✓
                          </span>
                        )}
                      </div>

                      {/* Other Accessible Companies */}
                      {workspacesQuery.data
                        ?.filter((c) => c.id !== user.company_id)
                        .map((c) => {
                          const isCurrent = selectedWorkspace === c.id;
                          return (
                            <div
                              key={c.id}
                              onClick={async () => {
                                setSelectedWorkspace(c.id);
                                setIsWorkspaceDropdownOpen(false);
                                try {
                                  const tokenData = await switchWorkspace(c.id);
                                  await establishSession(tokenData.access_token);
                                  navigate("/dashboard");
                                } catch (e) {
                                  console.error(e);
                                  alert("Failed to switch workspace.");
                                }
                              }}
                              style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "7px 9px",
                                borderRadius: "6px",
                                background: isCurrent ? "rgba(99, 102, 241, 0.15)" : "transparent",
                                cursor: "pointer",
                                transition: "background 0.15s ease",
                              }}
                              onMouseEnter={(e) => {
                                if (!isCurrent) e.currentTarget.style.background = "rgba(255, 255, 255, 0.05)";
                              }}
                              onMouseLeave={(e) => {
                                if (!isCurrent) e.currentTarget.style.background = "transparent";
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                                <span style={{ fontSize: "0.85rem" }}>🏢</span>
                                <div style={{ minWidth: 0 }}>
                                  <div style={{ fontSize: "0.78rem", fontWeight: 500, color: "#cbd5e1", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {c.name}
                                  </div>
                                  <div style={{ fontSize: "0.64rem", color: "#64748b", fontFamily: "monospace" }}>
                                    {c.code}
                                  </div>
                                </div>
                              </div>
                              {isCurrent && (
                                <span style={{ color: "#38bdf8", fontWeight: 700, fontSize: "0.85rem", paddingLeft: "6px" }} title="Currently Active">
                                  ✓
                                </span>
                              )}
                            </div>
                          );
                        })}
                    </div>

                    {/* Bottom Action: Create New Workspace / Company */}
                    <div
                      style={{
                        borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                        padding: "6px 4px 4px",
                        background: "rgba(15, 23, 42, 0.7)",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setIsWorkspaceDropdownOpen(false);
                          navigate("/workspaces/new");
                        }}
                        style={{
                          width: "100%",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "8px",
                          padding: "8px 10px",
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          color: "#4f46e5",
                          background: "#e0e7ff",
                          border: "1px solid #c7d2fe",
                          borderRadius: "6px",
                          cursor: "pointer",
                          textAlign: "center",
                          transition: "background 0.15s ease",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#c7d2fe")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "#e0e7ff")}
                      >
                        <span style={{ fontSize: "0.95rem", lineHeight: 1 }}>+</span>
                        <span>Create New Workspace / Company</span>
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div
                style={{
                  fontSize: "0.78rem",
                  fontWeight: 600,
                  color: "#cbd5e1",
                  display: "flex",
                  alignItems: "center",
                  gap: "7px",
                  padding: "6px 8px",
                  background: "rgba(30, 41, 59, 0.4)",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 255, 255, 0.06)",
                }}
              >
                <div
                  style={{
                    width: "20px",
                    height: "20px",
                    borderRadius: "4px",
                    background: "#3b82f6",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "0.7rem",
                    fontWeight: 700,
                    color: "#fff",
                    flexShrink: 0,
                  }}
                >
                  {activeCompanyName.charAt(0).toUpperCase()}
                </div>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {activeCompanyName}
                </span>
              </div>
            )}
          </div>
        )}

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

      {/* Main Page Content Area */}
      <div className="app-content-wrapper" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
        {/* Enterprise Top Bar: Workspace Switcher & Context */}
        <header
          style={{
            height: "54px",
            background: "#ffffff",
            borderBottom: "1px solid var(--color-border, #e2e8f0)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 1.5rem",
            zIndex: 40,
          }}
        >
          {/* Breadcrumb Navigation / Current Context */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem" }}>
            <span style={{ color: "var(--color-muted, #64748b)", fontWeight: 500 }}>
              {currentSectionLabel || "Portal"}
            </span>
            {currentPageLabel && (
              <>
                <span style={{ color: "var(--color-border, #cbd5e1)", fontSize: "0.75rem" }}>/</span>
                <span style={{ fontWeight: 600, color: "var(--color-heading, #0f172a)" }}>
                  {currentPageLabel}
                </span>
              </>
            )}
          </div>

          {/* User Quick Info & Notification Bell */}
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <NotificationBell />
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--color-muted, #64748b)",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#10b981" }} />
              {user?.role === "super_admin" ? "Platform Super Admin" : user?.role?.replace("_", " ")}
            </span>
          </div>
        </header>

        {/* Global Live Stopwatch Top Bar (Zoho / Jira style) */}
        {activeTimer && (
          <div
            style={{
              background: "linear-gradient(90deg, #0f172a, #1e1b4b)",
              color: "#fff",
              padding: "0.55rem 1.5rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              borderBottom: "1px solid rgba(99, 102, 241, 0.4)",
              boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
              zIndex: 50,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px", minWidth: 0 }}>
              <span
                style={{
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  background: "#10b981",
                  display: "inline-block",
                  boxShadow: "0 0 8px #10b981",
                  animation: "pulse 1.5s infinite",
                }}
              />
              <span style={{ fontSize: "0.82rem", color: "#a5b4fc", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Active Task Timer:
              </span>
              <span
                style={{
                  fontSize: "0.9rem",
                  fontWeight: 600,
                  color: "#f8fafc",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: "400px",
                }}
                title={activeTimer.taskTitle}
              >
                {activeTimer.taskTitle}
              </span>
              {activeTimer.projectName && (
                <span
                  style={{
                    fontSize: "0.75rem",
                    padding: "2px 8px",
                    background: "rgba(99, 102, 241, 0.25)",
                    border: "1px solid rgba(129, 140, 248, 0.3)",
                    borderRadius: "4px",
                    color: "#c7d2fe",
                  }}
                >
                  📁 {activeTimer.projectName}
                </span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
              <div
                style={{
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                  fontSize: "1.05rem",
                  fontWeight: 700,
                  color: "#34d399",
                  background: "rgba(0,0,0,0.35)",
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: "1px solid rgba(52, 211, 153, 0.3)",
                  letterSpacing: "1px",
                }}
              >
                ⏱️ {formatTime(elapsedSeconds)}
              </div>
              <button
                type="button"
                onClick={() => {
                  const stopped = stopTimer();
                  if (stopped) {
                    navigate(`/timesheets?autoOpen=true&projectId=${stopped.projectId}&taskId=${stopped.taskId}&seconds=${elapsedSeconds}`);
                  }
                }}
                style={{
                  background: "#ef4444",
                  color: "#fff",
                  border: "none",
                  borderRadius: "5px",
                  padding: "4px 12px",
                  fontSize: "0.82rem",
                  fontWeight: 700,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  boxShadow: "0 1px 4px rgba(239, 68, 68, 0.4)",
                }}
                title="Stop Timer & Log Hours"
              >
                ⏹ Stop & Log
              </button>
            </div>
          </div>
        )}

        <main className="main" style={{ flex: 1, minWidth: 0, padding: "1.5rem 2rem", background: "var(--color-bg)", overflowY: "auto" }}>
          <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
