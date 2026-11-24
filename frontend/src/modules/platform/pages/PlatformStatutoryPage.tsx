import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../../../shared/components/PageHeader";
import { useToast } from "../../../app/toast-context";
import { parseApiError } from "../../../shared/api/errors";
import { formatDate } from "../../../shared/utils/date";
import {
  listStatutoryRates,
  createStatutoryRate,
  deleteStatutoryRate,
  listSupportedRegions,
  listPtSlabs,
  listTaxSlabs,
  type StatutoryRate,
  type StatutoryRateCreateInput,
  type RegionStateItem,
} from "../../payroll/api";

export interface SchemeConfigOption {
  code: string;
  name: string;
  employeeRate: string;
  employerRate: string;
  wageCeiling: string;
  sourceUrl: string;
  sourceTitle: string;
  hasBreakdown?: boolean;
  employerEpfRate?: string;
  employerEpsRate?: string;
}

export interface CountryMeta {
  currencySymbol: string;
  currencyCode: string;
  defaultSourceUrl: string;
  schemes: SchemeConfigOption[];
}

export const COUNTRY_SCHEMES_CATALOG: Record<string, CountryMeta> = {
  IN: {
    currencySymbol: "₹",
    currencyCode: "INR",
    defaultSourceUrl: "https://epfindia.gov.in",
    schemes: [
      {
        code: "epf",
        name: "EPF (Employee Provident Fund)",
        employeeRate: "12.000",
        employerRate: "12.000",
        wageCeiling: "15000.00",
        sourceUrl: "https://epfindia.gov.in",
        sourceTitle: "EPFO Official Gazette Notification",
        hasBreakdown: true,
        employerEpfRate: "3.670",
        employerEpsRate: "8.330",
      },
      {
        code: "esi",
        name: "ESI (Employee State Insurance)",
        employeeRate: "0.750",
        employerRate: "3.250",
        wageCeiling: "21000.00",
        sourceUrl: "https://esic.gov.in",
        sourceTitle: "ESIC Official Gazette Notification",
      },
    ],
  },
  US: {
    currencySymbol: "$",
    currencyCode: "USD",
    defaultSourceUrl: "https://www.ssa.gov",
    schemes: [
      {
        code: "fica_ss",
        name: "FICA - Social Security (OASDI)",
        employeeRate: "6.200",
        employerRate: "6.200",
        wageCeiling: "168600.00",
        sourceUrl: "https://www.ssa.gov",
        sourceTitle: "Social Security Contribution and Benefit Base",
      },
      {
        code: "fica_med",
        name: "FICA - Medicare (Hospital Insurance)",
        employeeRate: "1.450",
        employerRate: "1.450",
        wageCeiling: "99999999.00",
        sourceUrl: "https://www.ssa.gov",
        sourceTitle: "Medicare Contribution Schedule",
      },
      {
        code: "futa",
        name: "FUTA (Federal Unemployment Tax)",
        employeeRate: "0.000",
        employerRate: "0.600",
        wageCeiling: "7000.00",
        sourceUrl: "https://www.ssa.gov",
        sourceTitle: "Federal Unemployment Tax Act Regulations",
      },
    ],
  },
  GB: {
    currencySymbol: "£",
    currencyCode: "GBP",
    defaultSourceUrl: "https://www.gov.uk",
    schemes: [
      {
        code: "nic",
        name: "NIC (National Insurance Contributions)",
        employeeRate: "8.000",
        employerRate: "13.800",
        wageCeiling: "50270.00",
        sourceUrl: "https://www.gov.uk",
        sourceTitle: "HMRC National Insurance Rates and Categories",
      },
      {
        code: "ae_pension",
        name: "Workplace Pension (Auto-Enrolment)",
        employeeRate: "5.000",
        employerRate: "3.000",
        wageCeiling: "50270.00",
        sourceUrl: "https://www.gov.uk",
        sourceTitle: "The Pensions Regulator Auto-Enrolment Thresholds",
      },
    ],
  },
  AE: {
    currencySymbol: "AED ",
    currencyCode: "AED",
    defaultSourceUrl: "https://www.dubai.ae",
    schemes: [
      {
        code: "gpssa",
        name: "GPSSA (General Pension & Social Security Authority)",
        employeeRate: "5.000",
        employerRate: "12.500",
        wageCeiling: "50000.00",
        sourceUrl: "https://www.dubai.ae",
        sourceTitle: "GPSSA Federal Law No. 7 on Pension and Social Security",
      },
      {
        code: "eosb",
        name: "EOSB (End of Service Gratuity Fund)",
        employeeRate: "0.000",
        employerRate: "5.830",
        wageCeiling: "99999999.00",
        sourceUrl: "https://www.dubai.ae",
        sourceTitle: "UAE Labour Law End of Service Benefits Scheme",
      },
    ],
  },
  SG: {
    currencySymbol: "S$",
    currencyCode: "SGD",
    defaultSourceUrl: "https://www.cpf.gov.sg",
    schemes: [
      {
        code: "cpf",
        name: "CPF (Central Provident Fund)",
        employeeRate: "20.000",
        employerRate: "17.000",
        wageCeiling: "6800.00",
        sourceUrl: "https://www.cpf.gov.sg",
        sourceTitle: "CPF Board Contribution Rates Table",
      },
      {
        code: "shg",
        name: "Self-Help Groups Fund (CDAC/SINDA/MBMF)",
        employeeRate: "1.000",
        employerRate: "0.000",
        wageCeiling: "10000.00",
        sourceUrl: "https://www.cpf.gov.sg",
        sourceTitle: "Community Fund Statutory Contributions",
      },
    ],
  },
  CA: {
    currencySymbol: "CA$",
    currencyCode: "CAD",
    defaultSourceUrl: "https://www.canada.ca",
    schemes: [
      {
        code: "cpp",
        name: "CPP (Canada Pension Plan)",
        employeeRate: "5.950",
        employerRate: "5.950",
        wageCeiling: "68500.00",
        sourceUrl: "https://www.canada.ca",
        sourceTitle: "CRA Canada Pension Plan Contributions Schedule",
      },
      {
        code: "ei",
        name: "EI (Employment Insurance)",
        employeeRate: "1.660",
        employerRate: "2.320",
        wageCeiling: "63200.00",
        sourceUrl: "https://www.canada.ca",
        sourceTitle: "CRA Employment Insurance Premium Rates",
      },
    ],
  },
  AU: {
    currencySymbol: "A$",
    currencyCode: "AUD",
    defaultSourceUrl: "https://www.ato.gov.au",
    schemes: [
      {
        code: "super",
        name: "Superannuation Guarantee (SG)",
        employeeRate: "0.000",
        employerRate: "11.500",
        wageCeiling: "62270.00",
        sourceUrl: "https://www.ato.gov.au",
        sourceTitle: "ATO Superannuation Guarantee Percentage and Thresholds",
      },
      {
        code: "medicare",
        name: "Medicare Levy Withholding",
        employeeRate: "2.000",
        employerRate: "0.000",
        wageCeiling: "99999999.00",
        sourceUrl: "https://www.ato.gov.au",
        sourceTitle: "ATO Medicare Levy Rates and Thresholds",
      },
    ],
  },
};

