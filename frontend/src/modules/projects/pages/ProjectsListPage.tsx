import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProjects, createProject, updateProject } from "../api";
import type { Project, ProjectStatus } from "../types";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";
import { apiClient } from "../../../app/api-client";
import type { Page } from "../../../shared/api/pagination";
import type { CompanyResponse } from "../../identity/api";

import { PageHeader } from "../../../shared/components/PageHeader";
import { formatDate } from "../../../shared/utils/date";

export function ProjectsListPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [companies, setCompanies] = useState<CompanyResponse[]>([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [showModal, setShowModal] = useState(false);

  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [formCompanyId, setFormCompanyId] = useState("");
  const [clientName, setClientName] = useState("");
  const [budget, setBudget] = useState("");
  const [startDate, setStartDate] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("active");
  const [submitting, setSubmitting] = useState(false);

  const { user } = useAuth();
  const { notify } = useToast();
  const isSuperAdmin = user?.role === "super_admin";
  const canManage = user?.role === "hr_admin" || isSuperAdmin || user?.role === "manager";

  useEffect(() => {
    if (isSuperAdmin) {
      apiClient.get<Page<CompanyResponse>>("/companies", { params: { limit: 100 } })
        .then((res) => {
          setCompanies(res.data.items || []);
        })
        .catch((err) => {
          console.error("Failed to load companies:", err);
        });
    }
  }, [isSuperAdmin]);

  async function loadProjects() {
    try {
      setLoading(true);
      const data = await fetchProjects(
        filterStatus === "all" ? undefined : filterStatus,
        isSuperAdmin ? (selectedCompanyId === "all" ? undefined : selectedCompanyId) : undefined
      );
      setProjects(data);
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to load projects", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, [filterStatus, selectedCompanyId]);

  function openCreateModal() {
    setEditingProjectId(null);
    setName("");
    setCode("");
    setFormCompanyId("");
    setClientName("");
    setBudget("");
    setStartDate("");
    setDeadline("");
    setDescription("");
    setStatus("active");
    setShowModal(true);
  }

  function openEditModal(proj: Project) {
    setEditingProjectId(proj.id);
    setName(proj.name);
    setCode(proj.code);
    setFormCompanyId(proj.company_id || "");
    setClientName(proj.client_name || "");
    setBudget(proj.budget ? String(proj.budget) : "");
    setStartDate(proj.start_date ? proj.start_date.slice(0, 10) : "");
    setDeadline(proj.deadline ? proj.deadline.slice(0, 10) : "");
    setDescription(proj.description || "");
    setStatus(proj.status);
    setShowModal(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !code) {
      notify("Name and Code are required", "error");
      return;
    }
    try {
      setSubmitting(true);
      if (editingProjectId) {
        await updateProject(editingProjectId, {
          name,
          code,
          client_name: clientName || undefined,
          budget: budget ? parseFloat(budget) : undefined,
          start_date: startDate || undefined,
          deadline: deadline || undefined,
          description: description || undefined,
          status,
        });
        notify("Project updated successfully!", "success");
      } else {
        await createProject({
          name,
          code,
          company_id: isSuperAdmin && formCompanyId ? formCompanyId : undefined,
          client_name: clientName || undefined,
          budget: budget ? parseFloat(budget) : undefined,
          start_date: startDate || undefined,
          deadline: deadline || undefined,
          description: description || undefined,
          status,
        });
        notify("Project created successfully!", "success");
      }
      setShowModal(false);
      loadProjects();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to save project", "error");
    } finally {
      setSubmitting(false);
    }
  }

  const statusColors: Record<ProjectStatus, string> = {
    active: "badge-success",
    planning: "badge-muted",
    on_hold: "badge-warning",
    completed: "badge-primary",
    cancelled: "badge-danger",
  };

  return (
    <div>
      <PageHeader
        title="Projects"
        breadcrumb="Projects & Work"
        action={
          canManage ? (
            <button className="btn btn-primary" onClick={openCreateModal}>
              + Create Project
            </button>
          ) : undefined
        }
      />

      {/* Super Admin Company Selector & Filter Toolbar */}
      <div className="stack" style={{ gap: "1rem", marginBottom: "var(--space-5)" }}>
        {isSuperAdmin && (
          <div
            className="card"
            style={{
              padding: "0.85rem 1.25rem",
              background: "var(--surface-sunken, #f8fafc)",
              border: "1px solid var(--border-color, #e2e8f0)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "1rem",
            }}
          >
            <div>
              <strong style={{ fontSize: "0.95rem" }}>🏢 Enterprise Company Filter</strong>
              <p className="text-muted" style={{ margin: 0, fontSize: "0.8rem" }}>
                Filter projects across all registered corporate organizations
              </p>
            </div>
            <select
              value={selectedCompanyId}
              onChange={(e) => setSelectedCompanyId(e.target.value)}
              style={{ width: "260px" }}
            >
              <option value="all">All Companies</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="tab-bar">
          {(["all", "planning", "active", "on_hold", "completed", "cancelled"] as const).map((st) => (
            <button
              key={st}
              type="button"
              className={`tab-item ${filterStatus === st ? "active" : ""}`}
              onClick={() => setFilterStatus(st)}
            >
              {st === "all" ? "All Projects" : st.replace("_", " ").charAt(0).toUpperCase() + st.replace("_", " ").slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Projects Grid */}
      {loading ? (
        <p className="text-muted">Loading projects...</p>
      ) : projects.length === 0 ? (
        <div className="card text-center" style={{ padding: "3rem" }}>
          <p className="text-muted">No projects found for the selected company and filter.</p>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "1.25rem" }}>
          {projects.map((proj) => (
            <div
              key={proj.id}
              className="card stack"
              style={{ justifyContent: "space-between", cursor: "pointer" }}
              onDoubleClick={() => openEditModal(proj)}
              title="Double-click to edit project"
            >
              <div className="stack" style={{ gap: "0.75rem" }}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.25rem" }}>
                      <span className="badge badge-muted" style={{ fontSize: "0.75rem" }}>
                        {proj.code}
                      </span>
                      {proj.company_name && (
                        <span
                          className="badge"
                          style={{
                            fontSize: "0.7rem",
                            background: "rgba(37, 99, 235, 0.1)",
                            color: "var(--color-primary, #2563eb)",
                            border: "1px solid rgba(37, 99, 235, 0.2)",
                          }}
                        >
                          🏢 {proj.company_name}
                        </span>
                      )}
                    </div>
                    <h3 style={{ margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <Link to={`/projects/${proj.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                        {proj.name}
                      </Link>
                    </h3>
                    {proj.client_name && <span className="text-muted" style={{ fontSize: "0.85rem", display: "block", marginTop: "2px" }}>Client: {proj.client_name}</span>}
                  </div>
                  <div className="flex items-center gap-1">
                    <span className={`badge ${statusColors[proj.status] || "badge-muted"}`}>
                      {proj.status.replace("_", " ")}
                    </span>
                    {canManage && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{
                          padding: "4px 6px",
                          borderRadius: "4px",
                          color: "#64748b",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          openEditModal(proj);
                        }}
                        title="Edit Project"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {proj.description && (
                  <p className="text-muted" style={{ fontSize: "0.9rem", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                    {proj.description}
                  </p>
                )}
              </div>

              <div className="stack" style={{ gap: "0.75rem", marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--border-color, #e2e8f0)" }}>
                <div className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
                  <span>Budget:</span>
                  <strong>{proj.budget ? `$${Number(proj.budget).toLocaleString()}` : "N/A"}</strong>
                </div>
                <div className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
                   <span>Deadline:</span>
                   <span className="text-muted">{proj.deadline ? formatDate(proj.deadline) : "Unscheduled"}</span>
                 </div>
                <div className="flex gap-2 items-center">
                  <Link to={`/projects/${proj.id}`} className="btn btn-secondary btn-sm" style={{ flex: 1, textAlign: "center" }}>
                    View Workspace →
                  </Link>
                  {canManage && (
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      style={{ padding: "0.35rem 0.65rem", display: "flex", alignItems: "center", gap: "4px" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        openEditModal(proj);
                      }}
                      title="Edit Project"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                      Edit
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal card stack" style={{ maxWidth: "520px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>{editingProjectId ? "Edit Project" : "+ Create New Project"}</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSave} className="stack gap-4 my-2">
              {isSuperAdmin && !editingProjectId && (
                <div className="field">
                  <label>Assign to Company *</label>
                  <select
                    value={formCompanyId}
                    onChange={(e) => setFormCompanyId(e.target.value)}
                    required
                  >
                    <option value="">-- Select Target Company --</option>
                    {companies.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.code})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="field">
                <label>Project Name *</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Mobile App Redesign"
                  required
                />
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Project Code *</label>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                    placeholder="e.g. MAP-01"
                    required
                  />
                </div>
                <div className="field">
                  <label>Status</label>
                  <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}>
                    <option value="planning">Planning</option>
                    <option value="active">Active</option>
                    <option value="on_hold">On Hold</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Client Name</label>
                  <input
                    type="text"
                    value={clientName}
                    onChange={(e) => setClientName(e.target.value)}
                    placeholder="Acme Corp"
                  />
                </div>
                <div className="field">
                  <label>Budget ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    placeholder="25000"
                  />
                </div>
              </div>

              <div className="grid-2">
                <div className="field">
                  <label>Start Date</label>
                  <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                </div>
                <div className="field">
                  <label>Deadline</label>
                  <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
                </div>
              </div>

              <div className="field">
                <label>Description</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Project scope and goals..."
                />
              </div>

              <div className="flex gap-2 justify-end mt-4">
                <button type="button" className="btn btn-ghost" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
