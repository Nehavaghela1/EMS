import { useState, useEffect, useRef } from "react";
import { searchManagers, type ManagerSearchResult } from "../api";

interface ManagerComboboxProps {
  value: string;
  onChange: (id: string, manager?: ManagerSearchResult | null) => void;
  excludeId?: string;
  initialManagerName?: string;
  initialManagerPosition?: string;
  disabled?: boolean;
}

export function ManagerCombobox({
  value,
  onChange,
  excludeId,
  initialManagerName,
  initialManagerPosition,
  disabled = false,
}: ManagerComboboxProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [results, setResults] = useState<ManagerSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedDisplay, setSelectedDisplay] = useState<string>("");

  const containerRef = useRef<HTMLDivElement>(null);

  // Synchronize initial manager name
  useEffect(() => {
    if (value && initialManagerName) {
      setSelectedDisplay(
        `${initialManagerName}${initialManagerPosition ? ` (${initialManagerPosition})` : ""}`
      );
    } else if (!value) {
      setSelectedDisplay("");
    }
  }, [value, initialManagerName, initialManagerPosition]);

  // Click outside listener
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Debounced search
  useEffect(() => {
    if (!isOpen) return;

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchManagers(searchTerm.trim() || undefined, excludeId);
        setResults(data);
      } catch (err) {
        console.error("Failed to search managers:", err);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [searchTerm, isOpen, excludeId]);

  function handleSelect(mgr: ManagerSearchResult) {
    const displayName = `${mgr.first_name} ${mgr.last_name || ""}`.trim();
    const fullText = `${displayName}${mgr.position ? ` (${mgr.position})` : ""}`;
    setSelectedDisplay(fullText);
    onChange(mgr.id, mgr);
    setIsOpen(false);
  }

  function handleClear() {
    setSelectedDisplay("");
    setSearchTerm("");
    onChange("", null);
  }

  return (
    <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
      {value && selectedDisplay ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 12px",
            border: "1px solid var(--color-border, #cbd5e1)",
            borderRadius: "6px",
            backgroundColor: "var(--color-surface, #f8fafc)",
            fontSize: "0.875rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1rem" }}>👤</span>
            <span style={{ fontWeight: 500, color: "var(--color-text, #1e293b)" }}>
              {selectedDisplay}
            </span>
          </div>
          {!disabled && (
            <button
              type="button"
              onClick={handleClear}
              className="btn btn-xs btn-ghost"
              style={{ padding: "0 6px", fontSize: "0.8rem", color: "var(--color-muted, #64748b)" }}
              title="Remove manager"
            >
              ✕
            </button>
          )}
        </div>
      ) : (
        <div style={{ position: "relative" }}>
          <input
            type="text"
            value={searchTerm}
            disabled={disabled}
            placeholder="Type to search candidate reporting manager..."
            onFocus={() => {
              setIsOpen(true);
              if (results.length === 0) {
                // Fetch first page immediately
                setLoading(true);
                searchManagers(undefined, excludeId)
                  .then(setResults)
                  .finally(() => setLoading(false));
              }
            }}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setIsOpen(true);
            }}
            style={{ width: "100%" }}
          />
          {loading && (
            <span
              style={{
                position: "absolute",
                right: "10px",
                top: "50%",
                transform: "translateY(-50%)",
                fontSize: "0.75rem",
                color: "var(--color-muted, #94a3b8)",
              }}
            >
              Searching...
            </span>
          )}
        </div>
      )}

      {isOpen && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 50,
            marginTop: "4px",
            maxHeight: "240px",
            overflowY: "auto",
            backgroundColor: "#ffffff",
            border: "1px solid var(--color-border, #cbd5e1)",
            borderRadius: "8px",
            boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
          }}
        >
          {loading && results.length === 0 ? (
            <div style={{ padding: "12px", textAlign: "center", color: "var(--color-muted, #64748b)", fontSize: "0.85rem" }}>
              Loading colleagues...
            </div>
          ) : results.length === 0 ? (
            <div style={{ padding: "12px", textAlign: "center", color: "var(--color-muted, #64748b)", fontSize: "0.85rem" }}>
              No matching employees found.
            </div>
          ) : (
            results.map((mgr) => {
              const name = `${mgr.first_name} ${mgr.last_name || ""}`.trim();
              return (
                <div
                  key={mgr.id}
                  onClick={() => handleSelect(mgr)}
                  style={{
                    padding: "8px 12px",
                    cursor: "pointer",
                    borderBottom: "1px solid #f1f5f9",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#f8fafc")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.875rem", color: "#1e293b" }}>
                      {name}{" "}
                      <span style={{ fontSize: "0.75rem", color: "#64748b", fontFamily: "monospace" }}>
                        ({mgr.employee_code})
                      </span>
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                      {mgr.position || "Staff"}{" "}
                      {mgr.department_name ? `• ${mgr.department_name}` : ""}
                    </div>
                  </div>
                  <span style={{ fontSize: "0.75rem", color: "#3b82f6", fontWeight: 500 }}>Select →</span>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
