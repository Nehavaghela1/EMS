from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError


class PageParams(BaseModel):
    page: int = 1
    limit: int = 20


def page_params(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PageParams:
    return PageParams(page=page, limit=limit)


class Page[T](BaseModel):
    """The standard list envelope — identical everywhere (Spec 10.1)."""

    items: list[T]
    page: int
    limit: int
    total: int
    pages: int
    has_next: bool


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list, int, int]:
    """Applies LIMIT/OFFSET to `stmt` (already filtered and sorted) and
    returns (rows, total, pages) for the standard envelope (10.1).
    """
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(params.limit).offset((params.page - 1) * params.limit)).all())
    pages = (total + params.limit - 1) // params.limit if total else 0
    return rows, total, pages


def resolve_sort(sort: str | None, allowed: dict[str, Any], default: Any) -> Any:
    """`sort` is a column name, `-` prefix for descending. Only columns on an
    explicit allowlist per endpoint — never interpolate a raw client string
    into ORDER BY (10.1). An invalid column is rejected (400), not silently
    dropped or interpolated.
    """
    if not sort:
        return default
    descending = sort.startswith("-")
    key = sort[1:] if descending else sort
    column = allowed.get(key)
    if column is None:
        raise ValidationError(f"Invalid sort column: {key}", details={"field": "sort"})
    return column.desc() if descending else column.asc()
