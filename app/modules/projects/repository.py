from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.modules.projects.models import (
    Project, ProjectMember, Task, TaskComment, TimeEntry, Milestone
)
from app.modules.projects.schemas import (
    ProjectCreate, ProjectUpdate, ProjectMemberCreate,
    TaskCreate, TaskUpdate, TaskCommentCreate,
    TimeEntryCreate, TimeEntryUpdate, MilestoneCreate, MilestoneUpdate
)

class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Projects ---
    def create_project(self, company_id: UUID, data: ProjectCreate) -> Project:
        project = Project(
            company_id=company_id,
            **data.dict()
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get_project_by_id(self, company_id: UUID, project_id: UUID) -> Optional[Project]:
        return self.db.query(Project).filter(
            Project.company_id == company_id,
            Project.id == project_id
        ).first()

    def get_project_by_code(self, company_id: UUID, code: str) -> Optional[Project]:
        return self.db.query(Project).filter(
            Project.company_id == company_id,
            Project.code == code
        ).first()

    def list_projects(self, company_id: UUID, status: Optional[str] = None) -> List[Project]:
        query = self.db.query(Project).filter(Project.company_id == company_id)
        if status:
            query = query.filter(Project.status == status)
        return query.order_by(Project.created_at.desc()).all()

    def update_project(self, project: Project, data: ProjectUpdate) -> Project:
        update_data = data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(project, key, value)
        project.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete_project(self, project: Project) -> None:
        self.db.delete(project)
        self.db.commit()

    # --- Members ---
    def add_member(self, company_id: UUID, project_id: UUID, data: ProjectMemberCreate) -> ProjectMember:
        member = ProjectMember(
            company_id=company_id,
            project_id=project_id,
            employee_id=data.employee_id,
            role=data.role,
            joined_at=data.joined_at or date.today()
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def get_member(self, company_id: UUID, project_id: UUID, employee_id: UUID) -> Optional[ProjectMember]:
        return self.db.query(ProjectMember).filter(
            ProjectMember.company_id == company_id,
            ProjectMember.project_id == project_id,
            ProjectMember.employee_id == employee_id
        ).first()

    def list_members(self, company_id: UUID, project_id: UUID) -> List[ProjectMember]:
        return self.db.query(ProjectMember).filter(
            ProjectMember.company_id == company_id,
            ProjectMember.project_id == project_id
        ).all()

    def remove_member(self, member: ProjectMember) -> None:
        self.db.delete(member)
        self.db.commit()

    # --- Tasks ---
    def create_task(self, company_id: UUID, project_id: UUID, created_by: Optional[UUID], data: TaskCreate) -> Task:
        task = Task(
            company_id=company_id,
            project_id=project_id,
            created_by=created_by,
            **data.dict()
        )
        if data.status == "done":
            task.completed_at = datetime.utcnow()
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_task_by_id(self, company_id: UUID, task_id: UUID) -> Optional[Task]:
        return self.db.query(Task).filter(
            Task.company_id == company_id,
            Task.id == task_id
        ).first()

    def list_tasks(self, company_id: UUID, project_id: UUID, status: Optional[str] = None, assigned_to: Optional[UUID] = None) -> List[Task]:
        query = self.db.query(Task).filter(
            Task.company_id == company_id,
            Task.project_id == project_id
        )
        if status:
            query = query.filter(Task.status == status)
        if assigned_to:
            query = query.filter(Task.assigned_to == assigned_to)
        return query.order_by(Task.created_at.desc()).all()

    def update_task(self, task: Task, data: TaskUpdate) -> Task:
        update_data = data.dict(exclude_unset=True)
        if "status" in update_data:
            if update_data["status"] == "done" and task.status != "done":
                task.completed_at = datetime.utcnow()
            elif update_data["status"] != "done" and task.status == "done":
                task.completed_at = None
        for key, value in update_data.items():
            setattr(task, key, value)
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def delete_task(self, task: Task) -> None:
        self.db.delete(task)
        self.db.commit()

    # --- Task Comments ---
    def add_comment(self, company_id: UUID, task_id: UUID, user_id: UUID, comment: str) -> TaskComment:
        tc = TaskComment(
            company_id=company_id,
            task_id=task_id,
            user_id=user_id,
            comment=comment
        )
        self.db.add(tc)
        self.db.commit()
        self.db.refresh(tc)
        return tc

    def list_comments(self, company_id: UUID, task_id: UUID) -> List[TaskComment]:
        return self.db.query(TaskComment).filter(
            TaskComment.company_id == company_id,
            TaskComment.task_id == task_id
        ).order_by(TaskComment.created_at.asc()).all()

    # --- Time Entries ---
    def create_time_entry(self, company_id: UUID, employee_id: UUID, data: TimeEntryCreate) -> TimeEntry:
        entry = TimeEntry(
            company_id=company_id,
            employee_id=employee_id,
            **data.dict()
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def get_time_entry_by_id(self, company_id: UUID, entry_id: UUID) -> Optional[TimeEntry]:
        return self.db.query(TimeEntry).filter(
            TimeEntry.company_id == company_id,
            TimeEntry.id == entry_id
        ).first()

    def list_time_entries(
        self,
        company_id: UUID,
        project_id: Optional[UUID] = None,
        employee_id: Optional[UUID] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[TimeEntry]:
        query = self.db.query(TimeEntry).filter(TimeEntry.company_id == company_id)
        if project_id:
            query = query.filter(TimeEntry.project_id == project_id)
        if employee_id:
            query = query.filter(TimeEntry.employee_id == employee_id)
        if status:
            query = query.filter(TimeEntry.status == status)
        if start_date:
            query = query.filter(TimeEntry.date >= start_date)
        if end_date:
            query = query.filter(TimeEntry.date <= end_date)
        return query.order_by(TimeEntry.date.desc()).all()

    def update_time_entry(self, entry: TimeEntry, data: TimeEntryUpdate) -> TimeEntry:
        update_data = data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(entry, key, value)
        entry.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def approve_reject_time_entry(self, entry: TimeEntry, status: str, approved_by: UUID) -> TimeEntry:
        entry.status = status
        entry.approved_by = approved_by
        entry.approved_at = datetime.utcnow()
        entry.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def delete_time_entry(self, entry: TimeEntry) -> None:
        self.db.delete(entry)
        self.db.commit()

    # --- Milestones ---
    def create_milestone(self, company_id: UUID, project_id: UUID, data: MilestoneCreate) -> Milestone:
        milestone = Milestone(
            company_id=company_id,
            project_id=project_id,
            **data.dict()
        )
        if data.status == "completed" or data.completion_percentage == Decimal("100.00"):
            milestone.completed_at = datetime.utcnow()
        self.db.add(milestone)
        self.db.commit()
        self.db.refresh(milestone)
        return milestone

    def get_milestone_by_id(self, company_id: UUID, milestone_id: UUID) -> Optional[Milestone]:
        return self.db.query(Milestone).filter(
            Milestone.company_id == company_id,
            Milestone.id == milestone_id
        ).first()

    def list_milestones(self, company_id: UUID, project_id: UUID) -> List[Milestone]:
        return self.db.query(Milestone).filter(
            Milestone.company_id == company_id,
            Milestone.project_id == project_id
        ).order_by(Milestone.due_date.asc().nulls_last()).all()

    def update_milestone(self, milestone: Milestone, data: MilestoneUpdate) -> Milestone:
        update_data = data.dict(exclude_unset=True)
        if "status" in update_data:
            if update_data["status"] == "completed" and milestone.status != "completed":
                milestone.completed_at = datetime.utcnow()
                milestone.completion_percentage = Decimal("100.00")
            elif update_data["status"] != "completed" and milestone.status == "completed":
                milestone.completed_at = None
        if "completion_percentage" in update_data:
            if update_data["completion_percentage"] == Decimal("100.00") and milestone.status != "completed":
                milestone.status = "completed"
                milestone.completed_at = datetime.utcnow()

        for key, value in update_data.items():
            setattr(milestone, key, value)
        milestone.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(milestone)
        return milestone

    def delete_milestone(self, milestone: Milestone) -> None:
        self.db.delete(milestone)
        self.db.commit()
