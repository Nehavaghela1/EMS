import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProjects, createProject } from "../api";
import type { Project, ProjectStatus } from "../types";
import { useAuth } from "../../../app/auth-context";
import { useToast } from "../../../app/toast-context";

import { PageHeader } from "../../../shared/components/PageHeader";

export function ProjectsListPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [showModal, setShowModal] = useState(false);

  // Form State
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [clientName, setClientName] = useState("");
  const [budget, setBudget] = useState("");
  const [startDate, setStartDate] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("active");
  const [submitting, setSubmitting] = useState(false);

  const { user } = useAuth();
  const { notify } = useToast();
  const canManage = user?.role === "hr_admin" || user?.role === "super_admin" || user?.role === "manager";

  async function loadProjects() {
    try {
      setLoading(true);
      const data = await fetchProjects(filterStatus === "all" ? undefined : filterStatus);
      setProjects(data);
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to load projects", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, [filterStatus]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !code) {
      notify("Name and Code are required", "error");
      return;
    }
    try {
      setSubmitting(true);
      await createProject({
        name,
        code,
        client_name: clientName || undefined,
        budget: budget ? parseFloat(budget) : undefined,
        start_date: startDate || undefined,
        deadline: deadline || undefined,
        description: description || undefined,
        status,
      });
      notify("Project created successfully!", "success");
      setShowModal(false);
      setName("");
      setCode("");
      setClientName("");
      setBudget("");
      setStartDate("");
      setDeadline("");
      setDescription("");
      loadProjects();
    } catch (err: any) {
      notify(err?.response?.data?.error?.message || err?.message || "Failed to create project", "error");
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
            <button className="btn btn-primary" onClick={() => setShowModal(true)}>
              + Create Project
            </button>
          ) : undefined
        }
      />

      {/* Filter Toolbar */}
      <div className="tab-bar mb-6" style={{ marginBottom: "var(--space-5)" }}>
        {(["all", "active", "planning", "on_hold", "completed", "cancelled"] as const).map((st) => (
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

      {/* Projects Grid */}
      {loading ? (
        <p className="text-muted">Loading projects...</p>
      ) : projects.length === 0 ? (
        <div className="card text-center" style={{ padding: "3rem" }}>
          <p className="text-muted">No projects found for the selected filter.</p>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "1.25rem" }}>
          {projects.map((proj) => (
            <div key={proj.id} className="card stack" style={{ justifyContent: "space-between" }}>
              <div className="stack" style={{ gap: "0.75rem" }}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <span className="badge badge-muted" style={{ fontSize: "0.75rem", marginBottom: "0.25rem" }}>
                      {proj.code}
                    </span>
                    <h3 style={{ margin: 0 }}>
                      <Link to={`/projects/${proj.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                        {proj.name}
                      </Link>
                    </h3>
                    {proj.client_name && <span className="text-muted" style={{ fontSize: "0.85rem" }}>Client: {proj.client_name}</span>}
                  </div>
                  <span className={`badge ${statusColors[proj.status] || "badge-muted"}`}>
                    {proj.status.replace("_", " ")}
                  </span>
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
                  <span className="text-muted">{proj.deadline || "Unscheduled"}</span>
                </div>
                <Link to={`/projects/${proj.id}`} className="btn btn-secondary btn-sm" style={{ width: "100%", textAlign: "center" }}>
                  View Project Workspace →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal card stack" style={{ maxWidth: "500px", width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header" style={{ marginBottom: "var(--space-2)" }}>
              <h3>Create New Project</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowModal(false)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreate} className="stack gap-4 my-2">
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
