from datetime import date
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_tenant_db, get_current_user, require_role
from app.modules.identity.models import User, UserRole
from app.modules.projects.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectSummaryResponse,
    ProjectMemberCreate, ProjectMemberResponse,
    TaskCreate, TaskUpdate, TaskResponse,
    TaskCommentCreate, TaskCommentResponse,
    TimeEntryCreate, TimeEntryUpdate, TimeEntryResponse,
    MilestoneCreate, MilestoneUpdate, MilestoneResponse
)
from app.modules.projects.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])

# --- Projects (Routes 100-104) ---

@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.create_project(current_user.company_id, data)

@router.get("", response_model=List[ProjectResponse])
def list_projects(
    status: Optional[str] = Query(None, pattern="^(planning|active|on_hold|completed|cancelled)$"),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.list_projects(current_user.company_id, status)

# --- Time Entries / Timesheets (Routes 115-118) ---

@router.post("/time-entries", response_model=TimeEntryResponse, status_code=status.HTTP_201_CREATED)
def create_time_entry(
    data: TimeEntryCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    from app.modules.hr.repository import EmployeeRepository
    from app.core.exceptions import AppError
    emp = EmployeeRepository(db).get_by_user_id(current_user.company_id, current_user.id)
    if not emp:
        raise AppError("User profile is not linked to an employee record.")
    service = ProjectService(db)
    return service.create_time_entry(current_user.company_id, emp.id, data)

@router.get("/time-entries", response_model=List[TimeEntryResponse])
def list_time_entries(
    project_id: Optional[UUID] = Query(None),
    employee_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None, pattern="^(draft|submitted|approved|rejected)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    target_employee_id = employee_id
    if current_user.role == UserRole.employee:
        from app.modules.hr.repository import EmployeeRepository
        emp = EmployeeRepository(db).get_by_user_id(current_user.company_id, current_user.id)
        target_employee_id = emp.id if emp else None
    return service.list_time_entries(current_user.company_id, project_id, target_employee_id, status, start_date, end_date)

@router.put("/time-entries/{entry_id}", response_model=TimeEntryResponse)
def update_time_entry(
    entry_id: UUID,
    data: TimeEntryUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    user_emp_id = None
    if current_user.role == UserRole.employee:
        from app.modules.hr.repository import EmployeeRepository
        emp = EmployeeRepository(db).get_by_user_id(current_user.company_id, current_user.id)
        user_emp_id = emp.id if emp else None
    return service.update_time_entry(current_user.company_id, entry_id, user_emp_id, data)

@router.post("/time-entries/{entry_id}/approve", response_model=TimeEntryResponse)
def approve_time_entry(
    entry_id: UUID,
    status_action: str = Query("approved", pattern="^(approved|rejected)$"),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.approve_reject_time_entry(current_user.company_id, entry_id, status_action, current_user.id)

@router.delete("/time-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_entry(
    entry_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    service.delete_time_entry(current_user.company_id, entry_id)

# --- Tasks & Task Comments Specific Endpoints (not starting with {project_id}) ---

@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.get_task(current_user.company_id, task_id)

@router.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: UUID,
    data: TaskUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.update_task(current_user.company_id, task_id, data)

@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    service.delete_task(current_user.company_id, task_id)

@router.post("/tasks/{task_id}/comments", response_model=TaskCommentResponse, status_code=status.HTTP_201_CREATED)
def add_task_comment(
    task_id: UUID,
    data: TaskCommentCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.add_comment(current_user.company_id, task_id, current_user.id, data)

@router.get("/tasks/{task_id}/comments", response_model=List[TaskCommentResponse])
def list_task_comments(
    task_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.list_comments(current_user.company_id, task_id)

# --- Milestones Global Update/Delete ---

@router.put("/milestones/{milestone_id}", response_model=MilestoneResponse)
def update_milestone(
    milestone_id: UUID,
    data: MilestoneUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.update_milestone(current_user.company_id, milestone_id, data)

@router.delete("/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_milestone(
    milestone_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    service.delete_milestone(current_user.company_id, milestone_id)

# --- Dynamic Project ID Routes ---

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.get_project(current_user.company_id, project_id)

@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.update_project(current_user.company_id, project_id, data)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin))
):
    service = ProjectService(db)
    service.delete_project(current_user.company_id, project_id)

@router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
def get_project_summary(
    project_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.get_project_summary(current_user.company_id, project_id)

# --- Project Members (Routes 105-107) ---

@router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=status.HTTP_201_CREATED)
def add_project_member(
    project_id: UUID,
    data: ProjectMemberCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.add_member(current_user.company_id, project_id, data)

@router.get("/{project_id}/members", response_model=List[ProjectMemberResponse])
def list_project_members(
    project_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.list_members(current_user.company_id, project_id)

@router.delete("/{project_id}/members/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_member(
    project_id: UUID,
    employee_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    service.remove_member(current_user.company_id, project_id, employee_id)

# --- Project Tasks (Routes 108-112) ---

@router.post("/{project_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: UUID,
    data: TaskCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.create_task(current_user.company_id, project_id, current_user.id, data)

@router.get("/{project_id}/tasks", response_model=List[TaskResponse])
def list_tasks(
    project_id: UUID,
    status: Optional[str] = Query(None, pattern="^(todo|in_progress|review|done)$"),
    assigned_to: Optional[UUID] = Query(None),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.list_tasks(current_user.company_id, project_id, status, assigned_to)

# --- Project Milestones (Routes 119-120) ---

@router.post("/{project_id}/milestones", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED)
def create_milestone(
    project_id: UUID,
    data: MilestoneCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(require_role(UserRole.super_admin, UserRole.hr_admin, UserRole.manager))
):
    service = ProjectService(db)
    return service.create_milestone(current_user.company_id, project_id, data)

@router.get("/{project_id}/milestones", response_model=List[MilestoneResponse])
def list_milestones(
    project_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = ProjectService(db)
    return service.list_milestones(current_user.company_id, project_id)
