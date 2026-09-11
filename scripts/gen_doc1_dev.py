"""
Generate Document 1: Development Documentation for EMS Pro.
Outputs to: /Users/apple/Downloads/EMS/document/1_Development_Documentation.docx
"""
import os
import sys
from docx.shared import Inches, Pt, RGBColor
from scripts.docx_helper import (
    create_styled_document, add_cover_page, add_header_1, add_header_2,
    add_header_3, add_callout, add_styled_table, COLOR_DARK_TEXT
)

def build_dev_documentation():
    doc = create_styled_document()
    add_cover_page(
        doc,
        title="EMS Pro — Development Documentation",
        subtitle="Developer Environment Setup, Codebase Conventions, API Architecture & Verification",
        doc_type="Engineering & Development Guide"
    )

    # 1. Executive Summary & Purpose
    add_header_1(doc, "1. Executive Summary & Architecture Overview")
    doc.add_paragraph(
        "EMS Pro is an enterprise-grade multi-tenant SaaS application designed to manage Core HRMS, "
        "Time & Leave, Statutory Payroll Engine, Performance Cycles, Projects Workspace, and Platform Services. "
        "The system is built upon a hardened architecture utilizing FastAPI (Python 3.12), PostgreSQL 16 "
        "with Row-Level Security (RLS), Redis 7, Celery asynchronous workers, and React 18 with TypeScript on the frontend."
    )
    doc.add_paragraph(
        "This document provides the canonical developer onboarding reference, code organization standards, "
        "backend and frontend workflow guidelines, test automation frameworks, and deployment practices."
    )

    add_callout(
        doc,
        "Every tenant table in PostgreSQL is governed by database-enforced Row Level Security (RLS). "
        "Developers MUST NEVER query tenant-scoped models using raw un-scoped sessions or bypass tenant context binding.",
        title="CRITICAL SECURITY INVARIANT"
    )

    # 2. Technology Stack
    add_header_1(doc, "2. Comprehensive Technology Stack")
    tech_headers = ["Layer", "Technology", "Version", "Key Purpose & Responsibility"]
    tech_data = [
        ["Runtime", "Python", "3.12.x", "Core backend language leveraging modern typing and performance"],
        ["Framework", "FastAPI", "0.115.x", "Asynchronous ASGI web framework with Pydantic v2 validation"],
        ["ORM / DB Client", "SQLAlchemy", "2.0.x", "Mapped models with strict typing and unit-of-work transactions"],
        ["Migrations", "Alembic", "1.14.x", "Version-controlled database schema migrations with RLS helpers"],
        ["Database", "PostgreSQL", "16.x", "Relational database with Row-Level Security and transactional isolation"],
        ["Caching / Broker", "Redis", "7.x", "In-memory cache for distributed locks, rate-limiting & Celery broker"],
        ["Task Queue", "Celery", "5.4.x", "Asynchronous processing for payroll runs, report exports, and notifications"],
        ["Frontend UI", "React", "18.3.x", "Component-driven SPA architecture with custom design system"],
        ["Type Safety", "TypeScript", "5.x", "Strict type checking, end-to-end interface contracts"],
        ["Build Tool", "Vite", "8.2.x", "Lightning fast HMR, bundling, and CSS asset pipeline"],
        ["Password Security", "Argon2id (passlib)", "Latest", "Memory-hard password hashing resistant to GPU attacks"],
        ["Token Auth", "PyJWT", "2.x", "Stateless short-lived access tokens with HttpOnly refresh cookies"],
    ]
    add_styled_table(doc, tech_headers, tech_data, [Inches(1.1), Inches(1.1), Inches(0.8), Inches(3.5)])

    # 3. Codebase Organization
    add_header_1(doc, "3. Codebase Directory Structure & Conventions")
    doc.add_paragraph(
        "The EMS Pro codebase strictly adheres to modular domain-driven design. "
        "Every backend module in app/modules/<name>/ contains exactly 5 canonical files, each with a single responsibility:"
    )
    mod_headers = ["File Name", "Role", "Rules & Architectural Guardrails"]
    mod_data = [
        ["models.py", "SQLAlchemy Entities", "Table schema only. No business logic or queries. Inherits TenantBase or Base."],
        ["schemas.py", "Pydantic DTOs", "Request/Response serialization schemas with regex, validators, and config."],
        ["repository.py", "Data Access Layer", "SQLAlchemy queries only. No business validation or HTTP exceptions."],
        ["service.py", "Business Domain Logic", "Orchestrates transactions, business invariants, security checks, and math."],
        ["router.py", "FastAPI Endpoints", "HTTP route definitions, dependency injection, and HTTP status codes only."],
    ]
    add_styled_table(doc, mod_headers, mod_data, [Inches(1.4), Inches(1.8), Inches(3.3)])

    add_header_2(doc, "Complete Directory Tree")
    tree_text = (
        "EMS/\n"
        "├── app/\n"
        "│   ├── core/           # Config, security, exceptions, shared dependencies, RLS hooks\n"
        "│   ├── db/             # Base model, SessionLocal, Alembic env, seed scripts\n"
        "│   ├── modules/\n"
        "│   │   ├── identity/   # Auth, Companies, Users, Refresh Tokens, Password Reset\n"
        "│   │   ├── hr/         # Employees, Departments, Resignation, Offboarding, FnF\n"
        "│   │   ├── time_leave/ # Attendance, Shifts, Holidays, Leave Requests & Balances\n"
        "│   │   ├── payroll/    # Structures, Components, Payroll Runs, Payslips, Reimbursements\n"
        "│   │   ├── performance/# Cycles, Goals, Reviews, Ratings & Summaries\n"
        "│   │   ├── projects/   # Projects, Members, Tasks (Kanban), Time Entries, Milestones\n"
        "│   │   └── platform/   # Announcements, Signed Documents, Audit Trail, Global Search\n"
        "│   ├── workers/        # Celery task definitions and scheduled beat jobs\n"
        "│   └── main.py         # Application factory, middleware & route mounting\n"
        "├── frontend/\n"
        "│   ├── src/\n"
        "│   │   ├── app/        # AppLayout, Router, ApiClient, AuthContext, ToastContext\n"
        "│   │   ├── modules/    # UI pages, components & API clients mirroring backend domains\n"
        "│   │   └── shared/     # Design tokens, date formatters, breadcrumbs, modals, tabs\n"
        "├── tests/              # Pytest backend test suite (unit, integration & RLS isolation)\n"
        "├── scripts/            # Bootstrap, database seeders, role creation scripts\n"
        "└── document/           # Official Word Technical Documentation Artifacts\n"
    )
    p_tree = doc.add_paragraph()
    r_tree = p_tree.add_run(tree_text)
    r_tree.font.name = "Courier New"
    r_tree.font.size = Pt(8)

    # 4. Local Developer Environment Setup
    add_header_1(doc, "4. Step-by-Step Developer Setup Guide")
    doc.add_paragraph(
        "Setting up EMS Pro locally requires Python 3.12+, Node.js 20+, Docker (or local PostgreSQL 16 & Redis 7)."
    )

    add_header_2(doc, "4.1 Backend Setup")
    doc.add_paragraph("Follow these exact steps from the root directory:")
    steps_backend = [
        "1. Start Infrastructure Containers: docker compose up -d",
        "2. Create Virtual Environment: python3 -m venv venv && source venv/bin/activate",
        "3. Install Python Dependencies: pip install -e '.[dev]'",
        "4. Configure Environment Variables: cp .env.example .env (verify DATABASE_URL & REDIS_URL)",
        "5. Initialize Database Roles & Tables: ./scripts/setup.sh (runs bootstrap_roles.sql & migrations)",
        "6. Seed Realistic Multi-Tenant Data: ./venv/bin/python3 scripts/seed_realistic_data.py",
        "7. Seed Unique Company Projects: ./venv/bin/python3 scripts/seed_unique_company_projects.py",
        "8. Launch Development API Server: uvicorn app.main:app --reload --port 8000",
    ]
    for s in steps_backend:
        p = doc.add_paragraph(s)
        p.paragraph_format.left_indent = Inches(0.2)

    add_header_2(doc, "4.2 Frontend Setup")
    steps_frontend = [
        "1. Navigate to frontend directory: cd frontend",
        "2. Install Node Dependencies: npm install",
        "3. Start Vite Dev Server: npm run dev (accessible on http://localhost:5173)",
        "4. Verify Production Build: npm run build (validates TypeScript types & bundle size)",
    ]
    for s in steps_frontend:
        p = doc.add_paragraph(s)
        p.paragraph_format.left_indent = Inches(0.2)

    # 5. Security & Authentication Model
    add_header_1(doc, "5. Authentication, RBAC & Multi-Tenancy Invariants")
    doc.add_paragraph(
        "Security in EMS Pro is defense-in-depth, enforcing access control at the network, "
        "application service, and PostgreSQL storage engine layers."
    )

    add_header_2(doc, "5.1 Authentication Flow & Token Lifecycle")
    doc.add_paragraph(
        "1. Login Endpoint (/api/v1/auth/login): Validates email & password using Argon2id. "
        "Returns a short-lived (15 min) JWT access token in the response payload. "
        "Sets a 7-day secure HttpOnly refresh token cookie on path /api/v1/auth.\n"
        "2. Access Token: Contains standard claims: 'sub' (User UUID), 'company_id' (Tenant UUID), "
        "'role' (UserRole string), and 'exp'.\n"
        "3. Token Refresh (/api/v1/auth/refresh): Rotates the refresh token (family-based revocation "
        "detects token theft) and issues a new access token without requiring re-authentication."
    )

    add_header_2(doc, "5.2 PostgreSQL Row-Level Security (RLS) Mechanics")
    doc.add_paragraph(
        "PostgreSQL 16 RLS guarantees that queries cannot leak cross-tenant data even in the presence "
        "of application-level coding errors. Every tenant table has RLS enabled and forced:"
    )
    rls_code = (
        "ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;\n"
        "ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;\n\n"
        "CREATE POLICY tenant_isolation ON <table_name>\n"
        "  USING (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid\n"
        "         OR current_setting('app.is_platform_admin', true) = 'on')\n"
        "  WITH CHECK (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid\n"
        "              OR current_setting('app.is_platform_admin', true) = 'on');\n"
    )
    p_rls = doc.add_paragraph()
    r_rls = p_rls.add_run(rls_code)
    r_rls.font.name = "Courier New"
    r_rls.font.size = Pt(8)

    doc.add_paragraph(
        "In Python, the get_tenant_db FastAPI dependency automatically executes:\n"
        "  SELECT set_config('app.current_company_id', :company_id, true);\n"
        "  SELECT set_config('app.is_platform_admin', :is_admin, true);\n"
        "This configuration is transaction-scoped (is_local=true) and automatically re-applied "
        "after commit via SQLAlchemy Session after_begin hooks."
    )

    # 6. Coding Conventions & Best Practices
    add_header_1(doc, "6. Coding Standards & Error Handling Conventions")
    doc.add_paragraph(
        "Consistency across the 7 modules is maintained via standard patterns for errors, "
        "date formatting, database transactions, and component design:"
    )
    rules_headers = ["Domain Area", "Standard Requirement", "Implementation Pattern"]
    rules_data = [
        ["Date Formatting", "All UI dates must render as DD/MM/YYYY", "shared/utils/date.ts -> formatDate(d)"],
        ["Money / Salaries", "Precise financial calculations, no float math", "Python Decimal('100.00'), SQL Numeric(12,2)"],
        ["Exception Handling", "Standardized JSON error envelope", "app.core.exceptions.AppError -> {error: {code, message}}"],
        ["HTTP Statuses", "Predictable RESTful response codes", "201 Created, 200 OK, 204 No Content, 401, 403, 404, 409, 422"],
        ["Audit Trail", "Immutable record for high-risk operations", "AuditLogRepository -> log_action(company_id, user_id, action, ...)"],
        ["Forms & Validations", "Client validation + server-side Pydantic", "Pydantic Field(..., min_length=2, regex=...)"],
    ]
    add_styled_table(doc, rules_headers, rules_data, [Inches(1.5), Inches(2.2), Inches(2.8)])

    # 7. Testing & Quality Assurance
    add_header_1(doc, "7. Testing Strategy & Verification Pipeline")
    doc.add_paragraph(
        "EMS Pro has a test suite covering unit tests, service logic, API endpoints, "
        "and strict multi-tenant RLS isolation boundaries."
    )
    doc.add_paragraph(
        "Running tests locally:\n"
        "  pytest -v --cov=app                # Execute all tests with coverage\n"
        "  pytest tests/test_rls_isolation.py  # Cross-tenant data leakage tests\n"
        "  pytest tests/test_payroll_math.py   # Statutory PF/ESI/PT calculation tests\n"
        "  npm run test (in frontend)          # Execute frontend unit & utility tests"
    )

    add_callout(
        doc,
        "CI pipelines reject any pull request where test coverage drops or where test_rls_isolation "
        "fails to block cross-tenant read/write attempts.",
        title="CI / CD GATEWAY"
    )

    output_path = "/Users/apple/Downloads/EMS/document/1_Development_Documentation.docx"
    doc.save(output_path)
    print(f"✔ Successfully generated: {output_path}")

if __name__ == "__main__":
    build_dev_documentation()
