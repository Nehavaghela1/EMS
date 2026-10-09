import { useState, useEffect, useRef, useCallback, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth, type UserRole } from "./auth-context";
import { useTimer } from "./timer-context";
import { getUserWorkspaces, switchWorkspace } from "../modules/identity/api";
import { fetchDashboard } from "../modules/platform/api";
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
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>
      </svg>
    ),
  },
  {
    id: "employees",
    label: "Employees",
    to: "/employees",
    roles: ["hr_admin", "manager", "super_admin", "owner"],
    icon: (active) => (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? "currentColor" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
    ),
  },
  {
    id: "time_attendance",
    label: "Leave & Attendance",
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
    children: [
      { to: "/attendance", label: "Attendance", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
      { to: "/leaves", label: "Leave Requests", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
      { to: "/shifts", label: "Shift Schedule", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
      { to: "/holidays", label: "Holidays", roles: ["hr_admin", "super_admin", "owner"] },
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
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
    children: [
      { to: "/payroll/run", label: "Pay Runs", roles: ["hr_admin", "super_admin", "owner"] },
      { to: "/payroll/setup", label: "Payroll Setup", roles: ["hr_admin", "super_admin", "owner"] },
      { to: "/payroll/payslip", label: "My Payslips", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
      { to: "/payroll/reimbursements", label: "Reimbursements", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
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
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
    children: [
      { to: "/performance", label: "Cycles & Review", roles: ["hr_admin", "super_admin", "owner"] },
      { to: "/performance/goals", label: "My Goals", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
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
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
    children: [
      { to: "/projects", label: "Projects", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
      { to: "/timesheets", label: "Timesheets", roles: ["employee", "manager", "hr_admin", "super_admin", "owner"] },
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
    roles: ["employee", "manager", "hr_admin", "super_admin", "owner"],
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

  // ── Profile pill dropdown (top-bar) ─────────────────────────────────────
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleOut(e: MouseEvent) {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setProfileMenuOpen(false);
      }
    }
    if (profileMenuOpen) document.addEventListener("mousedown", handleOut);
    return () => document.removeEventListener("mousedown", handleOut);
  }, [profileMenuOpen]);

  // ── Zoho People / Coworkers Quick Directory Popover ───────────────────────
  const [peopleMenuOpen, setPeopleMenuOpen] = useState(false);
  const peopleMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handlePeopleOut(e: MouseEvent) {
      if (peopleMenuRef.current && !peopleMenuRef.current.contains(e.target as Node)) {
        setPeopleMenuOpen(false);
      }
    }
    if (peopleMenuOpen) document.addEventListener("mousedown", handlePeopleOut);
    return () => document.removeEventListener("mousedown", handlePeopleOut);
  }, [peopleMenuOpen]);

  // ── Zoho 9-Dots Apps Suite Launcher Popover ──────────────────────────────
  const [appsMenuOpen, setAppsMenuOpen] = useState(false);
  const appsMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleAppsOut(e: MouseEvent) {
      if (appsMenuRef.current && !appsMenuRef.current.contains(e.target as Node)) {
        setAppsMenuOpen(false);
      }
    }
    if (appsMenuOpen) document.addEventListener("mousedown", handleAppsOut);
    return () => document.removeEventListener("mousedown", handleAppsOut);
  }, [appsMenuOpen]);

  // ── Mobile Responsive Sidebar Drawer ─────────────────────────────────────
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  // Auto-close mobile sidebar drawer on navigation
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);


  // ── Top Navbar Employee Search ──────────────────────────────────────────
  const [topEmployeeSearch, setTopEmployeeSearch] = useState("");
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    if (location.pathname === "/employees") {
      setTopEmployeeSearch(searchParams.get("q") || "");
    } else {
      setTopEmployeeSearch("");
    }
  }, [location.pathname, location.search]);

  // ── Global search (⌘K) ──────────────────────────────────────────────────
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  const openSearch = useCallback((initialQuery?: string) => {
    setSearchOpen(true);
    setSearchQ(typeof initialQuery === "string" ? initialQuery : "");
    setTimeout(() => {
      if (searchInputRef.current) {
        searchInputRef.current.focus();
        if (typeof initialQuery === "string" && initialQuery) {
          searchInputRef.current.setSelectionRange(initialQuery.length, initialQuery.length);
        }
      }
    }, 50);
  }, []);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        openSearch();
      }
      if (e.key === "Escape") setSearchOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [openSearch]);

  const SEARCH_SHORTCUTS = [
    { label: "Employee Directory", icon: "👥", to: "/employees" },
    { label: "Leave Requests", icon: "📋", to: "/leaves" },
    { label: "Attendance", icon: "🕐", to: "/attendance" },
    { label: "Pay Runs", icon: "💰", to: "/payroll/run" },
    { label: "My Payslips", icon: "🧾", to: "/payroll/payslip" },
    { label: "Performance Goals", icon: "🎯", to: "/performance/goals" },
    { label: "Timesheets", icon: "⏱️", to: "/timesheets" },
    { label: "Settings", icon: "⚙️", to: "/settings" },
    { label: "Departments", icon: "🏢", to: "/departments" },
    { label: "Shift Schedule", icon: "📅", to: "/shifts" },
    { label: "Holidays", icon: "🎉", to: "/holidays" },
    { label: "Reimbursements", icon: "🧾", to: "/payroll/reimbursements" },
  ];
  const filteredShortcuts = searchQ.trim()
    ? SEARCH_SHORTCUTS.filter((s) =>
        s.label.toLowerCase().includes(searchQ.toLowerCase())
      )
    : SEARCH_SHORTCUTS;

  // ── Pending approvals badge (admin/owner roles) ──────────────────────────
  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
    enabled: ["owner", "hr_admin", "super_admin"].includes(role),
    staleTime: 60_000,
  });
  const pendingLeaves: number =
    (dashboardQuery.data?.data as any)?.pending_leave_requests ?? 0;

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
    <>
    <div className="app-shell" style={{ display: "flex", height: "100vh", width: "100vw", overflow: "hidden" }}>
      {/* Mobile Drawer Backdrop */}
      {isMobileMenuOpen && (
        <div
          className="mobile-drawer-backdrop"
          onClick={() => setIsMobileMenuOpen(false)}
        />
      )}

      {/* Zoho HRMS Style Dark Sidebar */}
      <aside
        className={`sidebar ${isMobileMenuOpen ? "mobile-open" : ""}`}
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
        {/* Top Company / Organization Header (Zoho Style) */}
        <div
          ref={workspaceDropdownRef}
          style={{
            position: "relative",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            background: "rgba(15, 23, 42, 0.5)",
          }}
        >
          {user && user.role !== "employee" ? (
            <>
              <button
                type="button"
                onClick={() => setIsWorkspaceDropdownOpen((prev) => !prev)}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0.85rem 1rem",
                  background: isWorkspaceDropdownOpen ? "rgba(30, 41, 59, 0.9)" : "transparent",
                  border: "none",
                  color: "#f8fafc",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "background 0.15s ease",
                }}
                title="Switch company / organization"
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      width: "34px",
                      height: "34px",
                      borderRadius: "8px",
                      background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "1rem",
                      fontWeight: 800,
                      color: "#fff",
                      flexShrink: 0,
                      boxShadow: "0 2px 4px rgba(0, 0, 0, 0.2)",
                    }}
                  >
                    {activeCompanyName.charAt(0).toUpperCase()}
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        fontSize: "0.92rem",
                        fontWeight: 700,
                        color: "#f8fafc",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        letterSpacing: "-0.01em",
                      }}
                    >
                      {activeCompanyName}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "2px" }}>
                      {activeCompanyCode && (
                        <span
                          style={{
                            fontSize: "0.65rem",
                            color: "#94a3b8",
                            fontFamily: "monospace",
                            background: "rgba(255, 255, 255, 0.08)",
                            padding: "1px 5px",
                            borderRadius: "4px",
                          }}
                        >
                          {activeCompanyCode}
                        </span>
                      )}
                      <span style={{ fontSize: "0.66rem", color: "#64748b" }}>Organization</span>
                    </div>
                  </div>
                </div>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#94a3b8"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    flexShrink: 0,
                    marginLeft: "8px",
                    transform: isWorkspaceDropdownOpen ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "transform 0.15s ease",
                  }}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {/* Zoho Style Organization / Workspace Dropdown */}
              {isWorkspaceDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: "0.5rem",
                    right: "0.5rem",
                    background: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.5)",
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
                display: "flex",
                alignItems: "center",
                gap: "10px",
                padding: "0.85rem 1rem",
              }}
            >
              <div
                style={{
                  width: "34px",
                  height: "34px",
                  borderRadius: "8px",
                  background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1rem",
                  fontWeight: 800,
                  color: "#fff",
                  flexShrink: 0,
                  boxShadow: "0 2px 4px rgba(0, 0, 0, 0.2)",
                }}
              >
                {activeCompanyName.charAt(0).toUpperCase()}
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div
                  style={{
                    fontSize: "0.92rem",
                    fontWeight: 700,
                    color: "#f8fafc",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    letterSpacing: "-0.01em",
                  }}
                >
                  {activeCompanyName}
                </div>
                {activeCompanyCode && (
                  <div style={{ fontSize: "0.65rem", color: "#94a3b8", fontFamily: "monospace", marginTop: "2px" }}>
                    {activeCompanyCode}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Global Navigation Search (Sidebar First Search) */}
        {user && (
          <div style={{ padding: "0.6rem 0.85rem 0.4rem" }}>
            <div
              id="sidebar-global-search"
              style={{
                position: "relative",
                width: "100%",
              }}
            >
              <input
                type="text"
                placeholder=""
                onClick={() => openSearch("")}
                onChange={(e) => {
                  const val = e.target.value;
                  openSearch(val);
                  e.target.value = "";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    openSearch((e.target as HTMLInputElement).value);
                    (e.target as HTMLInputElement).value = "";
                  }
                }}
                style={{
                  width: "100%",
                  background: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  color: "#e2e8f0",
                  fontSize: "0.78rem",
                  padding: "0.38rem 0.65rem 0.38rem 1.85rem",
                  outline: "none",
                }}
              />
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#64748b"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{
                  position: "absolute",
                  left: "9px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  pointerEvents: "none",
                }}
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
            </div>
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
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "linear-gradient(135deg, #475569, #334155)",
                color: "#e2e8f0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: "0.82rem",
                flexShrink: 0,
              }}
            >
              {(user?.employee?.first_name || user?.email || "U").charAt(0).toUpperCase()}
            </div>
            <div style={{ minWidth: 0, overflow: "hidden" }}>
              <div
                style={{
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  color: "#f1f5f9",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {user?.employee
                  ? `${user.employee.first_name} ${user.employee.last_name || ""}`.trim()
                  : user?.email}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "0.66rem", color: "#94a3b8" }}>
                {user?.employee?.employee_code && (
                  <span style={{ fontFamily: "monospace", color: "#38bdf8", fontWeight: 600 }}>
                    {user.employee.employee_code}
                  </span>
                )}
                <span>•</span>
                <span>{user?.role?.replace("_", " ")}</span>
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
          className="app-header"
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
          {/* Left/Center: Mobile Hamburger + Zoho Employee Search Bar */}
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1, maxWidth: "560px" }}>
            {/* Mobile Hamburger Toggle Button */}
            <button
              type="button"
              id="btn-mobile-sidebar-toggle"
              onClick={() => setIsMobileMenuOpen((p) => !p)}
              title="Toggle Navigation Menu"
              style={{
                display: "none",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                borderRadius: "6px",
                border: "1px solid #e2e8f0",
                background: "#f8fafc",
                color: "#1e293b",
                cursor: "pointer",
                flexShrink: 0,
              }}
              className="mobile-hamburger-btn"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>

            {/* Top Navbar: Employee Search (Only visible to HR, Manager, and Owners who have access to employee directory) */}
            {["hr_admin", "manager", "super_admin", "owner"].includes(role) && (
              <div
                id="topbar-employee-search"
                className="desktop-only-search"
                style={{
                  position: "relative",
                  width: "100%",
                  maxWidth: "340px",
                }}
              >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#64748b"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{
                  position: "absolute",
                  left: "11px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  pointerEvents: "none",
                }}
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
              <input
                type="text"
                value={topEmployeeSearch}
                onChange={(e) => setTopEmployeeSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const q = topEmployeeSearch.trim();
                    if (q) {
                      navigate(`/employees?q=${encodeURIComponent(q)}`);
                    } else {
                      navigate("/employees");
                    }
                  }
                }}
                placeholder="Search in Employee..."
                style={{
                  width: "100%",
                  paddingLeft: "34px",
                  paddingRight: topEmployeeSearch ? "28px" : "12px",
                  height: "33px",
                  borderRadius: "7px",
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  fontSize: "0.82rem",
                  color: "#334155",
                  outline: "none",
                  transition: "all 0.15s ease",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = "#93c5fd";
                  e.currentTarget.style.background = "#ffffff";
                  e.currentTarget.style.boxShadow = "0 0 0 3px rgba(59, 130, 246, 0.1)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = "#e2e8f0";
                  e.currentTarget.style.background = "#f8fafc";
                  e.currentTarget.style.boxShadow = "none";
                }}
              />
              {topEmployeeSearch && (
                <button
                  type="button"
                  onClick={() => setTopEmployeeSearch("")}
                  style={{
                    position: "absolute",
                    right: "8px",
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "none",
                    border: "none",
                    color: "#94a3b8",
                    cursor: "pointer",
                    padding: "2px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "0.75rem",
                  }}
                  title="Clear"
                >
                  ✕
                </button>
              )}
            </div>
          )}
          </div>

          {/* Right side: Pending approvals + Notification + People + Settings + Apps + Profile Pill */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>

            {/* Pending approvals badge — admin/owner only */}
            {["owner", "hr_admin", "super_admin"].includes(role) && pendingLeaves > 0 && (
              <button
                type="button"
                id="btn-pending-approvals"
                onClick={() => navigate("/leaves?status=pending")}
                title={`${pendingLeaves} pending leave request${pendingLeaves !== 1 ? "s" : ""} — click to review`}
                style={{
                  display: "flex", alignItems: "center", gap: "5px",
                  padding: "5px 10px", borderRadius: "7px",
                  border: "1px solid #fde68a", background: "#fffbeb",
                  color: "#92400e", fontSize: "0.78rem", fontWeight: 600, cursor: "pointer",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#fef3c7"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#fffbeb"; }}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                </svg>
                {pendingLeaves} Pending
              </button>
            )}

            <NotificationBell />

            {/* Zoho People / Coworker Directory Quick Access Icon (Only for HR, Manager, Owners) */}
            {["hr_admin", "manager", "super_admin", "owner"].includes(role) && (
              <div ref={peopleMenuRef} style={{ position: "relative" }}>
              <button
                type="button"
                id="btn-top-people"
                onClick={() => setPeopleMenuOpen((p) => !p)}
                title="Coworkers & Organization Members (Zoho People)"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "32px",
                  height: "32px",
                  borderRadius: "7px",
                  border: `1px solid ${peopleMenuOpen ? "#bfdbfe" : "#e2e8f0"}`,
                  background: peopleMenuOpen ? "#eff6ff" : "#f8fafc",
                  color: peopleMenuOpen ? "#2563eb" : "#64748b",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "#cbd5e1";
                  e.currentTarget.style.color = "#0f172a";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = peopleMenuOpen ? "#bfdbfe" : "#e2e8f0";
                  e.currentTarget.style.color = peopleMenuOpen ? "#2563eb" : "#64748b";
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </button>

              {/* Zoho People Quick Popover Menu */}
              {peopleMenuOpen && (
                <div
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 6px)",
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "10px",
                    boxShadow: "0 10px 25px -5px rgba(0,0,0,0.15), 0 4px 6px -2px rgba(0,0,0,0.05)",
                    minWidth: "260px",
                    zIndex: 999,
                    overflow: "hidden",
                    padding: "6px 0",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div style={{ padding: "8px 14px 6px", borderBottom: "1px solid #f1f5f9" }}>
                    <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a" }}>
                      People & Teams
                    </div>
                    <div style={{ fontSize: "0.72rem", color: "#64748b", marginTop: "2px" }}>
                      Quick access to organization members
                    </div>
                  </div>

                  <div style={{ padding: "4px 0" }}>
                    <button
                      type="button"
                      onClick={() => {
                        setPeopleMenuOpen(false);
                        navigate("/employees");
                      }}
                      style={{
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        padding: "8px 14px",
                        border: "none",
                        background: "transparent",
                        fontSize: "0.82rem",
                        color: "#334155",
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      <span style={{ fontSize: "1rem" }}>👥</span>
                      <div>
                        <div style={{ fontWeight: 600, color: "#0f172a" }}>Employee Directory</div>
                        <div style={{ fontSize: "0.72rem", color: "#64748b" }}>View all active & registered staff</div>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setPeopleMenuOpen(false);
                        navigate("/departments");
                      }}
                      style={{
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        padding: "8px 14px",
                        border: "none",
                        background: "transparent",
                        fontSize: "0.82rem",
                        color: "#334155",
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      <span style={{ fontSize: "1rem" }}>🏢</span>
                      <div>
                        <div style={{ fontWeight: 600, color: "#0f172a" }}>Departments & Teams</div>
                        <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Team structures and headcounts</div>
                      </div>
                    </button>

                    {["owner", "hr_admin", "super_admin"].includes(role) && (
                      <button
                        type="button"
                        onClick={() => {
                          setPeopleMenuOpen(false);
                          navigate("/employees/new");
                        }}
                        style={{
                          width: "100%",
                          display: "flex",
                          alignItems: "center",
                          gap: "10px",
                          padding: "8px 14px",
                          border: "none",
                          background: "transparent",
                          fontSize: "0.82rem",
                          color: "#2563eb",
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#eff6ff")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <span style={{ fontSize: "1rem" }}>➕</span>
                        <div>
                          <div style={{ fontWeight: 600, color: "#2563eb" }}>Add New Employee</div>
                          <div style={{ fontSize: "0.72rem", color: "#64748b" }}>Onboard team member or invite</div>
                        </div>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

            {/* Zoho Settings Gear Icon */}
            <button
              type="button"
              id="btn-top-settings"
              onClick={() => navigate("/settings")}
              title="Organization Settings & Configurations"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                borderRadius: "7px",
                border: "1px solid #e2e8f0",
                background: location.pathname.startsWith("/settings") ? "#eff6ff" : "#f8fafc",
                color: location.pathname.startsWith("/settings") ? "#2563eb" : "#64748b",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#cbd5e1";
                e.currentTarget.style.color = "#0f172a";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "#e2e8f0";
                e.currentTarget.style.color = location.pathname.startsWith("/settings") ? "#2563eb" : "#64748b";
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>

            {/* Zoho 9-Dots / Apps Launcher Icon */}
            <div ref={appsMenuRef} style={{ position: "relative" }}>
              <button
                type="button"
                id="btn-top-apps"
                onClick={() => setAppsMenuOpen((prev) => !prev)}
                title="Zoho Apps Suite"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "32px",
                  height: "32px",
                  borderRadius: "7px",
                  border: `1px solid ${appsMenuOpen ? "#bfdbfe" : "#e2e8f0"}`,
                  background: appsMenuOpen ? "#eff6ff" : "#f8fafc",
                  color: appsMenuOpen ? "#2563eb" : "#64748b",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "#cbd5e1";
                  e.currentTarget.style.color = "#0f172a";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = appsMenuOpen ? "#bfdbfe" : "#e2e8f0";
                  e.currentTarget.style.color = appsMenuOpen ? "#2563eb" : "#64748b";
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="4" cy="4" r="2.2" />
                  <circle cx="12" cy="4" r="2.2" />
                  <circle cx="20" cy="4" r="2.2" />
                  <circle cx="4" cy="12" r="2.2" />
                  <circle cx="12" cy="12" r="2.2" />
                  <circle cx="20" cy="12" r="2.2" />
                  <circle cx="4" cy="20" r="2.2" />
                  <circle cx="12" cy="20" r="2.2" />
                  <circle cx="20" cy="20" r="2.2" />
                </svg>
              </button>

              {/* Zoho Apps Suite Popover Grid */}
              {appsMenuOpen && (
                <div
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 6px)",
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "12px",
                    boxShadow: "0 10px 25px -5px rgba(0,0,0,0.15), 0 4px 6px -2px rgba(0,0,0,0.05)",
                    width: "320px",
                    zIndex: 999,
                    overflow: "hidden",
                    padding: "12px",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px", paddingBottom: "8px", borderBottom: "1px solid #f1f5f9" }}>
                    <div>
                      <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a" }}>
                        Zoho People Apps Suite
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "#64748b" }}>
                        All workspace productivity modules
                      </div>
                    </div>
                    <span style={{ fontSize: "0.68rem", fontWeight: 700, color: "#2563eb", background: "#eff6ff", padding: "2px 6px", borderRadius: "4px" }}>
                      PRO
                    </span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px" }}>
                    {[
                      {
                        title: "Attendance",
                        sub: "Punch clock",
                        to: "/attendance",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                            <circle cx="12" cy="12" r="10" />
                            <polyline points="12 6 12 12 16 14" />
                          </svg>
                        ),
                        bg: "#eff6ff",
                      },
                      {
                        title: "Leave Mgmt",
                        sub: "Quotas & days",
                        to: "/leaves",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                            <line x1="16" y1="2" x2="16" y2="6" />
                            <line x1="8" y1="2" x2="8" y2="6" />
                            <line x1="12" y1="11" x2="12" y2="17" />
                            <line x1="9" y1="14" x2="15" y2="14" />
                          </svg>
                        ),
                        bg: "#ecfdf5",
                      },
                      {
                        title: "Timesheets",
                        sub: "Hours & tasks",
                        to: "/timesheets",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                            <polyline points="14 2 14 8 20 8" />
                            <line x1="16" y1="13" x2="8" y2="13" />
                            <line x1="16" y1="17" x2="8" y2="17" />
                          </svg>
                        ),
                        bg: "#f5f3ff",
                      },
                      {
                        title: "My Payslip",
                        sub: "Salary & taxes",
                        to: "/payroll/payslip",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2">
                            <rect x="2" y="4" width="20" height="16" rx="2" />
                            <line x1="12" y1="8" x2="12" y2="16" />
                            <path d="M16 11.5a3.5 3.5 0 0 0-5-2.5h-1a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4h-2a3.5 3.5 0 0 1-3-1.5" />
                          </svg>
                        ),
                        bg: "#fffbeb",
                      },
                      {
                        title: "Performance",
                        sub: "Goals & reviews",
                        to: "/performance/goals",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2">
                            <circle cx="12" cy="12" r="10" />
                            <circle cx="12" cy="12" r="6" />
                            <circle cx="12" cy="12" r="2" />
                          </svg>
                        ),
                        bg: "#fef2f2",
                      },
                      {
                        title: "Directory",
                        sub: "People & staff",
                        to: "/employees",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2">
                            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                            <circle cx="9" cy="7" r="4" />
                            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                          </svg>
                        ),
                        bg: "#f0f9ff",
                      },
                      {
                        title: "Departments",
                        sub: "Teams & units",
                        to: "/departments",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#475569" strokeWidth="2">
                            <path d="M3 21h18M3 7v14M21 7v14M6 21V11h4v10M14 21V11h4v10M9 3h6v4H9z" />
                          </svg>
                        ),
                        bg: "#f8fafc",
                      },
                      {
                        title: "Shifts",
                        sub: "Work schedules",
                        to: "/shifts",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0d9488" strokeWidth="2">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                            <line x1="16" y1="2" x2="16" y2="6" />
                            <line x1="8" y1="2" x2="8" y2="6" />
                            <line x1="3" y1="10" x2="21" y2="10" />
                          </svg>
                        ),
                        bg: "#f0fdfa",
                      },
                      {
                        title: "Settings",
                        sub: "Preferences",
                        to: "/settings",
                        icon: (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2">
                            <circle cx="12" cy="12" r="3" />
                            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                          </svg>
                        ),
                        bg: "#f8fafc",
                      },
                    ].filter((app) => {
                      if (app.to === "/employees") {
                        return ["hr_admin", "manager", "super_admin", "owner"].includes(role);
                      }
                      return true;
                    }).map((app) => (
                      <button
                        key={app.title}
                        type="button"
                        onClick={() => {
                          setAppsMenuOpen(false);
                          navigate(app.to);
                        }}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          padding: "10px 6px",
                          borderRadius: "8px",
                          border: "1px solid #f1f5f9",
                          background: "#ffffff",
                          cursor: "pointer",
                          textAlign: "center",
                          transition: "all 0.15s ease",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#f8fafc";
                          e.currentTarget.style.borderColor = "#cbd5e1";
                          e.currentTarget.style.transform = "translateY(-1px)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "#ffffff";
                          e.currentTarget.style.borderColor = "#f1f5f9";
                          e.currentTarget.style.transform = "none";
                        }}
                      >
                        <div
                          style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "8px",
                            background: app.bg,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            marginBottom: "6px",
                          }}
                        >
                          {app.icon}
                        </div>
                        <div style={{ fontSize: "0.74rem", fontWeight: 700, color: "#1e293b", lineHeight: 1.2 }}>
                          {app.title}
                        </div>
                        <div style={{ fontSize: "0.64rem", color: "#64748b", marginTop: "2px" }}>
                          {app.sub}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Interactive Profile Pill */}
            <div ref={profileMenuRef} style={{ position: "relative" }}>
              <button
                type="button"
                id="btn-profile-pill"
                onClick={() => setProfileMenuOpen((p) => !p)}
                style={{
                  display: "flex", alignItems: "center", gap: "6px",
                  padding: "4px 10px 4px 5px",
                  borderRadius: "24px",
                  border: `1px solid ${profileMenuOpen ? "#bfdbfe" : "#e2e8f0"}`,
                  background: profileMenuOpen ? "#eff6ff" : "#f8fafc",
                  cursor: "pointer", transition: "all 0.15s ease",
                }}
              >
                {/* Avatar circle */}
                <div style={{
                  width: "26px", height: "26px", borderRadius: "50%", flexShrink: 0,
                  background: role === "owner"
                    ? "linear-gradient(135deg,#f59e0b,#d97706)"
                    : role === "hr_admin"
                    ? "linear-gradient(135deg,#6366f1,#8b5cf6)"
                    : role === "super_admin"
                    ? "linear-gradient(135deg,#ec4899,#db2777)"
                    : "linear-gradient(135deg,#3b82f6,#2563eb)",
                  color: "#fff", display: "flex", alignItems: "center",
                  justifyContent: "center", fontWeight: 700, fontSize: "0.72rem",
                }}>
                  {user?.email?.charAt(0).toUpperCase()}
                </div>
                <span className="profile-pill-text" style={{ fontSize: "0.78rem", fontWeight: 600, color: "#374151", whiteSpace: "nowrap" }}>
                  {role === "super_admin" ? "Super Admin" : role === "hr_admin" ? "HR Admin" : role.charAt(0).toUpperCase() + role.slice(1)}
                </span>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                  style={{ transform: profileMenuOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s ease" }}>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {/* Profile dropdown */}
              {profileMenuOpen && (
                <div style={{
                  position: "absolute", right: 0, top: "calc(100% + 6px)",
                  background: "#ffffff", border: "1px solid #e2e8f0",
                  borderRadius: "10px",
                  boxShadow: "0 10px 25px -5px rgba(0,0,0,0.12), 0 4px 6px -2px rgba(0,0,0,0.05)",
                  minWidth: "210px", zIndex: 999, overflow: "hidden", padding: "4px 0",
                }}>
                  {/* User info header */}
                  <div style={{ padding: "10px 14px 8px", borderBottom: "1px solid #f1f5f9" }}>
                    <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "#0f172a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {user?.email}
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "#64748b", marginTop: "2px", textTransform: "capitalize" }}>
                      {role === "super_admin" ? "Platform Super Admin" : role.replace("_", " ")}
                    </div>
                  </div>
                  {/* Settings */}
                  {[
                    { label: "My Profile & Settings", icon: "👤", to: "/settings" },
                    ...(["owner", "hr_admin", "super_admin"].includes(role)
                      ? [{ label: "Manage Admins", icon: "🛡️", to: "/settings" }]
                      : []),
                  ].map((item) => (
                    <button
                      key={item.label}
                      type="button"
                      onClick={() => { setProfileMenuOpen(false); navigate(item.to); }}
                      style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#374151", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px" }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f8fafc"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                    >
                      <span>{item.icon}</span> {item.label}
                    </button>
                  ))}
                  <div style={{ height: "1px", background: "#f1f5f9", margin: "4px 0" }} />
                  <button
                    type="button"
                    onClick={handleLogout}
                    style={{ width: "100%", textAlign: "left", padding: "8px 14px", border: "none", background: "transparent", fontSize: "0.83rem", color: "#dc2626", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px", fontWeight: 600 }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#fef2f2"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                  >
                    <span>→</span> Sign Out
                  </button>
                </div>
              )}
            </div>
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

    {/* ⌘K Global Search Modal */}
    {searchOpen && (
      <div
        style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "rgba(15, 23, 42, 0.55)",
          backdropFilter: "blur(4px)",
          display: "flex", alignItems: "flex-start", justifyContent: "center",
          paddingTop: "12vh",
        }}
        onClick={() => setSearchOpen(false)}
      >
        <div
          style={{
            background: "#ffffff", borderRadius: "14px", width: "100%", maxWidth: "540px",
            boxShadow: "0 25px 50px -12px rgba(0,0,0,0.35), 0 0 0 1px rgba(0,0,0,0.06)",
            overflow: "hidden",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Search input */}
          <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid #f1f5f9" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
            </svg>
            <input
              ref={searchInputRef}
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && filteredShortcuts.length > 0) {
                  navigate(filteredShortcuts[0].to);
                  setSearchOpen(false);
                }
              }}
              placeholder="Jump to a page, or type employee name… (↵ to select)"
              style={{
                flex: 1, border: "none", outline: "none",
                fontSize: "0.95rem", color: "#0f172a", background: "transparent",
              }}
            />
            <span style={{ fontSize: "0.7rem", color: "#94a3b8", border: "1px solid #e2e8f0", borderRadius: "4px", padding: "2px 6px", fontFamily: "monospace" }}>ESC</span>
          </div>
          {/* Results */}
          <div style={{ maxHeight: "340px", overflowY: "auto", padding: "6px 0" }}>
            {searchQ.trim() && (
              <button
                type="button"
                onClick={() => {
                  navigate(`/employees?q=${encodeURIComponent(searchQ.trim())}`);
                  setSearchOpen(false);
                }}
                style={{
                  width: "100%", textAlign: "left", padding: "10px 16px",
                  border: "none", background: "#f0fdf4",
                  display: "flex", alignItems: "center", gap: "10px",
                  cursor: "pointer", fontSize: "0.875rem", color: "#166534",
                  borderBottom: "1px solid #dcfce7",
                  transition: "background 0.1s",
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#dcfce7"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f0fdf4"; }}
              >
                <span style={{ fontSize: "1rem", width: "22px", textAlign: "center", flexShrink: 0 }}>🔍</span>
                <span style={{ fontWeight: 600 }}>Search employee "{searchQ.trim()}" in directory</span>
                <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "#16a34a", fontFamily: "monospace" }}>↵</span>
              </button>
            )}
            {filteredShortcuts.length === 0 && !searchQ.trim() ? (
              <div style={{ padding: "20px 16px", textAlign: "center", color: "#94a3b8", fontSize: "0.875rem" }}>
                No results for "{searchQ}"
              </div>
            ) : (
              filteredShortcuts.map((s) => (
                <button
                  key={s.to + s.label}
                  type="button"
                  onClick={() => { navigate(s.to); setSearchOpen(false); }}
                  style={{
                    width: "100%", textAlign: "left", padding: "9px 16px",
                    border: "none", background: "transparent",
                    display: "flex", alignItems: "center", gap: "10px",
                    cursor: "pointer", fontSize: "0.875rem", color: "#374151",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f8fafc"; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                >
                  <span style={{ fontSize: "1rem", width: "22px", textAlign: "center", flexShrink: 0 }}>{s.icon}</span>
                  <span style={{ fontWeight: 500 }}>{s.label}</span>
                  <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "#cbd5e1", fontFamily: "monospace" }}>↵</span>
                </button>
              ))
            )}
          </div>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #f1f5f9", display: "flex", gap: "14px", fontSize: "0.72rem", color: "#94a3b8" }}>
            <span>↑↓ navigate</span>
            <span>↵ select</span>
            <span>ESC close</span>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
