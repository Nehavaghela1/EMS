"""create employee profile section tables with rls

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
Create Date: 2026-10-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = "8d9e0f1a2b3c"
down_revision: Union[str, Sequence[str], None] = "7c8d9e0f1a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. employee_addresses
    op.create_table(
        "employee_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("line1", sa.String(length=255), nullable=False),
        sa.Column("line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('current', 'permanent')", name="ck_employee_addresses_kind"),
    )
    op.create_index(op.f("ix_employee_addresses_company_id"), "employee_addresses", ["company_id"], unique=False)
    op.create_index("ix_employee_addresses_company_employee", "employee_addresses", ["company_id", "employee_id"], unique=False)
    op.create_index(
        "uq_employee_addresses_employee_kind",
        "employee_addresses",
        ["employee_id", "kind"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_rls("employee_addresses")

    # 2. employee_emergency_contacts
    op.create_table(
        "employee_emergency_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("relationship", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("alt_phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_employee_emergency_contacts_company_id"), "employee_emergency_contacts", ["company_id"], unique=False)
    op.create_index("ix_employee_emergency_contacts_company_employee", "employee_emergency_contacts", ["company_id", "employee_id"], unique=False)
    enable_rls("employee_emergency_contacts")

    # 3. employee_skills
    op.create_table(
        "employee_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("level IN ('beginner', 'intermediate', 'advanced', 'expert')", name="ck_employee_skills_level"),
        sa.CheckConstraint("years_experience >= 0 AND years_experience <= 60", name="ck_employee_skills_years_experience"),
    )
    op.create_index(op.f("ix_employee_skills_company_id"), "employee_skills", ["company_id"], unique=False)
    op.create_index("ix_employee_skills_company_employee", "employee_skills", ["company_id", "employee_id"], unique=False)
    op.create_index(
        "uq_employee_skills_employee_lower_name",
        "employee_skills",
        ["employee_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_rls("employee_skills")

    # 4. employee_education
    op.create_table(
        "employee_education",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution", sa.String(length=200), nullable=False),
        sa.Column("degree", sa.String(length=150), nullable=False),
        sa.Column("field_of_study", sa.String(length=150), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("grade", sa.String(length=50), nullable=True),
        sa.Column("verification_status", sa.String(length=20), server_default="unverified", nullable=False),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("verification_status IN ('unverified', 'verified')", name="ck_employee_education_verification_status"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_employee_education_end_after_start"),
    )
    op.create_index(op.f("ix_employee_education_company_id"), "employee_education", ["company_id"], unique=False)
    op.create_index("ix_employee_education_company_employee", "employee_education", ["company_id", "employee_id"], unique=False)
    enable_rls("employee_education")

    # 5. employee_experience
    op.create_table(
        "employee_experience",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employer", sa.String(length=200), nullable=False),
        sa.Column("job_title", sa.String(length=150), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=20), server_default="unverified", nullable=False),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("verification_status IN ('unverified', 'verified')", name="ck_employee_experience_verification_status"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_employee_experience_end_after_start"),
    )
    op.create_index(op.f("ix_employee_experience_company_id"), "employee_experience", ["company_id"], unique=False)
    op.create_index("ix_employee_experience_company_employee", "employee_experience", ["company_id", "employee_id"], unique=False)
    enable_rls("employee_experience")


def downgrade() -> None:
    op.drop_table("employee_experience")
    op.drop_table("employee_education")
    op.drop_table("employee_skills")
    op.drop_table("employee_emergency_contacts")
    op.drop_table("employee_addresses")

