import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { NotificationBell } from "../../../shared/components/NotificationBell";
import * as PlatformApi from "../api";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  };
});

describe("Sub-feature 3.2: Notifications Frontend", () => {
  const mockNotifications: PlatformApi.NotificationItem[] = [
    {
      id: "notif-1",
      type: "LEAVE_APPROVED",
      title: "Leave Request Approved",
      message: "Your annual leave request for Nov 10 has been approved.",
      action_url: "/leaves",
      entity_type: "leave",
      entity_id: "leave-101",
      is_read: false,
      created_at: "2026-10-31T09:00:00Z",
    },
    {
      id: "notif-2",
      type: "PROJECT_ASSIGNED",
      title: "Assigned to Project Alpha",
      message: "You have been added to Project Alpha.",
      action_url: null, // dropped unsafe or missing url
      entity_type: "project",
      entity_id: "proj-1",
      is_read: true,
      created_at: "2026-10-30T14:30:00Z",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(PlatformApi.fetchNotifications).mockResolvedValue({
      items: mockNotifications,
      page: 1,
      limit: 15,
      total: 2,
      pages: 1,
      has_next: false,
      unread_count: 1,
    });
  });

  const renderNotificationBell = () => {
    return render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
  };

  it("renders bell button and displays unread count badge", async () => {
    renderNotificationBell();

    await waitFor(() => {
      expect(PlatformApi.fetchNotifications).toHaveBeenCalled();
    });

    const badge = await screen.findByText("1");
    expect(badge).toBeInTheDocument();
  });

  it("displays '9+' badge when unread count exceeds 9", async () => {
    vi.mocked(PlatformApi.fetchNotifications).mockResolvedValue({
      items: [],
      page: 1,
      limit: 15,
      total: 12,
      pages: 1,
      has_next: false,
      unread_count: 12,
    });

    renderNotificationBell();

    const badge = await screen.findByText("9+");
    expect(badge).toBeInTheDocument();
  });

  it("toggles dropdown open on click and renders notification items", async () => {
    renderNotificationBell();

    await waitFor(() => {
      expect(PlatformApi.fetchNotifications).toHaveBeenCalled();
    });

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    expect(screen.getByText("Leave Request Approved")).toBeInTheDocument();
    expect(screen.getByText("Assigned to Project Alpha")).toBeInTheDocument();
    expect(screen.getByText("1 unread")).toBeInTheDocument();
  });

  it("marks all notifications as read when 'Mark all read' is clicked", async () => {
    vi.mocked(PlatformApi.markAllNotificationsRead).mockResolvedValue({ marked_read: 1 });

    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    const markAllBtn = await screen.findByText("Mark all read");
    await userEvent.click(markAllBtn);

    expect(PlatformApi.markAllNotificationsRead).toHaveBeenCalledTimes(1);

    // Unread badge should disappear after marking all as read
    await waitFor(() => {
      expect(screen.queryByText("1 unread")).not.toBeInTheDocument();
    });
  });

  it("marks individual unread notification as read and navigates when action_url exists", async () => {
    const updatedNotif = { ...mockNotifications[0], is_read: true };
    vi.mocked(PlatformApi.markNotificationRead).mockResolvedValue(updatedNotif);

    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    const unreadItem = await screen.findByText("Leave Request Approved");
    await userEvent.click(unreadItem);

    expect(PlatformApi.markNotificationRead).toHaveBeenCalledWith("notif-1");
    expect(mockNavigate).toHaveBeenCalledWith("/leaves");
  });

  it("opens the project page for a project notification with no action_url (BUG-095)", async () => {
    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    const itemWithoutUrl = await screen.findByText("Assigned to Project Alpha");
    await userEvent.click(itemWithoutUrl);

    // No link is rendered; already read, so no markNotificationRead call. The page for
    // the record it is about opens, since the server sends no action_url for projects.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(PlatformApi.markNotificationRead).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/projects/proj-1");
  });

  it("does not crash and item stays unread when markNotificationRead rejects", async () => {
    vi.mocked(PlatformApi.markNotificationRead).mockRejectedValue(new Error("Network error"));

    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    const unreadItem = await screen.findByText("Leave Request Approved");
    await userEvent.click(unreadItem);

    expect(PlatformApi.markNotificationRead).toHaveBeenCalledWith("notif-1");

    // Bell still renders and the unread badge is unchanged: the item stayed unread
    expect(screen.getByTitle("Notifications")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("displays empty state when there are no notifications", async () => {
    vi.mocked(PlatformApi.fetchNotifications).mockResolvedValue({
      items: [],
      page: 1,
      limit: 15,
      total: 0,
      pages: 1,
      has_next: false,
      unread_count: 0,
    });

    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    expect(screen.getByText("No notifications yet.")).toBeInTheDocument();
  });

  it("closes dropdown when clicking outside", async () => {
    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    expect(screen.getByText("Notifications")).toBeInTheDocument();

    // Trigger click outside
    fireEvent.mouseDown(document.body);

    await waitFor(() => {
      expect(screen.queryByText("Leave Request Approved")).not.toBeInTheDocument();
    });
  });

  describe("B5: Entity type routing & clickability", () => {
    const testCases: Array<{ entity_type: string; entity_id?: string; expectedPath: string }> = [
      { entity_type: "project", entity_id: "p-123", expectedPath: "/projects/p-123" },
      { entity_type: "project", expectedPath: "/projects" },
      { entity_type: "project_task", expectedPath: "/projects" },
      { entity_type: "task", expectedPath: "/projects" },
      { entity_type: "task_comment", expectedPath: "/projects" },
      { entity_type: "project_member", expectedPath: "/projects" },
      { entity_type: "milestone", expectedPath: "/projects" },
      { entity_type: "project_document", expectedPath: "/projects" },
      { entity_type: "time_entry", expectedPath: "/timesheets" },
      { entity_type: "attendance", expectedPath: "/attendance" },
      { entity_type: "attendance_regularization", expectedPath: "/attendance" },
      { entity_type: "leave", expectedPath: "/leaves" },
      { entity_type: "leave_balance", expectedPath: "/leaves" },
      { entity_type: "leave_type", expectedPath: "/leaves" },
      { entity_type: "payroll_run", expectedPath: "/payroll/payslip" },
      { entity_type: "reimbursement", expectedPath: "/payroll/reimbursements" },
      { entity_type: "performance_cycle", expectedPath: "/performance" },
      { entity_type: "performance_pip", expectedPath: "/performance" },
      { entity_type: "performance_pip_checkin", expectedPath: "/performance" },
      { entity_type: "performance_goal", expectedPath: "/performance/goals" },
      { entity_type: "performance_review", expectedPath: "/performance/reviews" },
      { entity_type: "performance_summary", expectedPath: "/performance/reviews" },
      { entity_type: "employee", expectedPath: "/performance/goals" },
      { entity_type: "employee_salary", expectedPath: "/payroll/setup" },
      { entity_type: "salary_structure", expectedPath: "/payroll/setup" },
      { entity_type: "statutory_config", expectedPath: "/payroll/setup" },
      { entity_type: "statutory_rate", expectedPath: "/payroll/setup" },
      { entity_type: "pt_slab", expectedPath: "/payroll/setup" },
      { entity_type: "tax_slab", expectedPath: "/payroll/setup" },
      { entity_type: "employee_bank_account", expectedPath: "/payroll/payslip" },
      { entity_type: "department", expectedPath: "/departments" },
      { entity_type: "location", expectedPath: "/settings/locations" },
      { entity_type: "shift", expectedPath: "/shifts" },
      { entity_type: "employee_shift", expectedPath: "/shifts" },
      { entity_type: "holiday", expectedPath: "/holidays" },
      { entity_type: "platform_stats", expectedPath: "/admin/payroll" },
      { entity_type: "rate", expectedPath: "/admin/payroll" },
      { entity_type: "rate_change_draft", expectedPath: "/admin/payroll" },
      { entity_type: "rate_source", expectedPath: "/admin/payroll" },
    ];

    testCases.forEach(({ entity_type, entity_id = null, expectedPath }) => {
      it(`navigates entity_type '${entity_type}' without action_url to '${expectedPath}'`, async () => {
        const notif: PlatformApi.NotificationItem = {
          id: `notif-${entity_type}`,
          type: "TEST_NOTICE",
          title: `Notice for ${entity_type}`,
          message: `Testing mapping for ${entity_type}`,
          action_url: null,
          entity_type,
          entity_id: entity_id ?? null,
          is_read: true,
          created_at: "2026-10-31T09:00:00Z",
        };
        vi.mocked(PlatformApi.fetchNotifications).mockResolvedValue({
          items: [notif],
          page: 1,
          limit: 15,
          total: 1,
          pages: 1,
          has_next: false,
          unread_count: 0,
        });

        renderNotificationBell();
        const bellBtn = screen.getByTitle("Notifications");
        await userEvent.click(bellBtn);

        const item = await screen.findByText(`Notice for ${entity_type}`);
        await userEvent.click(item);

        expect(mockNavigate).toHaveBeenCalledWith(expectedPath);
      });
    });

    it("asserts an unmappable entity type is not clickable (no pointer cursor, no navigation)", async () => {
      const unmappableTypes = ["audit_log", "company", "employee_document", "file_object", "user", "announcement"];
      const unmappableItems: PlatformApi.NotificationItem[] = unmappableTypes.map((type) => ({
        id: `notif-${type}`,
        type: "AUDIT_NOTICE",
        title: `Unmappable ${type}`,
        message: `Details about ${type}`,
        action_url: null,
        entity_type: type,
        entity_id: "entity-uuid",
        is_read: true,
        created_at: "2026-10-31T09:00:00Z",
      }));

      vi.mocked(PlatformApi.fetchNotifications).mockResolvedValue({
        items: unmappableItems,
        page: 1,
        limit: 15,
        total: unmappableItems.length,
        pages: 1,
        has_next: false,
        unread_count: 0,
      });

      renderNotificationBell();
      const bellBtn = screen.getByTitle("Notifications");
      await userEvent.click(bellBtn);

      for (const notif of unmappableItems) {
        const titleEl = await screen.findByText(notif.title);
        const rowEl = titleEl.closest("div[style*='display: flex']") as HTMLElement;
        expect(rowEl).toBeInTheDocument();
        expect(rowEl.style.cursor).toBe("default");

        await userEvent.click(rowEl);
        expect(mockNavigate).not.toHaveBeenCalled();
      }
    });
  });
});
