from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError, NotFoundError, ConflictError, ForbiddenError, ValidationError
)
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectSummaryResponse,
    ProjectMemberCreate, ProjectMemberResponse,
    TaskCreate, TaskUpdate, TaskResponse,
    TaskCommentCreate, TaskCommentResponse,
    TimeEntryCreate, TimeEntryUpdate, TimeEntryResponse,
    MilestoneCreate, MilestoneUpdate, MilestoneResponse
)

class ProjectService:
    def __init__(self, db: Session):
        self.repo = ProjectRepository(db)

    # --- Projects ---
    def create_project(self, company_id: UUID, data: ProjectCreate) -> ProjectResponse:
        existing = self.repo.get_project_by_code(company_id, data.code)
        if existing:
            raise ConflictException(f"Project with code '{data.code}' already exists.")
        project = self.repo.create_project(company_id, data)
        return ProjectResponse.from_orm(project)

    def get_project(self, company_id: UUID, project_id: UUID) -> ProjectResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        return ProjectResponse.from_orm(project)

    def list_projects(self, company_id: UUID, status: Optional[str] = None) -> List[ProjectResponse]:
        projects = self.repo.list_projects(company_id, status)
        return [ProjectResponse.from_orm(p) for p in projects]

    def update_project(self, company_id: UUID, project_id: UUID, data: ProjectUpdate) -> ProjectResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        if data.code and data.code != project.code:
            existing = self.repo.get_project_by_code(company_id, data.code)
            if existing:
                raise ConflictException(f"Project with code '{data.code}' already exists.")
        updated = self.repo.update_project(project, data)
        return ProjectResponse.from_orm(updated)

    def delete_project(self, company_id: UUID, project_id: UUID) -> None:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        self.repo.delete_project(project)

    # --- Project Summary Analytics ---
    def get_project_summary(self, company_id: UUID, project_id: UUID) -> ProjectSummaryResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        tasks = self.repo.list_tasks(company_id, project_id)
        members = self.repo.list_members(company_id, project_id)
        entries = self.repo.list_time_entries(company_id, project_id=project_id)
        milestones = self.repo.list_milestones(company_id, project_id)

        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status == "done")
        today = date.today()
        overdue_tasks = sum(1 for t in tasks if t.due_date and t.due_date < today and t.status != "done")

        completion_pct = Decimal("0.00")
        if total_tasks > 0:
            completion_pct = (Decimal(completed_tasks) / Decimal(total_tasks) * Decimal("100.00")).quantize(Decimal("0.01"))

        total_logged_hours = sum((e.hours for e in entries), Decimal("0.00"))
        total_billable_hours = sum((e.hours for e in entries if e.is_billable), Decimal("0.00"))

        milestones_count = len(milestones)
        completed_milestones = sum(1 for m in milestones if m.status == "completed")

        return ProjectSummaryResponse(
            project=ProjectResponse.from_orm(project),
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            overdue_tasks=overdue_tasks,
            completion_percentage=completion_pct,
            total_logged_hours=total_logged_hours,
            total_billable_hours=total_billable_hours,
            members_count=len(members),
            milestones_count=milestones_count,
            completed_milestones_count=completed_milestones
        )

    # --- Project Members ---
    def add_member(self, company_id: UUID, project_id: UUID, data: ProjectMemberCreate) -> ProjectMemberResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        existing = self.repo.get_member(company_id, project_id, data.employee_id)
        if existing:
            raise ConflictException("Employee is already a member of this project.")
        member = self.repo.add_member(company_id, project_id, data)
        return ProjectMemberResponse.from_orm(member)

    def list_members(self, company_id: UUID, project_id: UUID) -> List[ProjectMemberResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        members = self.repo.list_members(company_id, project_id)
        return [ProjectMemberResponse.from_orm(m) for m in members]

    def remove_member(self, company_id: UUID, project_id: UUID, employee_id: UUID) -> None:
        member = self.repo.get_member(company_id, project_id, employee_id)
        if not member:
            raise NotFoundException("Project member not found.")
        self.repo.remove_member(member)

    # --- Tasks ---
    def create_task(self, company_id: UUID, project_id: UUID, created_by: Optional[UUID], data: TaskCreate) -> TaskResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        task = self.repo.create_task(company_id, project_id, created_by, data)
        return TaskResponse.from_orm(task)

    def get_task(self, company_id: UUID, task_id: UUID) -> TaskResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        return TaskResponse.from_orm(task)

    def list_tasks(self, company_id: UUID, project_id: UUID, status: Optional[str] = None, assigned_to: Optional[UUID] = None) -> List[TaskResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        tasks = self.repo.list_tasks(company_id, project_id, status, assigned_to)
        return [TaskResponse.from_orm(t) for t in tasks]

    def update_task(self, company_id: UUID, task_id: UUID, data: TaskUpdate) -> TaskResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        updated = self.repo.update_task(task, data)
        return TaskResponse.from_orm(updated)

    def delete_task(self, company_id: UUID, task_id: UUID) -> None:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        self.repo.delete_task(task)

    # --- Task Comments ---
    def add_comment(self, company_id: UUID, task_id: UUID, user_id: UUID, data: TaskCommentCreate) -> TaskCommentResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        comment = self.repo.add_comment(company_id, task_id, user_id, data.comment)
        return TaskCommentResponse.from_orm(comment)

    def list_comments(self, company_id: UUID, task_id: UUID) -> List[TaskCommentResponse]:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        comments = self.repo.list_comments(company_id, task_id)
        return [TaskCommentResponse.from_orm(c) for c in comments]

    # --- Time Entries ---
    def create_time_entry(self, company_id: UUID, employee_id: UUID, data: TimeEntryCreate) -> TimeEntryResponse:
        project = self.repo.get_project_by_id(company_id, data.project_id)
        if not project:
            raise NotFoundError("Project not found.")
        if data.task_id:
            task = self.repo.get_task_by_id(company_id, data.task_id)
            if not task:
                raise NotFoundError("Task not found.")

        # Check total daily logged hours ceiling (max 24 hrs per day)
        existing_entries = self.repo.list_time_entries(company_id, employee_id=employee_id, start_date=data.date, end_date=data.date)
        daily_total = sum((e.hours for e in existing_entries), Decimal("0.00"))
        if daily_total + data.hours > Decimal("24.00"):
            raise AppError(f"Total logged hours for {data.date} cannot exceed 24 hours. (Current total: {daily_total})")

        entry = self.repo.create_time_entry(company_id, employee_id, data)
        return TimeEntryResponse.from_orm(entry)

    def list_time_entries(
        self,
        company_id: UUID,
        project_id: Optional[UUID] = None,
        employee_id: Optional[UUID] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[TimeEntryResponse]:
        entries = self.repo.list_time_entries(company_id, project_id, employee_id, status, start_date, end_date)
        return [TimeEntryResponse.from_orm(e) for e in entries]

    def update_time_entry(self, company_id: UUID, entry_id: UUID, user_employee_id: Optional[UUID], data: TimeEntryUpdate) -> TimeEntryResponse:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        if user_employee_id and entry.employee_id != user_employee_id and entry.status != "draft":
            raise ForbiddenError("You can only modify your own time entries.")

        if data.hours is not None:
            existing_entries = self.repo.list_time_entries(company_id, employee_id=entry.employee_id, start_date=entry.date, end_date=entry.date)
            daily_total = sum((e.hours for e in existing_entries if e.id != entry.id), Decimal("0.00"))
            if daily_total + data.hours > Decimal("24.00"):
                raise AppError(f"Total logged hours for {entry.date} cannot exceed 24 hours.")

        updated = self.repo.update_time_entry(entry, data)
        return TimeEntryResponse.from_orm(updated)

    def approve_reject_time_entry(self, company_id: UUID, entry_id: UUID, status: str, approver_user_id: UUID) -> TimeEntryResponse:
        if status not in ("approved", "rejected"):
            raise AppError("Status must be either 'approved' or 'rejected'.")
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        updated = self.repo.approve_reject_time_entry(entry, status, approver_user_id)
        return TimeEntryResponse.from_orm(updated)

    def delete_time_entry(self, company_id: UUID, entry_id: UUID) -> None:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        self.repo.delete_time_entry(entry)

    # --- Milestones ---
    def create_milestone(self, company_id: UUID, project_id: UUID, data: MilestoneCreate) -> MilestoneResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        milestone = self.repo.create_milestone(company_id, project_id, data)
        return MilestoneResponse.from_orm(milestone)

    def list_milestones(self, company_id: UUID, project_id: UUID) -> List[MilestoneResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        milestones = self.repo.list_milestones(company_id, project_id)
        return [MilestoneResponse.from_orm(m) for m in milestones]

    def update_milestone(self, company_id: UUID, milestone_id: UUID, data: MilestoneUpdate) -> MilestoneResponse:
        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")
        updated = self.repo.update_milestone(milestone, data)
        return MilestoneResponse.from_orm(updated)

    def delete_milestone(self, company_id: UUID, milestone_id: UUID) -> None:
        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")
        self.repo.delete_milestone(milestone)
