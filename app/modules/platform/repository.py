from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.platform.models import IndustryPreset


class IndustryPresetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, industry_name: str) -> IndustryPreset | None:
        return self.db.scalar(
            select(IndustryPreset).where(IndustryPreset.industry_name == industry_name)
        )

    def list_all(self) -> list[IndustryPreset]:
        return list(self.db.scalars(select(IndustryPreset).order_by(IndustryPreset.industry_name)))
