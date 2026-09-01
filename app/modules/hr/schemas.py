import uuid
from datetime import datetime

from pydantic import BaseModel


class DepartmentCreateRequest(BaseModel):
    name: str
    description: str | None = None


class DepartmentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    head_employee_id: uuid.UUID | None = None


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    head_employee_id: uuid.UUID | None
    # Always 0 until `employees` exists (WP-07) — there is nothing to count
    # yet. Route 31 asks for "live employee counts"; the field is here now so
    # the response shape doesn't change later, but the number isn't real yet.
    employee_count: int
    created_at: datetime
