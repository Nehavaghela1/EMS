# Entity-Relationship Diagram

Every table currently in the schema (WP-01 through WP-14), grouped by module. Tables
without a shaded RLS note inherit `TenantBase` and carry an RLS policy scoped to
`company_id`; the three called out below are the deliberate exceptions (Spec §8, §7.2)
and are scoped in the repository layer instead — see the README's "Multi-tenancy and
row-level security" section for why.

`payroll_items`, `salary_structures`, `statutory_configs`, `performance_*` and
`project_*` tables are specified (Spec §9, §12) but not yet built — WP-16 through
WP-25 haven't run. They're omitted here rather than drawn as empty boxes.

```mermaid
erDiagram
    COMPANIES ||--o{ USERS : "employs (no RLS)"
    COMPANIES ||--o| COMPANY_SETTINGS : has
    COMPANIES ||--o{ DEPARTMENTS : owns
    COMPANIES ||--o{ EMPLOYEES : owns
    COMPANIES ||--o{ AUDIT_LOGS : "scoped to (nullable, no RLS)"
    USERS ||--o| USERS : approved_by
    USERS ||--o{ REFRESH_TOKENS : "issues (no RLS)"
    USERS |o--o| EMPLOYEES : "linked account"
    USERS ||--o{ AUDIT_LOGS : "acted as (no RLS)"
    USERS ||--o{ NOTIFICATIONS : receives
    USERS ||--o{ LEAVES : "approved by"
    DEPARTMENTS ||--o{ EMPLOYEES : contains
    DEPARTMENTS |o--o| EMPLOYEES : "headed by"
    DEPARTMENTS ||--o{ HOLIDAYS : "applies to (nullable)"
    EMPLOYEES ||--o| EMPLOYEES : "reports to"
    EMPLOYEES ||--o{ ATTENDANCE : logs
    EMPLOYEES ||--o{ EMPLOYEE_SHIFTS : "assigned"
    EMPLOYEES ||--o{ LEAVES : requests
    EMPLOYEES ||--o{ LEAVE_BALANCES : has
    SHIFTS ||--o{ EMPLOYEE_SHIFTS : "assigned via"
    LEAVE_TYPES ||--o{ LEAVES : categorizes
    LEAVE_TYPES ||--o{ LEAVE_BALANCES : tracks

    COMPANIES {
        uuid id PK
        string name
        string code UK
        string email UK
        enum status
        string country
        string currency
        uuid approved_by FK
    }
    USERS {
        uuid id PK
        uuid company_id FK
        string email
        string username
        string hashed_password
        enum role
        bool is_active
        bool must_change_password
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        string token_hash
        uuid replaced_by_id FK
        datetime expires_at
        datetime revoked_at
    }
    COMPANY_SETTINGS {
        uuid id PK
        uuid company_id FK
        enum leave_year_type
        enum payroll_working_days_basis
    }
    DEPARTMENTS {
        uuid id PK
        uuid company_id FK
        string name
        string description
        uuid head_employee_id FK
    }
    EMPLOYEES {
        uuid id PK
        uuid company_id FK
        uuid user_id FK
        string employee_code UK
        string first_name
        string last_name
        string email
        uuid department_id FK
        uuid reporting_manager_id FK
        enum employment_type
        date hire_date
        bool is_active
        enum invitation_status
    }
    ATTENDANCE {
        uuid id PK
        uuid company_id FK
        uuid employee_id FK
        date date
        datetime check_in
        datetime check_out
        decimal hours_worked
        enum status
        enum source
    }
    SHIFTS {
        uuid id PK
        uuid company_id FK
        string name
        time start_time
        time end_time
        int break_minutes
        decimal night_allowance
        bool is_active
    }
    EMPLOYEE_SHIFTS {
        uuid id PK
        uuid company_id FK
        uuid employee_id FK
        uuid shift_id FK
        date effective_from
        date effective_to
    }
    HOLIDAYS {
        uuid id PK
        uuid company_id FK
        string name
        date date
        bool is_optional
        uuid applies_to_department_id FK
    }
    LEAVE_TYPES {
        uuid id PK
        uuid company_id FK
        string name
        string code
        decimal annual_allowance
        decimal carry_forward_limit
        bool requires_approval
        bool is_paid
    }
    LEAVES {
        uuid id PK
        uuid company_id FK
        uuid employee_id FK
        uuid leave_type_id FK
        date start_date
        date end_date
        bool is_half_day
        enum status
        uuid approved_by FK
    }
    LEAVE_BALANCES {
        uuid id PK
        uuid company_id FK
        uuid employee_id FK
        uuid leave_type_id FK
        int year
        decimal opening_balance
        decimal allocated
        decimal used
        decimal encashed
    }
    AUDIT_LOGS {
        uuid id PK
        uuid company_id FK "nullable, no RLS"
        uuid actor_user_id FK
        string actor_email
        string action
        string entity_type
        uuid entity_id
        jsonb details
        datetime created_at
    }
    NOTIFICATIONS {
        uuid id PK
        uuid company_id FK
        uuid user_id FK
        string type
        string message
        bool is_read
        datetime created_at
    }
    INDUSTRY_PRESETS {
        uuid id PK
        string industry_name UK
        jsonb departments_json
        jsonb leave_types_json
    }
```

`INDUSTRY_PRESETS` is platform-level reference data (no `company_id`, seeded once by
`scripts/setup.sh`) and has no relationship to any tenant table — it's read by the
company-registration form to suggest starter departments, not joined against.
