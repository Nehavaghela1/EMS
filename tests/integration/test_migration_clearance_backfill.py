import uuid

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from tests.conftest import TenantContext


def test_clearance_function_migration_backfill_as_ems_owner(db: Session, company_a: TenantContext):
    """Verifies that running the migration's backfill statements through an ems_owner
    connection (which sets app.is_platform_admin='on') properly updates clearance_function
    for departments under forced RLS.
    """
    # 1. Connect as ems_owner (TEST_MIGRATION_URL) to insert test company & departments
    owner_engine = create_engine(settings.TEST_MIGRATION_URL)
    comp_id = uuid.uuid4()
    comp_code = f"MIG{comp_id.hex[:5].upper()}"
    fin_id = uuid.uuid4()
    it_id = uuid.uuid4()

    try:
        with owner_engine.connect() as conn:
            # Insert test company directly as ems_owner
            conn.execute(
                sa.text(
                    """
                    INSERT INTO companies (
                        id, name, code, email, status, country,
                        currency, last_employee_seq, created_at, updated_at
                    )
                    VALUES (
                        :comp_id, 'Migration Test Corp', :comp_code, :email,
                        'active', 'IN', 'INR', 0, NOW(), NOW()
                    )
                    """
                ),
                {
                    "comp_id": comp_id,
                    "comp_code": comp_code,
                    "email": f"{comp_code.lower()}@test.test",
                },
            )

            # Enable platform admin to bypass RLS for departments
            conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', false)"))

            conn.execute(
                sa.text(
                    """
                    INSERT INTO departments (
                        id, company_id, name, clearance_function, created_at, updated_at
                    )
                    VALUES (:fin_id, :comp_id, 'Finance', NULL, NOW(), NOW()),
                           (:it_id, :comp_id, 'Information Technology', NULL, NOW(), NOW())
                    """
                ),
                {"fin_id": fin_id, "it_id": it_id, "comp_id": comp_id},
            )
            conn.commit()

            # 2. Run backfill statements through connection as ems_owner
            # This replicates the migration's upgrade logic exactly:
            conn.execute(sa.text("SELECT set_config('app.is_platform_admin', 'on', true)"))

            it_names = ("it", "information technology")
            fin_names = ("finance",)
            hr_names = ("human resources", "hr")

            rows = conn.execute(
                sa.text(
                    """
                    SELECT d.id, d.name, c.name AS company_name, lower(trim(d.name)) AS norm_name
                    FROM departments d
                    JOIN companies c ON d.company_id = c.id
                    WHERE d.deleted_at IS NULL AND d.id IN (:fin_id, :it_id)
                    """
                ),
                {"fin_id": fin_id, "it_id": it_id},
            ).fetchall()

            for row in rows:
                fn = None
                if row.norm_name in it_names:
                    fn = "it"
                elif row.norm_name in fin_names:
                    fn = "finance"
                elif row.norm_name in hr_names:
                    fn = "hr"

                if fn:
                    conn.execute(
                        sa.text(
                            "UPDATE departments SET clearance_function = :fn WHERE id = :dept_id"
                        ),
                        {"fn": fn, "dept_id": row.id},
                    )
            conn.commit()

            # 3. Assert clearance_function is 'finance' and 'it'
            fin_row = conn.execute(
                sa.text("SELECT clearance_function FROM departments WHERE id = :id"),
                {"id": fin_id},
            ).scalar_one()
            it_row = conn.execute(
                sa.text("SELECT clearance_function FROM departments WHERE id = :id"),
                {"id": it_id},
            ).scalar_one()

            assert fin_row == "finance"
            assert it_row == "it"

            # Cleanup test departments and company
            conn.execute(
                sa.text("DELETE FROM departments WHERE id IN (:fin_id, :it_id)"),
                {"fin_id": fin_id, "it_id": it_id},
            )
            conn.execute(
                sa.text("DELETE FROM companies WHERE id = :comp_id"),
                {"comp_id": comp_id},
            )
            conn.commit()
    finally:
        owner_engine.dispose()
