import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import {
  listHolidays,
  createHoliday,
  deleteHoliday,
  importRegionalHolidays,
  type Holiday,
} from "../api";
import { listLocations } from "../../identity/api";
import { formatDate } from "../../../shared/utils/date";

export function HolidaysPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const isHr = user?.role === "hr_admin" || user?.role === "super_admin";
  const [selectedYear, setSelectedYear] = useState<number>(2026);
  const [scopeFilter, setScopeFilter] = useState<"my" | "all">("my");
  const [locationFilter, setLocationFilter] = useState<string>("all");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);

  // Add form state
  const [newName, setNewName] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newIsOptional, setNewIsOptional] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Import state
  const [importState, setImportState] = useState("Gujarat");
  const [importYear, setImportYear] = useState(2026);
  const [isImporting, setIsImporting] = useState(false);

  // Query locations
  const locationsQuery = useQuery({
    queryKey: ["company-locations"],
    queryFn: listLocations,
    enabled: isHr,
  });

  // Query holidays
  const holidaysQuery = useQuery({
    queryKey: ["holidays", selectedYear],
    queryFn: () => listHolidays(selectedYear),
  });

  const allHolidays = holidaysQuery.data ?? [];

  // Filter holidays based on scope / location
  const displayedHolidays = useMemo(() => {
    return allHolidays.sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    );
  }, [allHolidays]);

  // Split into upcoming and past
  const todayStr = new Date().toISOString().split("T")[0];
  const upcomingHolidays = displayedHolidays.filter((h) => h.date >= todayStr);
  const pastHolidays = displayedHolidays.filter((h) => h.date < todayStr);

  async function handleAddHoliday(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim() || !newDate) {
      notify("Please provide holiday name and date.", "error");
      return;
    }
    setIsSubmitting(true);
    try {
      await createHoliday({
        name: newName.trim(),
        date: newDate,
        is_optional: newIsOptional,
      });
      notify("Holiday added successfully.", "success");
      setIsAddModalOpen(false);
      setNewName("");
      setNewDate("");
      setNewIsOptional(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["holidays"] }),
        queryClient.invalidateQueries({ queryKey: ["attendance-calendar"] }),
      ]);
    } catch (err: any) {
      notify(err?.response?.data?.detail || "Failed to add holiday.", "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDeleteHoliday(holiday: Holiday) {
    if (!confirm(`Are you sure you want to remove ${holiday.name}?`)) return;
    try {
      await deleteHoliday(holiday.id);
      notify("Holiday removed.", "info");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["holidays"] }),
        queryClient.invalidateQueries({ queryKey: ["attendance-calendar"] }),
      ]);
    } catch (err: any) {
      notify(err?.response?.data?.detail || "Failed to remove holiday.", "error");
    }
  }

  async function handleImportRegional() {
    setIsImporting(true);
    try {
      const res = await importRegionalHolidays({
        state: importState,
        year: importYear,
      });
      notify(res.message, "success");
      setIsImportModalOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["holidays"] }),
        queryClient.invalidateQueries({ queryKey: ["attendance-calendar"] }),
      ]);
    } catch (err: any) {
      notify(err?.response?.data?.detail || "Import failed.", "error");
    } finally {
      setIsImporting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", backgroundColor: "#f8fafc" }}>
      <PageHeader
        title="Holiday Calendar (2026)"
        breadcrumb="Leave & Attendance / Holiday Calendar"
        action={
          isHr && (
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setIsImportModalOpen(true)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  backgroundColor: "#ffffff",
                  color: "#6b21a8",
                  border: "1px solid #d8b4fe",
                  fontWeight: 600,
                  boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                }}
              >
                <span>📥</span> Import Statutory (Gallery)
              </button>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => setIsAddModalOpen(true)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  fontWeight: 600,
                }}
              >
                <span>+</span> Add Custom Holiday
              </button>
            </div>
          )
        }
      />

      <div style={{ padding: "20px 24px", overflowY: "auto", flex: 1 }}>
        {/* Controls Bar: View Switcher (Zoho Model) + Year Filter */}
        <div
          style={{
            backgroundColor: "#ffffff",
            padding: "12px 18px",
            borderRadius: "10px",
            border: "1px solid #e2e8f0",
            marginBottom: "20px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "14px", flexWrap: "wrap" }}>
            {/* View Switcher: My Holidays vs All Locations (Admin) */}
            {isHr ? (
              <div
                style={{
                  display: "inline-flex",
                  backgroundColor: "#f1f5f9",
                  borderRadius: "8px",
                  padding: "3px",
                  border: "1px solid #e2e8f0",
                }}
              >
                <button
                  type="button"
                  onClick={() => setScopeFilter("my")}
                  style={{
                    padding: "5px 12px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer",
                    backgroundColor: scopeFilter === "my" ? "#ffffff" : "transparent",
                    color: scopeFilter === "my" ? "#2563eb" : "#64748b",
                    boxShadow: scopeFilter === "my" ? "0 1px 2px rgba(0,0,0,0.05)" : "none",
                  }}
                >
                  My Holidays
                </button>
                <button
                  type="button"
                  onClick={() => setScopeFilter("all")}
                  style={{
                    padding: "5px 12px",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer",
                    backgroundColor: scopeFilter === "all" ? "#ffffff" : "transparent",
                    color: scopeFilter === "all" ? "#2563eb" : "#64748b",
                    boxShadow: scopeFilter === "all" ? "0 1px 2px rgba(0,0,0,0.05)" : "none",
                  }}
                >
                  All Locations (Corporate)
                </button>
              </div>
            ) : (
              <div style={{ fontSize: "0.9rem", fontWeight: 600, color: "#334155" }}>
                📍 Applicable Worksite: <strong>Corporate HQ (Gujarat)</strong>
              </div>
            )}

            {isHr && scopeFilter === "all" && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#64748b" }}>Location:</label>
                <select
                  value={locationFilter}
                  onChange={(e) => setLocationFilter(e.target.value)}
                  style={{
                    padding: "4px 8px",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.82rem",
                    backgroundColor: "#ffffff",
                  }}
                >
                  <option value="all">All Locations (15 Days)</option>
                  {(locationsQuery.data || []).map((loc) => (
                    <option key={loc.id} value={loc.id}>
                      {loc.name} {loc.city ? `(${loc.city})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Year selector & summary counter */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <div style={{ fontSize: "0.85rem", color: "#64748b" }}>
              Total Holidays: <strong style={{ color: "#0f172a" }}>{displayedHolidays.length} Days</strong>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#64748b" }}>Year:</label>
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                style={{
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: "1px solid #cbd5e1",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  backgroundColor: "#ffffff",
                }}
              >
                <option value={2025}>2025</option>
                <option value={2026}>2026</option>
                <option value={2027}>2027</option>
              </select>
            </div>
          </div>
        </div>

        {holidaysQuery.isLoading ? (
          <div style={{ textAlign: "center", padding: "40px", color: "#64748b" }}>
            Loading holiday calendar...
          </div>
        ) : displayedHolidays.length === 0 ? (
          <div
            style={{
              backgroundColor: "#ffffff",
              padding: "48px 24px",
              borderRadius: "12px",
              border: "1px dashed #cbd5e1",
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: "2.5rem", marginBottom: "8px" }}>📅</div>
            <h3 style={{ margin: "0 0 6px 0", fontSize: "1.1rem", color: "#1e293b" }}>
              No holidays configured for {selectedYear}
            </h3>
            <p style={{ margin: "0 0 16px 0", fontSize: "0.85rem", color: "#64748b", maxWidth: "450px", marginLeft: "auto", marginRight: "auto" }}>
              {isHr
                ? "You can quickly import standard statutory public holidays with one click, or add specific company foundation days."
                : "No corporate holidays have been scheduled for this calendar year yet."}
            </p>
            {isHr && (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => setIsImportModalOpen(true)}
              >
                📥 Import {selectedYear} Statutory Holidays
              </button>
            )}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "28px" }}>
            {/* UPCOMING HOLIDAYS SECTION */}
            {upcomingHolidays.length > 0 && (
              <section>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}>
                  <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "#334155", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Upcoming Holidays ({upcomingHolidays.length})
                  </h3>
                  <div style={{ flex: 1, height: "1px", backgroundColor: "#e2e8f0" }} />
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                    gap: "16px",
                  }}
                >
                  {upcomingHolidays.map((holiday) => {
                    const dateObj = new Date(holiday.date + "T00:00:00");
                    const dayName = dateObj.toLocaleDateString("en-US", { weekday: "long" });
                    const formatted = formatDate(holiday.date);

                    return (
                      <div
                        key={holiday.id}
                        style={{
                          backgroundColor: "#ffffff",
                          borderRadius: "10px",
                          border: "1px solid #e2e8f0",
                          padding: "16px",
                          boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
                          position: "relative",
                          display: "flex",
                          flexDirection: "column",
                          justifyContent: "space-between",
                          transition: "transform 0.15s ease, box-shadow 0.15s ease",
                        }}
                      >
                        <div>
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              marginBottom: "8px",
                            }}
                          >
                            <span
                              style={{
                                fontSize: "0.75rem",
                                fontWeight: 700,
                                textTransform: "uppercase",
                                color: "#2563eb",
                                backgroundColor: "#eff6ff",
                                border: "1px solid #bfdbfe",
                                padding: "2px 8px",
                                borderRadius: "4px",
                              }}
                            >
                              {formatted}
                            </span>

                            <span
                              style={{
                                fontSize: "0.72rem",
                                fontWeight: 600,
                                color: holiday.is_optional ? "#d97706" : "#6b21a8",
                                backgroundColor: holiday.is_optional ? "#fffbeb" : "#faf5ff",
                                border: `1px solid ${holiday.is_optional ? "#fde68a" : "#d8b4fe"}`,
                                padding: "2px 6px",
                                borderRadius: "4px",
                              }}
                            >
                              {holiday.is_optional ? "Restricted / Optional" : "Mandatory Gazetted"}
                            </span>
                          </div>

                          <h4 style={{ margin: "4px 0 6px 0", fontSize: "1.05rem", fontWeight: 700, color: "#1e293b" }}>
                            {holiday.name}
                          </h4>

                          <p style={{ margin: 0, fontSize: "0.82rem", color: "#64748b" }}>
                            {dayName} • Office Closed
                          </p>
                        </div>

                        {isHr && (
                          <div style={{ marginTop: "14px", paddingTop: "10px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "flex-end" }}>
                            <button
                              type="button"
                              onClick={() => handleDeleteHoliday(holiday)}
                              style={{
                                background: "none",
                                border: "none",
                                color: "#ef4444",
                                fontSize: "0.75rem",
                                cursor: "pointer",
                                padding: "2px 6px",
                                borderRadius: "4px",
                              }}
                              title="Delete holiday"
                            >
                              Remove
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* PAST HOLIDAYS SECTION */}
            {pastHolidays.length > 0 && (
              <section>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}>
                  <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Past Holidays ({pastHolidays.length})
                  </h3>
                  <div style={{ flex: 1, height: "1px", backgroundColor: "#e2e8f0" }} />
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                    gap: "16px",
                    opacity: 0.75,
                  }}
                >
                  {pastHolidays.map((holiday) => {
                    const dateObj = new Date(holiday.date + "T00:00:00");
                    const dayName = dateObj.toLocaleDateString("en-US", { weekday: "long" });
                    const formatted = formatDate(holiday.date);

                    return (
                      <div
                        key={holiday.id}
                        style={{
                          backgroundColor: "#f8fafc",
                          borderRadius: "10px",
                          border: "1px solid #e2e8f0",
                          padding: "14px 16px",
                          display: "flex",
                          flexDirection: "column",
                          justifyContent: "space-between",
                        }}
                      >
                        <div>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                            <span style={{ fontSize: "0.72rem", fontWeight: 600, color: "#64748b" }}>
                              {formatted}
                            </span>
                            <span style={{ fontSize: "0.7rem", color: "#94a3b8" }}>
                              {holiday.is_optional ? "Optional" : "Mandatory"}
                            </span>
                          </div>
                          <h4 style={{ margin: "2px 0 4px 0", fontSize: "0.95rem", fontWeight: 600, color: "#475569" }}>
                            {holiday.name}
                          </h4>
                          <p style={{ margin: 0, fontSize: "0.78rem", color: "#94a3b8" }}>
                            {dayName}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </div>
        )}
      </div>

      {/* MODAL: ADD CUSTOM HOLIDAY */}
      {isAddModalOpen && (
        <div
          className="modal-backdrop"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            backgroundColor: "rgba(15, 23, 42, 0.65)",
            backdropFilter: "blur(4px)",
            WebkitBackdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
            overflowY: "auto",
          }}
          onClick={() => setIsAddModalOpen(false)}
        >
          <div
            className="modal-card"
            style={{
              position: "relative",
              width: "100%",
              maxWidth: "480px",
              backgroundColor: "#ffffff",
              borderRadius: "16px",
              boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.35)",
              border: "1px solid #e2e8f0",
              overflow: "hidden",
              zIndex: 10000,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="modal-header"
              style={{
                backgroundColor: "#ffffff",
                padding: "16px 20px",
                borderBottom: "1px solid #f1f5f9",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#0f172a", fontWeight: 700 }}>Add Custom Holiday</h3>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setIsAddModalOpen(false)}
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAddHoliday}>
              <div
                className="modal-body"
                style={{
                  backgroundColor: "#ffffff",
                  padding: "20px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>Holiday Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Annual Company Foundation Day"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="form-input"
                  />
                </div>

                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>Date *</label>
                  <input
                    type="date"
                    required
                    value={newDate}
                    onChange={(e) => setNewDate(e.target.value)}
                    className="form-input"
                  />
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                  <input
                    type="checkbox"
                    id="is_optional_check"
                    checked={newIsOptional}
                    onChange={(e) => setNewIsOptional(e.target.checked)}
                  />
                  <label htmlFor="is_optional_check" style={{ fontSize: "0.85rem", color: "#334155", cursor: "pointer" }}>
                    Restricted / Optional Holiday (office open, quota based)
                  </label>
                </div>
              </div>

              <div
                className="modal-footer"
                style={{
                  backgroundColor: "#f8fafc",
                  padding: "14px 20px",
                  borderTop: "1px solid #f1f5f9",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  gap: "10px",
                }}
              >
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setIsAddModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? "Adding..." : "Add Holiday"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: IMPORT STATUTORY HOLIDAYS (ZOHO GALLERY) */}
      {isImportModalOpen && (
        <div
          className="modal-backdrop"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            backgroundColor: "rgba(15, 23, 42, 0.65)",
            backdropFilter: "blur(4px)",
            WebkitBackdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
            overflowY: "auto",
          }}
          onClick={() => setIsImportModalOpen(false)}
        >
          <div
            className="modal-card"
            style={{
              position: "relative",
              width: "100%",
              maxWidth: "540px",
              backgroundColor: "#ffffff",
              borderRadius: "16px",
              boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.35)",
              border: "1px solid #e2e8f0",
              overflow: "hidden",
              zIndex: 10000,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="modal-header"
              style={{
                backgroundColor: "#ffffff",
                padding: "16px 20px",
                borderBottom: "1px solid #f1f5f9",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#0f172a", fontWeight: 700 }}>📥 Holidays Gallery (Regional Import)</h3>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setIsImportModalOpen(false)}
              >
                ✕
              </button>
            </div>

            <div
              className="modal-body"
              style={{
                backgroundColor: "#ffffff",
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                gap: "16px",
              }}
            >
              <p style={{ margin: 0, fontSize: "0.85rem", color: "#475569" }}>
                Import standard gazetted statutory public holidays for your regional branch directly into your calendar. The system skips any dates already configured.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>State / Region</label>
                  <select
                    value={importState}
                    onChange={(e) => setImportState(e.target.value)}
                    className="form-input"
                  >
                    <option value="Gujarat">Gujarat (15 statutory days)</option>
                  </select>
                </div>

                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>Calendar Year</label>
                  <select
                    value={importYear}
                    onChange={(e) => setImportYear(Number(e.target.value))}
                    className="form-input"
                  >
                    <option value={2026}>2026</option>
                  </select>
                </div>
              </div>

              <div
                style={{
                  backgroundColor: "#faf5ff",
                  border: "1px solid #d8b4fe",
                  borderRadius: "8px",
                  padding: "12px",
                  fontSize: "0.8rem",
                  color: "#581c87",
                }}
              >
                <strong>Preview of Included Gazetted Holidays:</strong>
                <ul style={{ margin: "6px 0 0 16px", padding: 0 }}>
                  <li>Republic Day (Jan 26)</li>
                  <li>Holi / Dhuleti (Mar 04)</li>
                  <li>Independence Day (Aug 15)</li>
                  <li>Janmashtami (Sep 04)</li>
                  <li>Diwali & Gujarati New Year (Nov 08 - 09)</li>
                  <li>Christmas (Dec 25) + 9 others</li>
                </ul>
              </div>
            </div>

            <div
              className="modal-footer"
              style={{
                backgroundColor: "#f8fafc",
                padding: "14px 20px",
                borderTop: "1px solid #f1f5f9",
                display: "flex",
                alignItems: "center",
                justifyContent: "flex-end",
                gap: "10px",
              }}
            >
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setIsImportModalOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleImportRegional}
                disabled={isImporting}
              >
                {isImporting ? "Importing..." : `Import ${importYear} Public Holidays`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
