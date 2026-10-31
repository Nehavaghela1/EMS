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

  it("handles null action_url safely without triggering navigation", async () => {
    renderNotificationBell();

    const bellBtn = screen.getByTitle("Notifications");
    await userEvent.click(bellBtn);

    const itemWithoutUrl = await screen.findByText("Assigned to Project Alpha");
    await userEvent.click(itemWithoutUrl);

    // Already read, no markNotificationRead call and no navigation
    expect(PlatformApi.markNotificationRead).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
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
});
