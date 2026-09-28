import { useState, useMemo, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import {
  listHolidays,
  createHoliday,
  deleteHoliday,
  importRegionalHolidays,
  previewRegionalHolidays,
  getHolidayRegions,
  type Holiday,
} from "../api";
import { listLocations, getMyCompany } from "../../identity/api";
import { formatDate } from "../../../shared/utils/date";

export function HolidaysPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const isHr = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "owner";
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
  const [importCountry, setImportCountry] = useState("IN");
  const [importState, setImportState] = useState("Gujarat");
  const [importYear, setImportYear] = useState(selectedYear);
  const [isImporting, setIsImporting] = useState(false);
  const [showAllPreview, setShowAllPreview] = useState(false);

  // Sync importYear with selectedYear whenever outer year filter changes
  useEffect(() => {
    setImportYear(selectedYear);
  }, [selectedYear]);

  // Query company details to detect company's configured country and state
  const companyQuery = useQuery({
    queryKey: ["my-company"],
    queryFn: getMyCompany,
    enabled: isHr,
  });

  // Query all supported countries and their states/regions
  const regionsQuery = useQuery({
    queryKey: ["holiday-regions"],
    queryFn: getHolidayRegions,
    enabled: isImportModalOpen,
  });

  // Set defaults based on company country/state when loaded
  useEffect(() => {
    if (companyQuery.data) {
      const coCountry = (companyQuery.data.country || "IN").toUpperCase();
      setImportCountry(coCountry);
      if (companyQuery.data.state) {
        setImportState(companyQuery.data.state);
      }
    }
  }, [companyQuery.data]);

  // Query actual statutory holidays from the backend for the selected country, state & year
  const regionalPreviewQuery = useQuery({
    queryKey: ["regional-preview", importCountry, importState, importYear],
    queryFn: () => previewRegionalHolidays({ country: importCountry, state: importState, year: importYear }),
    enabled: isImportModalOpen,
  });

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
        country: importCountry,
        state: importState,
        year: importYear,
      });
      notify(res.message, "success");
      setIsImportModalOpen(false);
      setSelectedYear(importYear);
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
        title={`Holiday Calendar (${selectedYear})`}
        breadcrumb="Leave & Attendance / Holiday Calendar"
        action={
          isHr && (
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setImportYear(selectedYear);
                  setIsImportModalOpen(true);
                }}
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
              <div style={{ display: "inline-flex", alignItems: "center", border: "1px solid #cbd5e1", borderRadius: "6px", backgroundColor: "#ffffff", overflow: "hidden" }}>
                <button
                  type="button"
                  title="Previous Year"
                  onClick={() => setSelectedYear((y) => y - 1)}
                  style={{
                    background: "none",
                    border: "none",
                    borderRight: "1px solid #e2e8f0",
                    padding: "4px 8px",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                    color: "#475569",
                  }}
                >
                  ◀
                </button>
                <select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  style={{
                    padding: "4px 8px",
                    border: "none",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    backgroundColor: "transparent",
                    cursor: "pointer",
                    outline: "none",
                  }}
                >
                  {Array.from({ length: 16 }, (_, i) => 2020 + i).map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                  {/* Keep current custom year if user navigated outside the 2020-2035 window */}
                  {(selectedYear < 2020 || selectedYear > 2035) && (
                    <option value={selectedYear}>{selectedYear}</option>
                  )}
                </select>
                <button
                  type="button"
                  title="Next Year"
                  onClick={() => setSelectedYear((y) => y + 1)}
                  style={{
                    background: "none",
                    border: "none",
                    borderLeft: "1px solid #e2e8f0",
                    padding: "4px 8px",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                    color: "#475569",
                  }}
                >
                  ▶
                </button>
              </div>
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
                            {dayName} • {holiday.is_optional ? (
                              <span style={{ color: "#d97706", fontWeight: 600 }}>
                                Office Open • Optional Holiday (Floater)
                              </span>
                            ) : (
                              <span style={{ color: "#475569" }}>
                                Office Closed • Mandatory Off
                              </span>
                            )}
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

                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                    <input
                      type="checkbox"
                      id="is_optional_check"
                      checked={newIsOptional}
                      onChange={(e) => setNewIsOptional(e.target.checked)}
                    />
                    <label htmlFor="is_optional_check" style={{ fontSize: "0.85rem", color: "#334155", cursor: "pointer", fontWeight: 600 }}>
                      Restricted / Optional Holiday (Office remains OPEN)
                    </label>
                  </div>
                  <p style={{ margin: "4px 0 0 24px", fontSize: "0.75rem", color: "#64748b", lineHeight: 1.4 }}>
                    • <strong>Office Status:</strong> The office stays OPEN. Normal work continues.<br />
                    • <strong>Leave / Salary:</strong> No salary is deducted. Employees can apply for this date as an Optional Holiday (Floater Leave) under their assigned quota.
                  </p>
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

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>Country</label>
                  <select
                    value={importCountry}
                    onChange={(e) => {
                      const newC = e.target.value;
                      setImportCountry(newC);
                      const regInfo = regionsQuery.data?.[newC];
                      if (regInfo && regInfo.states && regInfo.states.length > 0) {
                        setImportState(regInfo.states[0]);
                      }
                    }}
                    className="form-input"
                    style={{ fontWeight: 600 }}
                  >
                    {regionsQuery.data ? (
                      Object.entries(regionsQuery.data).map(([code, info]) => (
                        <option key={code} value={code}>
                          {info.name} ({code})
                        </option>
                      ))
                    ) : (
                      <>
                        <option value="IN">India (IN)</option>
                        <option value="US">United States (US)</option>
                        <option value="GB">United Kingdom (GB)</option>
                        <option value="AE">United Arab Emirates (AE)</option>
                        <option value="SG">Singapore (SG)</option>
                        <option value="CA">Canada (CA)</option>
                        <option value="AU">Australia (AU)</option>
                      </>
                    )}
                  </select>
                </div>

                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>State / Region</label>
                  <select
                    value={importState}
                    onChange={(e) => setImportState(e.target.value)}
                    className="form-input"
                    style={{ fontWeight: 600 }}
                  >
                    {regionsQuery.data && regionsQuery.data[importCountry]?.states ? (
                      regionsQuery.data[importCountry].states.map((st) => (
                        <option key={st} value={st}>
                          {st}
                        </option>
                      ))
                    ) : (
                      <>
                        <option value="Gujarat">Gujarat</option>
                        <option value="Maharashtra">Maharashtra</option>
                        <option value="Karnataka">Karnataka</option>
                        <option value="Delhi">Delhi</option>
                        <option value="Tamil Nadu">Tamil Nadu</option>
                      </>
                    )}
                  </select>
                </div>

                <div>
                  <label className="form-label" style={{ fontWeight: 600, color: "#334155" }}>Calendar Year</label>
                  <select
                    value={importYear}
                    onChange={(e) => setImportYear(Number(e.target.value))}
                    className="form-input"
                    style={{ fontWeight: 600 }}
                  >
                    {Array.from({ length: 16 }, (_, i) => 2020 + i).map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                    {(importYear < 2020 || importYear > 2035) && (
                      <option value={importYear}>{importYear}</option>
                    )}
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
                  maxHeight: "220px",
                  overflowY: "auto",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <strong>
                    Preview of Gazetted Holidays ({importState}, {importYear}):
                  </strong>
                  {regionalPreviewQuery.data && regionalPreviewQuery.data.length > 6 && (
                    <button
                      type="button"
                      onClick={() => setShowAllPreview(!showAllPreview)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#7c3aed",
                        cursor: "pointer",
                        fontWeight: 700,
                        fontSize: "0.75rem",
                        padding: "2px 6px",
                        textDecoration: "underline",
                      }}
                    >
                      {showAllPreview ? "Show less" : `+${regionalPreviewQuery.data.length - 6} more (View all)`}
                    </button>
                  )}
                </div>

                {regionalPreviewQuery.isLoading ? (
                  <div style={{ padding: "8px 0", color: "#7c3aed", fontStyle: "italic" }}>
                    Fetching regional holiday database for {importState} ({importYear})...
                  </div>
                ) : !regionalPreviewQuery.data || regionalPreviewQuery.data.length === 0 ? (
                  <div style={{ padding: "8px 0", color: "#6b7280" }}>
                    No pre-seeded holidays available for {importState} in {importYear}.
                  </div>
                ) : (
                  <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                    {(showAllPreview
                      ? regionalPreviewQuery.data
                      : regionalPreviewQuery.data.slice(0, 6)
                    ).map((item, idx) => (
                      <li key={idx} style={{ marginBottom: "3px" }}>
                        <span style={{ fontWeight: 600 }}>{item.name}</span>{" "}
                        <span style={{ color: "#6b21a8", fontSize: "0.75rem" }}>
                          ({formatDate(item.date)})
                        </span>
                      </li>
                    ))}
                    {!showAllPreview && regionalPreviewQuery.data.length > 6 && (
                      <li style={{ listStyleType: "none", marginTop: "6px" }}>
                        <button
                          type="button"
                          onClick={() => setShowAllPreview(true)}
                          style={{
                            background: "#ede9fe",
                            border: "1px solid #c4b5fd",
                            color: "#5b21b6",
                            borderRadius: "4px",
                            padding: "2px 8px",
                            cursor: "pointer",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                          }}
                        >
                          +{regionalPreviewQuery.data.length - 6} more holidays... Click to view all
                        </button>
                      </li>
                    )}
                  </ul>
                )}
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
                disabled={isImporting || regionalPreviewQuery.isLoading}
              >
                {isImporting ? "Importing..." : `Import ${importState} (${importYear}) Holidays`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
