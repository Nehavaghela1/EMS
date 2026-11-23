import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  type NotificationItem,
} from "../../modules/platform/api";

/** Where a notification opens. Falls back to entity_type routing when
 * no action_url is present on the notification item. */
export function notificationTarget(n: NotificationItem): string | null {
  if (n.action_url) return n.action_url;
  if (!n.entity_type) return null;

  switch (n.entity_type) {
    case "project":
      return n.entity_id ? `/projects/${n.entity_id}` : "/projects";
    case "project_task":
    case "task":
    case "task_comment":
    case "project_member":
    case "milestone":
    case "project_document":
      return "/projects";
    case "time_entry":
      return "/timesheets";
    case "attendance":
    case "attendance_regularization":
      return "/attendance";
    case "leave":
    case "leave_balance":
    case "leave_type":
      return "/leaves";
    case "payroll_run":
      return "/payroll/payslip";
    case "reimbursement":
      return "/payroll/reimbursements";
    case "performance_cycle":
    case "performance_pip":
    case "performance_pip_checkin":
      return "/performance";
    case "performance_goal":
      return "/performance/goals";
    case "performance_review":
    case "performance_summary":
      return "/performance/reviews";
    case "employee":
      return "/performance/goals";
    case "employee_salary":
    case "salary_structure":
    case "statutory_config":
    case "statutory_rate":
    case "pt_slab":
    case "tax_slab":
      return "/payroll/setup";
    case "employee_bank_account":
      return "/payroll/payslip";
    case "department":
      return "/departments";
    case "location":
      return "/settings/locations";
    case "shift":
    case "employee_shift":
      return "/shifts";
    case "holiday":
      return "/holidays";
    case "platform_stats":
      return "/admin/payroll";
    case "rate":
    case "rate_change_draft":
    case "rate_source":
      return "/admin/payroll";
    default:
      return null;
  }
}

export function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const loadNotifications = async () => {
    try {
      const data = await fetchNotifications(false, 15);
      setNotifications(data.items);
      setUnreadCount(data.unread_count);
    } catch (err) {
      // Silently catch in polling
    }
  };

  useEffect(() => {
    loadNotifications();
    // Poll every 30 seconds for background notifications
    const interval = setInterval(loadNotifications, 30000);
    return () => clearInterval(interval);
  }, []);

  // Click outside listener
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch (err) {
      console.error("Failed to mark all notifications read:", err);
    }
  };

  const handleItemClick = async (n: NotificationItem) => {
    const target = notificationTarget(n);
    if (!target) return; // unmappable type is not clickable (B3)

    if (!n.is_read) {
      try {
        await markNotificationRead(n.id);
        setNotifications((prev) =>
          prev.map((item) => (item.id === n.id ? { ...item, is_read: true } : item))
        );
        setUnreadCount((c) => Math.max(0, c - 1));
      } catch (err) {
        // Continue navigation
      }
    }
    setIsOpen(false);
    navigate(target);
  };

  return (
    <div ref={dropdownRef} style={{ position: "relative" }}>
      {/* Bell Button */}
      <button
        type="button"
        onClick={() => {
          setIsOpen(!isOpen);
          if (!isOpen) loadNotifications();
        }}
        style={{
          position: "relative",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          padding: "6px 8px",
          borderRadius: "8px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#64748b",
          transition: "all 0.15s ease",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#f1f5f9")}
        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
        title="Notifications"
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>

        {unreadCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: "2px",
              right: "2px",
              backgroundColor: "#ef4444",
              color: "#ffffff",
              fontSize: "0.65rem",
              fontWeight: 700,
              minWidth: "16px",
              height: "16px",
              borderRadius: "8px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "0 4px",
              boxShadow: "0 0 0 2px #ffffff",
            }}
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            width: "360px",
            maxHeight: "440px",
            backgroundColor: "#ffffff",
            borderRadius: "12px",
            border: "1px solid #e2e8f0",
            boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.05)",
            zIndex: 100,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: "12px 16px",
              borderBottom: "1px solid #f1f5f9",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              backgroundColor: "#f8fafc",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0f172a" }}>
                Notifications
              </span>
              {unreadCount > 0 && (
                <span
                  style={{
                    backgroundColor: "#dbeafe",
                    color: "#1e40af",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    padding: "1px 6px",
                    borderRadius: "9999px",
                  }}
                >
                  {unreadCount} unread
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                style={{
                  fontSize: "0.75rem",
                  color: "#2563eb",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 500,
                }}
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {notifications.length === 0 ? (
              <div
                style={{
                  padding: "32px 16px",
                  textAlign: "center",
                  color: "#94a3b8",
                  fontSize: "0.85rem",
                }}
              >
                No notifications yet.
              </div>
            ) : (
              notifications.map((n) => {
                const target = notificationTarget(n);
                const isClickable = Boolean(target);
                const unreadBg = "#f0fdf4";
                const readBg = "#ffffff";
                const baseBg = n.is_read ? readBg : unreadBg;

                return (
                  <div
                    key={n.id}
                    onClick={() => {
                      if (isClickable) handleItemClick(n);
                    }}
                    style={{
                      padding: "12px 16px",
                      borderBottom: "1px solid #f8fafc",
                      backgroundColor: baseBg,
                      cursor: isClickable ? "pointer" : "default",
                      display: "flex",
                      gap: "12px",
                      transition: isClickable ? "background-color 0.15s ease" : "none",
                    }}
                    onMouseEnter={(e) => {
                      if (isClickable) {
                        e.currentTarget.style.backgroundColor = "#f1f5f9";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (isClickable) {
                        e.currentTarget.style.backgroundColor = baseBg;
                      }
                    }}
                  >
                    <span
                      style={{
                        width: "8px",
                        height: "8px",
                        borderRadius: "50%",
                        backgroundColor: n.is_read ? "transparent" : "#22c55e",
                        marginTop: "5px",
                        flexShrink: 0,
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: n.is_read ? 500 : 700,
                          fontSize: "0.82rem",
                          color: "#1e293b",
                          lineHeight: 1.3,
                        }}
                      >
                        {n.title}
                      </div>
                      <div
                        style={{
                          fontSize: "0.78rem",
                          color: "#64748b",
                          marginTop: "2px",
                          lineHeight: 1.4,
                        }}
                      >
                        {n.message}
                      </div>
                      <div
                        style={{
                          fontSize: "0.68rem",
                          color: "#94a3b8",
                          marginTop: "4px",
                        }}
                      >
                        {new Date(n.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
