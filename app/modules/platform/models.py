from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimeStampedBase


class IndustryPreset(TimeStampedBase):
    """RLS: No — global seed data (Spec 7.8). Applied automatically when a
    company is approved (WP-05)."""

    __tablename__ = "industry_presets"
    __table_args__ = (Index("uq_industry_presets_industry_name", "industry_name", unique=True),)

    industry_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # [{"name": "Engineering", "description": "..."}, ...] — applied to
    # `departments` on approval (WP-05/WP-06).
    departments_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    # [{"name": "Annual Leave", "code": "annual", "annual_allowance": 18, ...}, ...]
    # — applied to `leave_types` once that table exists (WP-10).
    leave_types_json: Mapped[list] = mapped_column(JSONB, nullable=False)