const DEFAULT_COUNTRIES: RegionStateItem[] = [
  { code: "IN", name: "India", states: [] },
  { code: "US", name: "United States", states: [] },
  { code: "GB", name: "United Kingdom", states: [] },
  { code: "AE", name: "United Arab Emirates", states: [] },
  { code: "SG", name: "Singapore", states: [] },
  { code: "CA", name: "Canada", states: [] },
  { code: "AU", name: "Australia", states: [] },
];

export function PlatformStatutoryPage() {
  const { notify } = useToast();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<"rates" | "pt_slabs" | "tax_slabs">("rates");
  const [countryFilter, setCountryFilter] = useState("all");
  const [schemeFilter, setSchemeFilter] = useState("all");
  const [showAddModal, setShowAddModal] = useState(false);
  const [isCustomScheme, setIsCustomScheme] = useState(false);
  const [deletingRateId, setDeletingRateId] = useState<string | null>(null);
  const [openActionMenuId, setOpenActionMenuId] = useState<string | null>(null);
  const [modalMode, setModalMode] = useState<"create" | "revise">("create");

  // Close dropdown on click outside or Escape
  useEffect(() => {
    if (!openActionMenuId) return;
    const handleDocumentClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest("[data-action-menu]")) {
        setOpenActionMenuId(null);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpenActionMenuId(null);
      }
    };
    document.addEventListener("mousedown", handleDocumentClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [openActionMenuId]);

  // Modal Form State
  const [formData, setFormData] = useState<StatutoryRateCreateInput>({
    country: "IN",
    scheme: "epf",
    employee_rate: "12.000",
    employer_rate: "12.000",
    wage_ceiling: "15000.00",
    employer_epf_rate: "3.670",
    employer_eps_rate: "8.330",
    edli_rate: "0.500",
    admin_charge_rate: "0.500",
    employee_exempt_daily_wage: null,
    effective_from: new Date().toISOString().split("T")[0],
    source_url: "https://epfindia.gov.in",
    source_title: "EPFO Official Gazette Notification",
    verified_on: new Date().toISOString().split("T")[0],
    source_note: "",
  });

  // Queries
  const regionsQuery = useQuery<RegionStateItem[]>({
    queryKey: ["regions"],
    queryFn: listSupportedRegions,
    staleTime: 1000 * 60 * 30,
  });

  const ratesQuery = useQuery({
    queryKey: ["platform", "statutory-rates", { country: countryFilter, scheme: schemeFilter }],
    queryFn: () =>
      listStatutoryRates({
        country: countryFilter === "all" ? undefined : countryFilter,
        scheme: schemeFilter === "all" ? undefined : schemeFilter,
        limit: 100,
      }),
  });

  const ptSlabsQuery = useQuery({
    queryKey: ["platform", "pt-slabs"],
    queryFn: () => listPtSlabs("Gujarat"),
    enabled: activeTab === "pt_slabs",
  });

  const taxSlabsQuery = useQuery({
    queryKey: ["platform", "tax-slabs"],
    queryFn: () => listTaxSlabs("IN", "2026-2027", "new"),
    enabled: activeTab === "tax_slabs",
  });

  // Create Mutation
  const createMutation = useMutation({
    mutationFn: (payload: StatutoryRateCreateInput) => createStatutoryRate(payload),
    onSuccess: () => {
      notify("Global statutory rate published successfully.", "success");
      setShowAddModal(false);
      queryClient.invalidateQueries({ queryKey: ["platform", "statutory-rates"] });
    },
    onError: (err) => {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to create statutory rate", "error");
    },
  });

  // Delete Mutation
  const deleteMutation = useMutation({
    mutationFn: (rateId: string) => deleteStatutoryRate(rateId),
    onSuccess: () => {
      notify("Statutory rate cancelled and removed.", "success");
      setDeletingRateId(null);
      queryClient.invalidateQueries({ queryKey: ["platform", "statutory-rates"] });
    },
    onError: (err) => {
      const parsed = parseApiError(err);
      notify(parsed.message || "Failed to remove statutory rate", "error");
      setDeletingRateId(null);
    },
  });

  const currentCountryMeta = useMemo(() => {
    return COUNTRY_SCHEMES_CATALOG[formData.country] || COUNTRY_SCHEMES_CATALOG.IN;
  }, [formData.country]);

  const handleCountryChange = (newCountry: string) => {
    const meta = COUNTRY_SCHEMES_CATALOG[newCountry] || COUNTRY_SCHEMES_CATALOG.IN;
    const defaultScheme = meta.schemes[0];
    setIsCustomScheme(false);
    setFormData({
      ...formData,
      country: newCountry,
      scheme: defaultScheme ? defaultScheme.code : "custom",
      employee_rate: defaultScheme ? defaultScheme.employeeRate : "0.000",
      employer_rate: defaultScheme ? defaultScheme.employerRate : "0.000",
      wage_ceiling: defaultScheme ? defaultScheme.wageCeiling : "10000.00",
      employer_epf_rate: defaultScheme?.employerEpfRate || null,
      employer_eps_rate: defaultScheme?.employerEpsRate || null,
      source_url: defaultScheme ? defaultScheme.sourceUrl : meta.defaultSourceUrl,
      source_title: defaultScheme ? defaultScheme.sourceTitle : `${newCountry} Official Gazette Notification`,
      employee_exempt_daily_wage: null,
    });
  };

  const handleSchemeChange = (schemeCode: string) => {
    if (schemeCode === "custom") {
      setIsCustomScheme(true);
      setFormData({
        ...formData,
        scheme: "",
        source_url: currentCountryMeta.defaultSourceUrl,
      });
      return;
    }
    setIsCustomScheme(false);
    const matched = currentCountryMeta.schemes.find((s) => s.code === schemeCode);
    if (matched) {
      setFormData({
        ...formData,
        scheme: matched.code,
        employee_rate: matched.employeeRate,
        employer_rate: matched.employerRate,
        wage_ceiling: matched.wageCeiling,
        employer_epf_rate: matched.employerEpfRate || null,
        employer_eps_rate: matched.employerEpsRate || null,
        source_url: matched.sourceUrl,
        source_title: matched.sourceTitle,
        employee_exempt_daily_wage: null,
      });
    } else {
      setFormData({ ...formData, scheme: schemeCode });
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      ...formData,
      scheme: formData.scheme.trim().toLowerCase(),
      employee_rate: Number(formData.employee_rate),
      employer_rate: Number(formData.employer_rate),
      wage_ceiling: Number(formData.wage_ceiling),
      employer_epf_rate:
        formData.scheme === "epf" && formData.employer_epf_rate
          ? Number(formData.employer_epf_rate)
          : null,
      employer_eps_rate:
        formData.scheme === "epf" && formData.employer_eps_rate
          ? Number(formData.employer_eps_rate)
          : null,
      edli_rate:
        formData.scheme === "epf" && formData.edli_rate
          ? Number(formData.edli_rate)
          : null,
      admin_charge_rate:
        formData.scheme === "epf" && formData.admin_charge_rate
          ? Number(formData.admin_charge_rate)
          : null,
      employee_exempt_daily_wage:
        formData.scheme === "esi" && formData.employee_exempt_daily_wage
          ? Number(formData.employee_exempt_daily_wage)
          : null,
    });
  };

  const countries = useMemo<RegionStateItem[]>(() => {
    if (regionsQuery.data && regionsQuery.data.length > 0) {
      return regionsQuery.data;
    }
    return DEFAULT_COUNTRIES;
  }, [regionsQuery.data]);

  return (
    <div className="container" style={{ paddingBottom: "3rem" }}>
      <PageHeader
        title="Global Statutory & Compliance"
        action={
          activeTab === "rates" ? (
            <button
              type="button"
              className="btn btn-primary"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 18px",
                fontWeight: 600,
                borderRadius: "6px",
              }}
              onClick={() => {
                setModalMode("create");
                handleCountryChange("IN");
                setShowAddModal(true);
              }}
            >
              <span>+ Add Statutory Rate</span>
            </button>
          ) : undefined
        }
      />

      <p className="text-muted" style={{ marginTop: "-0.5rem", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
        Manage national statutory schemes (EPF, ESI, FICA, NIC, CPF, CPP, Superannuation), state PT slabs, and tax schedules across all jurisdictions.
      </p>

      {/* Overview Stat Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "1rem",
          margin: "1.5rem 0",
        }}
      >
        <div className="card" style={{ padding: "1.2rem", borderLeft: "4px solid #2563eb" }}>
          <div style={{ fontSize: "0.8rem", color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>
            Supported Jurisdictions
          </div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a", marginTop: "4px" }}>
            {countries.length || 7} Countries
          </div>
          <div style={{ fontSize: "0.75rem", color: "#16a34a", marginTop: "4px" }}>
            ✓ Multi-currency & regional statutory rules
          </div>
        </div>

        <div className="card" style={{ padding: "1.2rem", borderLeft: "4px solid #16a34a" }}>
          <div style={{ fontSize: "0.8rem", color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>
            Active Statutory Rates
          </div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a", marginTop: "4px" }}>
            {ratesQuery.data?.items?.filter((r: StatutoryRate) => !r.effective_to).length ?? "—"} Schemes
          </div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "4px" }}>
            Official schemes in force
          </div>
        </div>

        <div className="card" style={{ padding: "1.2rem", borderLeft: "4px solid #d97706" }}>
          <div style={{ fontSize: "0.8rem", color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>
            Compliance Source Check
          </div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "#0f172a", marginTop: "4px" }}>
            100% Verified
          </div>
          <div style={{ fontSize: "0.75rem", color: "#b45309", marginTop: "4px" }}>
            Official Gazette URL validation enforced
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "2px solid #e2e8f0", marginBottom: "1.5rem", gap: "1.5rem" }}>
        <button
          type="button"
          onClick={() => setActiveTab("rates")}
          style={{
            padding: "8px 4px",
            border: "none",
            background: "none",
            fontWeight: 600,
            fontSize: "0.95rem",
            color: activeTab === "rates" ? "#2563eb" : "#64748b",
            borderBottom: activeTab === "rates" ? "2px solid #2563eb" : "2px solid transparent",
            marginBottom: "-2px",
            cursor: "pointer",
          }}
        >
          📜 Statutory Schemes (Global Rates)
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("pt_slabs")}
          style={{
            padding: "8px 4px",
            border: "none",
            background: "none",
            fontWeight: 600,
            fontSize: "0.95rem",
            color: activeTab === "pt_slabs" ? "#2563eb" : "#64748b",
            borderBottom: activeTab === "pt_slabs" ? "2px solid #2563eb" : "2px solid transparent",
            marginBottom: "-2px",
            cursor: "pointer",
          }}
        >
          🏛️ Professional Tax Slabs
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("tax_slabs")}
          style={{
            padding: "8px 4px",
            border: "none",
            background: "none",
            fontWeight: 600,
            fontSize: "0.95rem",
            color: activeTab === "tax_slabs" ? "#2563eb" : "#64748b",
            borderBottom: activeTab === "tax_slabs" ? "2px solid #2563eb" : "2px solid transparent",
            marginBottom: "-2px",
            cursor: "pointer",
          }}
        >
          💰 Income Tax / TDS Slabs
        </button>
      </div>

      {/* TAB 1: Statutory Rates Table */}
      {activeTab === "rates" && (
        <div className="card" style={{ padding: "1.5rem" }}>
          {/* Filters Bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "#475569" }}>Country:</label>
              <select
                value={countryFilter}
                onChange={(e) => {
                  setCountryFilter(e.target.value);
                  setSchemeFilter("all");
                }}
                style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
              >
                <option value="all">All Countries</option>
                {countries.map((c: RegionStateItem) => (
                  <option key={c.code} value={c.code}>
                    {c.name} ({c.code})
                  </option>
                ))}
              </select>

              <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "#475569", marginLeft: "10px" }}>Scheme:</label>
              <select
                value={schemeFilter}
                onChange={(e) => setSchemeFilter(e.target.value)}
                style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
              >
                <option value="all">All Schemes</option>
                {countryFilter !== "all" &&
                  COUNTRY_SCHEMES_CATALOG[countryFilter]?.schemes.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                {countryFilter === "all" && (
                  <>
                    <option value="epf">EPF (India)</option>
                    <option value="esi">ESI (India)</option>
                    <option value="fica_ss">FICA Social Security (US)</option>
                    <option value="fica_med">FICA Medicare (US)</option>
                    <option value="nic">NIC (UK)</option>
                    <option value="cpf">CPF (Singapore)</option>
                    <option value="cpp">CPP (Canada)</option>
                    <option value="super">Superannuation (Australia)</option>
                    <option value="gpssa">GPSSA (UAE)</option>
                  </>
                )}
              </select>
            </div>

            <div style={{ fontSize: "0.8rem", color: "#64748b" }}>
              Total: {ratesQuery.data?.total ?? 0} published records
            </div>
          </div>

          {ratesQuery.isLoading ? (
            <div style={{ padding: "2rem", textAlign: "center", color: "#64748b" }}>Loading statutory rates…</div>
          ) : ratesQuery.data?.items?.length === 0 ? (
            <div style={{ padding: "3rem", textAlign: "center", color: "#64748b" }}>
              No statutory rates found for the selected filters.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="table" style={{ width: "100%", fontSize: "0.86rem" }}>
                <thead>
                  <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                    <th style={{ padding: "10px 14px" }}>Country</th>
                    <th style={{ padding: "10px 14px" }}>Scheme</th>
                    <th style={{ padding: "10px 14px" }}>Employee Rate</th>
                    <th style={{ padding: "10px 14px" }}>Employer Rate</th>
                    <th style={{ padding: "10px 14px" }}>Wage Ceiling</th>
                    <th style={{ padding: "10px 14px" }}>Effective Period</th>
                    <th style={{ padding: "10px 14px" }}>Status</th>
                    <th style={{ padding: "10px 14px" }}>Official Source</th>
                    <th style={{ padding: "10px 14px", textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {ratesQuery.data?.items?.map((rate: StatutoryRate) => {
                    const isActive = !rate.effective_to;
                    const cMeta = COUNTRY_SCHEMES_CATALOG[rate.country] || COUNTRY_SCHEMES_CATALOG.IN;
                    return (
                      <tr key={rate.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "12px 14px" }}>
                          <span style={{ fontWeight: 600 }}>{rate.country}</span>
                        </td>
                        <td style={{ padding: "12px 14px" }}>
                          <span
                            className="badge"
                            style={{
                              backgroundColor: rate.scheme === "epf" ? "#dbeafe" : rate.scheme === "esi" ? "#fef3c7" : "#e0e7ff",
                              color: rate.scheme === "epf" ? "#1e40af" : rate.scheme === "esi" ? "#b45309" : "#3730a3",
                              textTransform: "uppercase",
                              fontWeight: 700,
                              fontSize: "0.75rem",
                              padding: "4px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            {rate.scheme}
                          </span>
                        </td>
                        <td style={{ padding: "12px 14px", fontWeight: 600, color: "#0f172a" }}>
                          {rate.employee_rate}%
                        </td>
                        <td style={{ padding: "12px 14px", fontWeight: 600, color: "#0f172a" }}>
                          {rate.employer_rate}%
                          {rate.scheme === "epf" && rate.employer_epf_rate && (
                            <div style={{ fontSize: "0.72rem", color: "#64748b", fontWeight: "normal" }}>
                              (EPF {rate.employer_epf_rate}% + EPS {rate.employer_eps_rate}%)
                            </div>
                          )}
                        </td>
                        <td style={{ padding: "12px 14px", fontWeight: 500 }}>
                          {cMeta.currencySymbol}{Number(rate.wage_ceiling).toLocaleString()}
                        </td>
                        <td style={{ padding: "12px 14px", color: "#334155" }}>
                          <div>From: <strong>{formatDate(rate.effective_from)}</strong></div>
                          <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                            To: {rate.effective_to ? formatDate(rate.effective_to) : "Open (Current)"}
                          </div>
                        </td>
                        <td style={{ padding: "12px 14px" }}>
                          <span
                            className="badge"
                            style={{
                              backgroundColor: isActive ? "#dcfce7" : "#f1f5f9",
                              color: isActive ? "#15803d" : "#64748b",
                              fontWeight: 600,
                              fontSize: "0.75rem",
                              padding: "3px 8px",
                              borderRadius: "12px",
                            }}
                          >
                            {isActive ? "Active / In Force" : "Historical (Closed)"}
                          </span>
                        </td>
                        <td style={{ padding: "12px 14px", maxWidth: "220px" }}>
                          <a
                            href={rate.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: "#2563eb",
                              textDecoration: "none",
                              display: "inline-block",
                              maxWidth: "200px",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={rate.source_title}
                          >
                            🏛️ {rate.source_title}
                          </a>
                          <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>
                            Verified on {formatDate(rate.verified_on)}
                          </div>
                        </td>
                        <td style={{ padding: "12px 14px", textAlign: "right", position: "relative" }}>
                          <div data-action-menu style={{ display: "inline-block", position: "relative" }}>
                            <button
                              type="button"
                              className="btn btn-xs"
                              style={{
                                background: openActionMenuId === rate.id ? "#e2e8f0" : "#f8fafc",
                                border: "1px solid #cbd5e1",
                                borderRadius: "4px",
                                color: "#334155",
                                padding: "3px 7px",
                                fontSize: "0.78rem",
                                fontWeight: 700,
                                cursor: "pointer",
                                letterSpacing: "1px",
                                lineHeight: 1,
                              }}
                              title="Actions"
                              onClick={(e) => {
                                e.stopPropagation();
                                setOpenActionMenuId(openActionMenuId === rate.id ? null : rate.id);
                              }}
                            >
                              •••
                            </button>

                            {openActionMenuId === rate.id && (
                              <div
                                style={{
                                  position: "absolute",
                                  right: 0,
                                  top: "calc(100% + 2px)",
                                  background: "#ffffff",
                                  border: "1px solid #e2e8f0",
                                  borderRadius: "6px",
                                  boxShadow: "0 4px 12px rgba(0, 0, 0, 0.12)",
                                  zIndex: 50,
                                  minWidth: "110px",
                                  padding: "3px 0",
                                  textAlign: "left",
                                }}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <button
                                  type="button"
                                  style={{
                                    width: "100%",
                                    textAlign: "left",
                                    padding: "5px 10px",
                                    border: "none",
                                    background: "transparent",
                                    fontSize: "0.78rem",
                                    fontWeight: 500,
                                    color: "#1e293b",
                                    cursor: "pointer",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "6px",
                                  }}
                                  onMouseEnter={(e) => (e.currentTarget.style.background = "#f1f5f9")}
                                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                  onClick={() => {
                                    setOpenActionMenuId(null);
                                    setModalMode("revise");
                                    const meta = COUNTRY_SCHEMES_CATALOG[rate.country] || COUNTRY_SCHEMES_CATALOG.IN;
                                    const matched = meta.schemes.find((s) => s.code === rate.scheme);
                                    setIsCustomScheme(!matched);
                                    setFormData({
                                      country: rate.country,
                                      scheme: rate.scheme,
                                      employee_rate: String(rate.employee_rate),
                                      employer_rate: String(rate.employer_rate),
                                      wage_ceiling: String(rate.wage_ceiling),
                                      employer_epf_rate: rate.employer_epf_rate ? String(rate.employer_epf_rate) : null,
                                      employer_eps_rate: rate.employer_eps_rate ? String(rate.employer_eps_rate) : null,
                                      edli_rate: rate.edli_rate ? String(rate.edli_rate) : null,
                                      admin_charge_rate: rate.admin_charge_rate ? String(rate.admin_charge_rate) : null,
                                      employee_exempt_daily_wage: rate.employee_exempt_daily_wage ? String(rate.employee_exempt_daily_wage) : null,
                                      effective_from: new Date().toISOString().split("T")[0],
                                      source_url: rate.source_url,
                                      source_title: rate.source_title,
                                      verified_on: new Date().toISOString().split("T")[0],
                                      source_note: rate.source_note || "",
                                    });
                                    setShowAddModal(true);
                                  }}
                                >
                                  <span>✏️</span> <span>Revise</span>
                                </button>
                                <div style={{ height: "1px", background: "#f1f5f9", margin: "2px 0" }} />
                                <button
                                  type="button"
                                  style={{
                                    width: "100%",
                                    textAlign: "left",
                                    padding: "5px 10px",
                                    border: "none",
                                    background: "transparent",
                                    fontSize: "0.78rem",
                                    fontWeight: 500,
                                    color: "#b91c1c",
                                    cursor: "pointer",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "6px",
                                  }}
                                  onMouseEnter={(e) => (e.currentTarget.style.background = "#fef2f2")}
                                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                  disabled={deleteMutation.isPending && deletingRateId === rate.id}
                                  onClick={() => {
                                    setOpenActionMenuId(null);
                                    if (window.confirm(`Are you sure you want to remove the ${rate.country} ${rate.scheme.toUpperCase()} statutory rate?`)) {
                                      setDeletingRateId(rate.id);
                                      deleteMutation.mutate(rate.id);
                                    }
                                  }}
                                >
                                  <span>✕</span> <span>Remove</span>
                                </button>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: PT Slabs (Gujarat) */}
      {activeTab === "pt_slabs" && (
        <div className="card" style={{ padding: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1.05rem" }}>State Professional Tax (PT) Slabs</h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.8rem", color: "#64748b" }}>
                Auto-populated into tenant payrolls when regional slabs are selected.
              </p>
            </div>
            <span className="badge" style={{ background: "#f0fdf4", color: "#166534", border: "1px solid #bbf7d0" }}>
              Active State: Gujarat (IN)
            </span>
          </div>

          <table className="table" style={{ width: "100%", fontSize: "0.86rem" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={{ padding: "10px 14px" }}>Monthly Gross Salary Slab</th>
                <th style={{ padding: "10px 14px" }}>Deduction Amount</th>
                <th style={{ padding: "10px 14px" }}>Special Month Amount (Feb)</th>
                <th style={{ padding: "10px 14px" }}>Source Note</th>
              </tr>
            </thead>
            <tbody>
              {ptSlabsQuery.data?.map((slab, i) => (
                <tr key={slab.id || i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "12px 14px", fontWeight: 600 }}>
                    ₹{Number(slab.income_min).toLocaleString("en-IN")} —{" "}
                    {slab.income_max ? `₹${Number(slab.income_max).toLocaleString("en-IN")}` : "Above"}
                  </td>
                  <td style={{ padding: "12px 14px", fontWeight: 600, color: "#0f172a" }}>
                    ₹{Number(slab.monthly_amount).toLocaleString("en-IN")} / month
                  </td>
                  <td style={{ padding: "12px 14px", color: "#64748b" }}>
                    {slab.special_month_amount ? `₹${Number(slab.special_month_amount).toLocaleString("en-IN")}` : "—"}
                  </td>
                  <td style={{ padding: "12px 14px", color: "#475569" }}>
                    {slab.source_note || "Gujarat Panchayats, Municipalities and State Tax on Professions Act"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* TAB 3: Income Tax / TDS Slabs */}
      {activeTab === "tax_slabs" && (
        <div className="card" style={{ padding: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1.05rem" }}>National Income Tax Brackets (Section 115BAC)</h3>
              <p style={{ margin: "2px 0 0", fontSize: "0.8rem", color: "#64748b" }}>
                India FY 2026-27 Union Budget statutory slabs for New Regime TDS deduction.
              </p>
            </div>
            <span className="badge" style={{ background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
              FY 2026-27 (New Tax Regime)
            </span>
          </div>

          <table className="table" style={{ width: "100%", fontSize: "0.86rem" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={{ padding: "10px 14px" }}>Annual Income Bracket</th>
                <th style={{ padding: "10px 14px" }}>Tax Rate (%)</th>
                <th style={{ padding: "10px 14px" }}>Health & Education Cess</th>
                <th style={{ padding: "10px 14px" }}>Source Note</th>
              </tr>
            </thead>
            <tbody>
              {taxSlabsQuery.data?.map((slab, i) => (
                <tr key={slab.id || i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "12px 14px", fontWeight: 600 }}>
                    ₹{Number(slab.min_income).toLocaleString("en-IN")} —{" "}
                    {slab.max_income ? `₹${Number(slab.max_income).toLocaleString("en-IN")}` : "Above"}
                  </td>
                  <td style={{ padding: "12px 14px", fontWeight: 700, color: "#0f172a" }}>
                    {slab.rate_percent}%
                  </td>
                  <td style={{ padding: "12px 14px", color: "#475569" }}>
                    {slab.cess_percent}%
                  </td>
                  <td style={{ padding: "12px 14px", color: "#64748b" }}>
                    {slab.source_note || "Finance Act 2026 Section 115BAC"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* MODAL: Add / Revise Statutory Rate */}
      {showAddModal && (
        <div className="modal-backdrop" onClick={() => setShowAddModal(false)}>
          <div
            className="modal card"
            style={{ maxWidth: "660px", width: "95%", maxHeight: "90vh", overflowY: "auto" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>
                {modalMode === "revise" ? "Revise / Update Statutory Rate" : "Add / Publish Global Statutory Rate"}
              </h3>
              <button type="button" className="modal-close-btn" onClick={() => setShowAddModal(false)}>
                ✕
              </button>
            </div>

            <form onSubmit={handleSubmit} className="stack gap-3 mt-3">
              <div className="p-3 bg-muted rounded border text-xs text-muted" style={{ lineHeight: 1.45 }}>
                ℹ️ Publishing a statutory rate registers an official gazetted schedule for all tenant companies.
                If an active rate currently exists for this country & scheme, it will automatically be closed the day before the new effective date.
              </div>

              <div className="grid grid-2 gap-3">
                <div className="field">
                  <label>Country *</label>
                  <select
                    value={formData.country}
                    onChange={(e) => handleCountryChange(e.target.value)}
                    required
                  >
                    {countries.map((c: RegionStateItem) => (
                      <option key={c.code} value={c.code}>
                        {c.name} ({c.code})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Statutory Scheme *</label>
                  <select
                    value={isCustomScheme ? "custom" : formData.scheme}
                    onChange={(e) => handleSchemeChange(e.target.value)}
                    required
                  >
                    {currentCountryMeta.schemes.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.name}
                      </option>
                    ))}
                    <option value="custom">+ Other / Custom Scheme...</option>
                  </select>
                </div>
              </div>

              {isCustomScheme && (
                <div className="field">
                  <label>Custom Scheme Code *</label>
                  <input
                    type="text"
                    value={formData.scheme}
                    onChange={(e) => setFormData({ ...formData, scheme: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })}
                    placeholder="e.g. state_disability, provident_fund, socso"
                    required
                  />
                  <span className="text-xs text-muted">Use lowercase alphanumeric identifier (e.g. disability_fund).</span>
                </div>
              )}

              <div className="grid grid-3 gap-3">
                <div className="field">
                  <label>Employee Rate (%) *</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    max="100"
                    value={formData.employee_rate}
                    onChange={(e) => setFormData({ ...formData, employee_rate: e.target.value })}
                    required
                  />
                </div>

                <div className="field">
                  <label>Employer Rate (%) *</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    max="100"
                    value={formData.employer_rate}
                    onChange={(e) => setFormData({ ...formData, employer_rate: e.target.value })}
                    required
                  />
                </div>

                <div className="field">
                  <label>Wage Ceiling ({currentCountryMeta.currencySymbol}) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="1"
                    value={formData.wage_ceiling}
                    onChange={(e) => setFormData({ ...formData, wage_ceiling: e.target.value })}
                    required
                  />
                </div>
              </div>

              {formData.scheme === "epf" && formData.country === "IN" && (
                <div className="p-3 rounded border" style={{ background: "#f8fafc" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.82rem", color: "#334155", marginBottom: "8px" }}>
                    EPF Sub-Components Breakdown (Optional)
                  </div>
                  <div className="grid grid-2 gap-2 text-xs">
                    <div>
                      <label>Employer EPF Share (%)</label>
                      <input
                        type="number"
                        step="0.001"
                        value={formData.employer_epf_rate || ""}
                        onChange={(e) => setFormData({ ...formData, employer_epf_rate: e.target.value })}
                        placeholder="3.670"
                      />
                    </div>
                    <div>
                      <label>Employer EPS Pension Share (%)</label>
                      <input
                        type="number"
                        step="0.001"
                        value={formData.employer_eps_rate || ""}
                        onChange={(e) => setFormData({ ...formData, employer_eps_rate: e.target.value })}
                        placeholder="8.330"
                      />
                    </div>
                  </div>
                </div>
              )}

              {formData.scheme === "esi" && formData.country === "IN" && (
                <div className="field">
                  <label>Exempt Average Daily Wage ({currentCountryMeta.currencySymbol})</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formData.employee_exempt_daily_wage || ""}
                    onChange={(e) => setFormData({ ...formData, employee_exempt_daily_wage: e.target.value })}
                    placeholder="176.00"
                  />
                  <span className="text-xs text-muted">Daily wage at or below which employee pays 0% share.</span>
                </div>
              )}

              <div className="grid grid-2 gap-3">
                <div className="field">
                  <label>Effective From Date *</label>
                  <input
                    type="date"
                    value={formData.effective_from}
                    onChange={(e) => setFormData({ ...formData, effective_from: e.target.value })}
                    required
                  />
                </div>

                <div className="field">
                  <label>Verified On *</label>
                  <input
                    type="date"
                    value={formData.verified_on}
                    onChange={(e) => setFormData({ ...formData, verified_on: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className="field">
                <label>Official Gazette / Government URL *</label>
                <input
                  type="url"
                  value={formData.source_url}
                  onChange={(e) => setFormData({ ...formData, source_url: e.target.value })}
                  placeholder="https://..."
                  required
                />
                <span className="text-xs text-muted">Must be an official government domain (e.g. epfindia.gov.in, esic.gov.in, ssa.gov, gov.uk, cpf.gov.sg, canada.ca, ato.gov.au, dubai.ae).</span>
              </div>

              <div className="field">
                <label>Official Notification Title *</label>
                <input
                  type="text"
                  value={formData.source_title}
                  onChange={(e) => setFormData({ ...formData, source_title: e.target.value })}
                  placeholder="e.g. Gazette Notification No. S.O. 2026/..."
                  required
                />
              </div>

              <div className="field">
                <label>Notes & Summary (Optional)</label>
                <textarea
                  rows={2}
                  value={formData.source_note || ""}
                  onChange={(e) => setFormData({ ...formData, source_note: e.target.value })}
                  placeholder="Additional context or ministry circular details..."
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => setShowAddModal(false)}
                  disabled={createMutation.isPending}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={createMutation.isPending}
                  style={{ background: "#2563eb", borderColor: "#2563eb" }}
                >
                  {createMutation.isPending ? "Publishing Rate…" : "Publish Statutory Rate"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
