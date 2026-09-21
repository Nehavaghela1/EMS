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
    MilestoneCreate, MilestoneUpdate, MilestoneResponse,
    ProjectDocumentCreate, ProjectDocumentResponse
)

class ProjectService:
    def __init__(self, db: Session):
        self.repo = ProjectRepository(db)

    def _to_project_response(self, project) -> ProjectResponse:
        resp = ProjectResponse.from_orm(project)
        if getattr(project, "company", None):
            resp.company_name = project.company.name
        else:
            from app.modules.identity.models import Company
            comp = self.repo.db.query(Company).filter(Company.id == project.company_id).first()
            if comp:
                resp.company_name = comp.name
        return resp

    # --- Projects ---
    def create_project(self, company_id: UUID, data: ProjectCreate) -> ProjectResponse:
        target_company_id = data.company_id or company_id
        existing = self.repo.get_project_by_code(target_company_id, data.code)
        if existing:
            raise ConflictError(f"Project with code '{data.code}' already exists.")
        project_dict = data.dict(exclude={"company_id"})
        project = self.repo.create_project(target_company_id, ProjectCreate(**project_dict))
        return self._to_project_response(project)

    def get_project(self, company_id: Optional[UUID], project_id: UUID) -> ProjectResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        return self._to_project_response(project)

    def list_projects(self, company_id: Optional[UUID] = None, status: Optional[str] = None) -> List[ProjectResponse]:
        projects = self.repo.list_projects(company_id, status)
        return [self._to_project_response(p) for p in projects]

    def update_project(self, company_id: Optional[UUID], project_id: UUID, data: ProjectUpdate) -> ProjectResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        if data.code and data.code != project.code:
            existing = self.repo.get_project_by_code(project.company_id, data.code)
            if existing:
                raise ConflictError(f"Project with code '{data.code}' already exists.")
        updated = self.repo.update_project(project, data)
        return self._to_project_response(updated)

    def delete_project(self, company_id: Optional[UUID], project_id: UUID) -> None:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        self.repo.delete_project(project)

    # --- Project Summary Analytics ---
    def get_project_summary(self, company_id: Optional[UUID], project_id: UUID) -> ProjectSummaryResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Always use project's actual company_id for sub-entities
        p_cid = project.company_id
        tasks = self.repo.list_tasks(p_cid, project_id)
        members = self.repo.list_members(p_cid, project_id)
        entries = self.repo.list_time_entries(p_cid, project_id=project_id)
        milestones = self.repo.list_milestones(p_cid, project_id)

        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status == "done")
        today = date.today()
        overdue_tasks = sum(1 for t in tasks if t.due_date and t.due_date < today and t.status != "done")

        completion_pct = Decimal("0.00")
        if total_tasks > 0:
            completion_pct = (Decimal(completed_tasks) / Decimal(total_tasks) * Decimal("100.00")).quantize(Decimal("0.01"))

        total_logged_hours = sum((e.hours for e in entries), Decimal("0.00"))
        total_billable_hours = sum((e.hours for e in entries if e.is_billable), Decimal("0.00"))

        # Filter approved entries for financial budget burn calculations
        approved_entries = [e for e in entries if e.status == "approved"]
        approved_logged_hours = sum((e.hours for e in approved_entries), Decimal("0.00"))
        approved_billable_entries = [e for e in approved_entries if e.is_billable]
        approved_billable_hours = sum((e.hours for e in approved_billable_entries), Decimal("0.00"))

        # Calculate Budget Spent = sum(approved billable hours * employee hourly cost)
        budget_spent = Decimal("0.00")
        if approved_billable_entries:
            from app.modules.payroll.models import EmployeeSalary
            # Fetch salaries for all relevant employees
            emp_ids = list({e.employee_id for e in approved_billable_entries})
            salaries = (
                self.repo.db.query(EmployeeSalary)
                .filter(
                    EmployeeSalary.company_id == p_cid,
                    EmployeeSalary.employee_id.in_(emp_ids),
                    EmployeeSalary.deleted_at.is_(None)
                )
                .order_by(EmployeeSalary.effective_from.desc())
                .all()
            )
            # Map employee_id -> hourly rate
            emp_rates = {}
            for s in salaries:
                if s.employee_id not in emp_rates:
                    if s.hourly_rate is not None and s.hourly_rate > 0:
                        emp_rates[s.employee_id] = s.hourly_rate
                    elif s.ctc and s.ctc > 0:
                        # Monthly CTC / 160 standard Indian convention
                        emp_rates[s.employee_id] = (s.ctc / Decimal("12") / Decimal("160.00")).quantize(Decimal("0.01"))

            for e in approved_billable_entries:
                rate = emp_rates.get(e.employee_id, Decimal("500.00"))  # Default fallback rate ₹500/hr
                budget_spent += (Decimal(str(e.hours)) * rate)
            budget_spent = budget_spent.quantize(Decimal("0.01"))

        budget_remaining = None
        if project.budget is not None:
            budget_remaining = (project.budget - budget_spent).quantize(Decimal("0.01"))

        # Delivery Health progression: Not Started -> In Progress -> On Schedule (or Needs Attention)
        has_in_progress_tasks = any(t.status == "in_progress" for t in tasks)
        if overdue_tasks > 0:
            delivery_health = "Needs Attention"
        elif total_tasks == 0 and total_logged_hours == 0:
            delivery_health = "Not Started"
        elif completion_pct == 0 and (total_logged_hours > 0 or has_in_progress_tasks):
            delivery_health = "In Progress"
        elif completion_pct == 0:
            delivery_health = "Not Started"
        else:
            delivery_health = "On Schedule"

        milestones_count = len(milestones)
        completed_milestones = sum(1 for m in milestones if m.status == "completed")

        return ProjectSummaryResponse(
            project=self._to_project_response(project),
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            overdue_tasks=overdue_tasks,
            completion_percentage=completion_pct,
            total_logged_hours=total_logged_hours,
            total_billable_hours=total_billable_hours,
            members_count=len(members),
            milestones_count=milestones_count,
            completed_milestones_count=completed_milestones,
            budget_spent=budget_spent,
            budget_remaining=budget_remaining,
            delivery_health=delivery_health,
            approved_billable_hours=approved_billable_hours,
            approved_logged_hours=approved_logged_hours
        )

    # --- Project Members ---
    def add_member(self, company_id: Optional[UUID], project_id: UUID, data: ProjectMemberCreate) -> ProjectMemberResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        p_cid = project.company_id
        existing = self.repo.get_member(p_cid, project_id, data.employee_id)
        if existing:
            raise ConflictError("Employee is already a member of this project.")
        member = self.repo.add_member(p_cid, project_id, data)
        resp = ProjectMemberResponse.from_orm(member)
        from app.modules.hr.models import Employee, Department
        emp_data = (
            self.repo.db.query(Employee, Department.name.label("dept_name"))
            .outerjoin(Department, Employee.department_id == Department.id)
            .filter(Employee.id == data.employee_id)
            .first()
        )
        if emp_data:
            emp, dept_name = emp_data
            resp.employee_name = f"{emp.first_name} {emp.last_name or ''}".strip()
            resp.employee_email = emp.email
            resp.employee_code = emp.employee_code
            resp.designation = emp.position or "Staff"
            resp.department_name = dept_name or "General"
        return resp

    def list_members(self, company_id: Optional[UUID], project_id: UUID) -> List[ProjectMemberResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        results = self.repo.list_members_with_details(project.company_id, project_id)
        responses = []
        for m, emp, dept_name in results:
            resp = ProjectMemberResponse.from_orm(m)
            if emp:
                resp.employee_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                resp.employee_email = emp.email
                resp.employee_code = emp.employee_code
                resp.designation = emp.position or "Staff"
                resp.department_name = dept_name or "General"
            responses.append(resp)
        return responses

    def remove_member(self, company_id: Optional[UUID], project_id: UUID, employee_id: UUID) -> None:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        member = self.repo.get_member(project.company_id, project_id, employee_id)
        if not member:
            raise NotFoundError("Project member not found.")
        self.repo.remove_member(member)

    # --- Tasks ---
    def _enrich_task_response(self, task) -> TaskResponse:
        resp = TaskResponse.from_orm(task)
        if task.assigned_to:
            from app.modules.hr.models import Employee
            emp = self.repo.db.query(Employee).filter(Employee.id == task.assigned_to).first()
            if emp:
                resp.assigned_to_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                resp.assigned_to_email = emp.email
                resp.assigned_to_code = emp.employee_code
                resp.assigned_to_designation = emp.position or "Staff"
        return resp

    def create_task(self, company_id: Optional[UUID], project_id: UUID, created_by: Optional[UUID], data: TaskCreate) -> TaskResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        task = self.repo.create_task(project.company_id, project_id, created_by, data)
        return self._enrich_task_response(task)

    def get_task(self, company_id: Optional[UUID], task_id: UUID) -> TaskResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        return self._enrich_task_response(task)

    def list_tasks(self, company_id: Optional[UUID], project_id: UUID, status: Optional[str] = None, assigned_to: Optional[UUID] = None) -> List[TaskResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        results = self.repo.list_tasks_with_details(project.company_id, project_id, status, assigned_to)
        responses = []
        for t, emp in results:
            resp = TaskResponse.from_orm(t)
            if emp:
                resp.assigned_to_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                resp.assigned_to_email = emp.email
                resp.assigned_to_code = emp.employee_code
                resp.assigned_to_designation = emp.position or "Staff"
            responses.append(resp)
        return responses

    def update_task(
        self,
        company_id: Optional[UUID],
        task_id: UUID,
        data: TaskUpdate,
        current_emp_id: Optional[UUID] = None,
        is_admin_or_manager: bool = False
    ) -> TaskResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")

        # Permission check: If not admin/manager, employee must be assignee or project lead
        if not is_admin_or_manager and current_emp_id:
            is_assignee = task.assigned_to == current_emp_id
            is_lead = False
            if task.company_id and task.project_id:
                member = self.repo.get_member(task.company_id, task.project_id, current_emp_id)
                if member and member.role == "lead":
                    is_lead = True
            if not is_assignee and not is_lead:
                raise ForbiddenError("Only the task assignee or Project Lead can modify this task.")

        updated = self.repo.update_task(task, data)
        return self._enrich_task_response(updated)

    def delete_task(self, company_id: Optional[UUID], task_id: UUID) -> None:
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
    def create_time_entry(
        self,
        company_id: UUID,
        employee_id: UUID,
        data: TimeEntryCreate,
        is_admin_or_manager: bool = False
    ) -> TimeEntryResponse:
        project = self.repo.get_project_by_id(company_id, data.project_id)
        if not project:
            raise NotFoundError("Project not found.")
        if data.task_id:
            task = self.repo.get_task_by_id(company_id, data.task_id)
            if not task:
                raise NotFoundError("Task not found.")
            # Server-side validation: Regular employees can only log time against their own assigned tasks
            if not is_admin_or_manager:
                # Check if employee is Project Lead
                is_lead = False
                member = self.repo.get_member(company_id, data.project_id, employee_id)
                if member and member.role == "lead":
                    is_lead = True

                if task.assigned_to and task.assigned_to != employee_id and not is_lead:
                    assignee_name = task.assigned_to_name if hasattr(task, "assigned_to_name") else "another teammate"
                    raise ForbiddenError(f"You cannot log time against a task assigned to {assignee_name}. Employees can only log hours on their own assigned tasks.")

        # Check total daily logged hours ceiling (max 14 hrs per day across all tasks combined)
        existing_entries = self.repo.list_time_entries(company_id, employee_id=employee_id, start_date=data.date, end_date=data.date)
        daily_total = sum((e.hours for e in existing_entries), Decimal("0.00"))
        if daily_total + data.hours > Decimal("14.00"):
            raise AppError(f"Total logged time across all projects cannot exceed 14 hours per day. (Currently logged: {daily_total} hrs, attempting: {data.hours} hrs)")

        entry = self.repo.create_time_entry(company_id, employee_id, data)
        resp = TimeEntryResponse.from_orm(entry)
        from app.modules.hr.models import Employee
        emp = self.repo.db.query(Employee).filter(Employee.id == employee_id).first()
        if emp:
            resp.employee_name = f"{emp.first_name} {emp.last_name or ''}".strip()
            resp.employee_email = emp.email
            resp.employee_code = emp.employee_code
        if data.task_id and task:
            resp.task_title = task.title
        if project:
            resp.project_name = project.name
            resp.project_code = project.code
        return resp

    def list_time_entries(
        self,
        company_id: UUID,
        project_id: Optional[UUID] = None,
        employee_id: Optional[UUID] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[TimeEntryResponse]:
        results = self.repo.list_time_entries_with_details(company_id, project_id, employee_id, status, start_date, end_date)
        responses = []
        for entry, emp, task_title, proj_name, proj_code in results:
            resp = TimeEntryResponse.from_orm(entry)
            if emp:
                resp.employee_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                resp.employee_email = emp.email
                resp.employee_code = emp.employee_code
            if task_title:
                resp.task_title = task_title
            if proj_name:
                resp.project_name = proj_name
            if proj_code:
                resp.project_code = proj_code
            responses.append(resp)
        return responses

    def update_time_entry(self, company_id: UUID, entry_id: UUID, user_employee_id: Optional[UUID], data: TimeEntryUpdate) -> TimeEntryResponse:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        
        # Lock check: once submitted/pending or approved, employees cannot modify it. Only draft or rejected can be edited.
        if user_employee_id:
            if entry.employee_id != user_employee_id:
                raise ForbiddenError("You can only modify your own time entries.")
            if entry.status in ("approved", "submitted"):
                raise AppError(f"Cannot edit time entry in '{entry.status}' status. Only draft or rejected entries can be edited.")

        target_date = data.date if data.date is not None else entry.date
        if data.hours is not None:
            existing_entries = self.repo.list_time_entries(company_id, employee_id=entry.employee_id, start_date=target_date, end_date=target_date)
            daily_total = sum((e.hours for e in existing_entries if e.id != entry.id), Decimal("0.00"))
            if daily_total + data.hours > Decimal("14.00"):
                raise AppError(f"Total logged time across all projects cannot exceed 14 hours per day. (Currently logged: {daily_total} hrs, attempting: {data.hours} hrs)")

        updated = self.repo.update_time_entry(entry, data)
        return TimeEntryResponse.from_orm(updated)

    def approve_reject_time_entry(
        self, company_id: UUID, entry_id: UUID, status: str,
        approver_user_id: UUID, rejection_reason: str | None = None
    ) -> TimeEntryResponse:
        if status not in ("approved", "rejected"):
            raise AppError("Status must be either 'approved' or 'rejected'.")
        if status == "rejected" and not (rejection_reason and rejection_reason.strip()):
            raise AppError("A rejection reason is required when rejecting a time entry.")
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        updated = self.repo.approve_reject_time_entry(
            entry, status, approver_user_id, rejection_reason=rejection_reason.strip() if rejection_reason else None
        )
        return TimeEntryResponse.from_orm(updated)

    def delete_time_entry(self, company_id: UUID, entry_id: UUID, user_employee_id: Optional[UUID] = None) -> None:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        if user_employee_id:
            if entry.employee_id != user_employee_id:
                raise ForbiddenError("You can only delete your own time entries.")
            if entry.status in ("approved", "submitted"):
                raise AppError(f"Cannot delete time entry in '{entry.status}' status. Only draft or rejected entries can be deleted.")
        self.repo.delete_time_entry(entry)

    # --- Milestones ---
    def create_milestone(self, company_id: Optional[UUID], project_id: UUID, data: MilestoneCreate) -> MilestoneResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        milestone = self.repo.create_milestone(project.company_id, project_id, data)
        return MilestoneResponse.from_orm(milestone)

    def list_milestones(self, company_id: Optional[UUID], project_id: UUID) -> List[MilestoneResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        milestones = self.repo.list_milestones(project.company_id, project_id)
        return [MilestoneResponse.from_orm(m) for m in milestones]

    def update_milestone(self, company_id: Optional[UUID], milestone_id: UUID, data: MilestoneUpdate) -> MilestoneResponse:
        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")
        updated = self.repo.update_milestone(milestone, data)
        return MilestoneResponse.from_orm(updated)

    def delete_milestone(self, company_id: Optional[UUID], milestone_id: UUID) -> None:
        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")
        self.repo.delete_milestone(milestone)

    # --- Project Documents ---
    def add_document(self, company_id: Optional[UUID], project_id: UUID, data: ProjectDocumentCreate, uploaded_by: Optional[UUID] = None) -> ProjectDocumentResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        doc = self.repo.create_project_document(project.company_id, project_id, data, uploaded_by)
        resp = ProjectDocumentResponse.from_orm(doc)
        try:
            from app.modules.platform.service import FileService
            signed = FileService(self.repo.db).generate_signed_url(project.company_id, doc.file_id)
            resp.download_url = signed.url
        except Exception:
            resp.download_url = f"/api/v1/files/download/{doc.file_id}"
        return resp

    def list_documents(self, company_id: Optional[UUID], project_id: UUID) -> List[ProjectDocumentResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        results = self.repo.list_project_documents(project.company_id, project_id)
        responses = []
        from app.modules.platform.service import FileService
        file_service = FileService(self.repo.db)
        for doc, user_email in results:
            resp = ProjectDocumentResponse.from_orm(doc)
            resp.uploaded_by_name = user_email or "Team Member"
            try:
                signed = file_service.generate_signed_url(project.company_id, doc.file_id)
                resp.download_url = signed.url
            except Exception:
                resp.download_url = f"/api/v1/files/download/{doc.file_id}"
            responses.append(resp)
        return responses

    def delete_document(self, company_id: Optional[UUID], project_id: UUID, document_id: UUID) -> None:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        doc = self.repo.get_project_document(project.company_id, document_id)
        if not doc:
            raise NotFoundError("Document not found.")
        self.repo.delete_project_document(doc)

