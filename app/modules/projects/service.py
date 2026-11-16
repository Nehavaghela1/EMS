from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import EmployeeSalary
from app.modules.platform.service import AuditService, NotificationService
from app.modules.projects.models import Task
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import (
    MemberRateUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    PagedProjectResponse,
    ProjectCreate,
    ProjectDocumentCreate,
    ProjectDocumentResponse,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdate,
    TaskCommentCreate,
    TaskCommentResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    TimeEntryCreate,
    TimeEntryResponse,
    TimeEntryUpdate,
)


class ProjectService:
    def __init__(self, db: Session):
        self.repo = ProjectRepository(db)
        self.audit = AuditService(db)
        self.notifications = NotificationService(db)

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
    def create_project(
        self, company_id: UUID, data: ProjectCreate, actor: User | None = None
    ) -> ProjectResponse:
        from app.modules.hr.models import Employee
        from app.modules.projects.models import Project

        target_company_id = data.company_id or company_id
        # Rule 1: Plain employees get 403
        if actor and actor.role == UserRole.employee:
            raise ForbiddenError("Employees cannot create projects.")

        # Rule 3: Name is required and unique among company live projects
        live_statuses = ["active", "planning", "on_hold"]
        same_name = (
            self.repo.db.query(Project)
            .filter(
                Project.company_id == target_company_id,
                Project.name == data.name,
                Project.status.in_(live_statuses),
            )
            .first()
        )
        if same_name:
            raise ValidationError(f"A live project with name '{data.name}' already exists.")

        existing_code = self.repo.get_project_by_code(target_company_id, data.code)
        if existing_code:
            raise ConflictError(f"Project with code '{data.code}' already exists.")

        # Rule 3: project manager must be an active employee of the same company
        chosen_mgr_emp_id = data.manager_id
        if chosen_mgr_emp_id:
            emp = (
                self.repo.db.query(Employee)
                .filter(
                    Employee.id == chosen_mgr_emp_id,
                    Employee.company_id == target_company_id,
                    Employee.is_active.is_(True),
                )
                .first()
            )
            if not emp:
                raise ValidationError(
                    "Project manager must be an active employee of the same company."
                )
        elif actor and actor.role == UserRole.manager:
            # The creator becomes the project manager
            actor_emp = (
                self.repo.db.query(Employee)
                .filter(
                    Employee.user_id == actor.id,
                    Employee.company_id == target_company_id,
                    Employee.is_active.is_(True),
                )
                .first()
            )
            if actor_emp:
                chosen_mgr_emp_id = actor_emp.id

        project_dict = data.dict(exclude={"company_id"})
        project_dict["manager_id"] = chosen_mgr_emp_id
        project = self.repo.create_project(target_company_id, ProjectCreate(**project_dict))

        # Rule 1: Creator or manager becomes PM and is added with role manager
        if chosen_mgr_emp_id:
            existing_mem = self.repo.get_member(target_company_id, project.id, chosen_mgr_emp_id)
            if not existing_mem:
                self.repo.add_member(
                    target_company_id,
                    project.id,
                    ProjectMemberCreate(
                        employee_id=chosen_mgr_emp_id, role="manager", hourly_rate=None
                    ),
                )

        # Rule 7: Every create is audited (ids and field names only)
        self.audit.record(
            company_id=target_company_id,
            actor=actor,
            action="create",
            entity_type="project",
            entity_id=project.id,
            details={"fields": ["name", "code", "status", "budget", "manager_id"]},
        )
        return self._to_project_response(project)

    def get_project(
        self, company_id: UUID | None, project_id: UUID, actor: User | None = None
    ) -> ProjectResponse:
        from app.modules.hr.models import Employee

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Rule 2: members and project manager read; HR and owner read all; non-member gets 404
        if actor and actor.role not in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            actor_emp = (
                self.repo.db.query(Employee)
                .filter(Employee.user_id == actor.id, Employee.company_id == project.company_id)
                .first()
            )
            is_member = False
            if actor_emp:
                mem = self.repo.get_member(project.company_id, project_id, actor_emp.id)
                if mem:
                    is_member = True
            if not is_member and project.manager_id != (actor_emp.id if actor_emp else None):
                raise NotFoundError("Project not found.")

        return self._to_project_response(project)

    def list_projects(
        self,
        company_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
        actor: User | None = None,
    ) -> PagedProjectResponse:
        from app.modules.hr.models import Employee
        from app.modules.projects.models import Project, ProjectMember

        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)

        query = self.repo.db.query(Project)
        if company_id is not None:
            query = query.filter(Project.company_id == company_id)
        if status:
            query = query.filter(Project.status == status)

        # Scoping: Plain employees / non-HR see only projects where they are member or manager
        if actor and actor.role not in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            actor_emp = (
                self.repo.db.query(Employee)
                .filter(Employee.user_id == actor.id, Employee.company_id == company_id)
                .first()
            )
            if not actor_emp:
                return PagedProjectResponse(items=[], total=0, page=page, page_size=page_size)
            member_proj_ids = [
                row[0]
                for row in self.repo.db.query(ProjectMember.project_id)
                .filter(
                    ProjectMember.company_id == company_id,
                    ProjectMember.employee_id == actor_emp.id,
                )
                .all()
            ]
            query = query.filter(
                (Project.manager_id == actor_emp.id) | (Project.id.in_(member_proj_ids))
            )

        total = query.count()
        projects = (
            query.order_by(Project.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return PagedProjectResponse(
            items=[self._to_project_response(p) for p in projects],
            total=total,
            page=page,
            page_size=page_size,
        )

    def update_project(
        self,
        company_id: UUID | None,
        project_id: UUID,
        data: ProjectUpdate,
        actor: User | None = None,
    ) -> ProjectResponse:
        from app.modules.hr.models import Employee
        from app.modules.projects.models import Milestone, Task

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Rule 2: Project manager, HR and owner edit; plain members get 403
        is_pm = False
        actor_emp_id = None
        if actor:
            actor_emp = (
                self.repo.db.query(Employee)
                .filter(Employee.user_id == actor.id, Employee.company_id == project.company_id)
                .first()
            )
            if actor_emp:
                actor_emp_id = actor_emp.id
                if project.manager_id == actor_emp_id:
                    is_pm = True
                else:
                    mem = self.repo.get_member(project.company_id, project_id, actor_emp_id)
                    if mem and mem.role == "manager":
                        is_pm = True

        can_edit = (
            actor is None
            or actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
            or is_pm
        )
        if not can_edit:
            raise ForbiddenError("Only project manager, HR and owner can edit the project.")

        # Rule 4: An archived project is read-only; only HR and owner can unarchive
        if project.status == "archived":
            if data.status and data.status != "archived":
                if actor and actor.role not in (
                    UserRole.hr_admin,
                    UserRole.owner,
                    UserRole.super_admin,
                ):
                    raise ForbiddenError("Only HR and owner can unarchive a project.")
            else:
                raise ConflictError("Archived project is read-only.")

        # Rule 10: Project dates cannot exclude existing milestones or tasks
        new_start = data.start_date if data.start_date is not None else project.start_date
        new_end = (
            data.end_date
            if data.end_date is not None
            else (
                data.deadline
                if data.deadline is not None
                else (project.end_date or project.deadline)
            )
        )

        if new_start or new_end:
            if new_start:
                ms_before = (
                    self.repo.db.query(Milestone)
                    .filter(Milestone.project_id == project.id, Milestone.due_date < new_start)
                    .first()
                )
                task_before = (
                    self.repo.db.query(Task)
                    .filter(Task.project_id == project.id, Task.due_date < new_start)
                    .first()
                )
                if ms_before or task_before:
                    raise ConflictError(
                        "New project start date excludes existing milestones or tasks."
                    )
            if new_end:
                ms_after = (
                    self.repo.db.query(Milestone)
                    .filter(Milestone.project_id == project.id, Milestone.due_date > new_end)
                    .first()
                )
                task_after = (
                    self.repo.db.query(Task)
                    .filter(Task.project_id == project.id, Task.due_date > new_end)
                    .first()
                )
                if ms_after or task_after:
                    raise ConflictError(
                        "New project end date excludes existing milestones or tasks."
                    )

        if data.code and data.code != project.code:
            existing = self.repo.get_project_by_code(project.company_id, data.code)
            if existing:
                raise ConflictError(f"Project with code '{data.code}' already exists.")

        updated_fields = list(data.dict(exclude_unset=True).keys())
        updated = self.repo.update_project(project, data)

        # Rule 7: Audited
        self.audit.record(
            company_id=project.company_id,
            actor=actor,
            action="status_change" if "status" in updated_fields else "edit",
            entity_type="project",
            entity_id=project.id,
            details={"fields": updated_fields},
        )
        return self._to_project_response(updated)

    def delete_project(
        self, company_id: UUID | None, project_id: UUID, actor: User | None = None
    ) -> None:
        from app.modules.projects.models import TimeEntry

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Rule 5: A project that has time entries can never be deleted
        has_time_entries = (
            self.repo.db.query(TimeEntry).filter(TimeEntry.project_id == project.id).first()
        )
        if has_time_entries:
            raise ConflictError("A project with time entries can never be deleted.")

        self.audit.record(
            company_id=project.company_id,
            actor=actor,
            action="delete",
            entity_type="project",
            entity_id=project.id,
            details={"fields": ["id", "code"]},
        )
        self.repo.delete_project(project)

    # --- Project Summary Analytics ---
    def get_project_summary(
        self, company_id: UUID | None, project_id: UUID
    ) -> ProjectSummaryResponse:
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
        overdue_tasks = sum(
            1 for t in tasks if t.due_date and t.due_date < today and t.status != "done"
        )

        completion_pct = Decimal("0.00")
        if total_tasks > 0:
            completion_pct = (
                Decimal(completed_tasks) / Decimal(total_tasks) * Decimal("100.00")
            ).quantize(Decimal("0.01"))

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
                    EmployeeSalary.deleted_at.is_(None),
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
                        emp_rates[s.employee_id] = (
                            s.ctc / Decimal("12") / Decimal("160.00")
                        ).quantize(Decimal("0.01"))

            for e in approved_billable_entries:
                rate = emp_rates.get(
                    e.employee_id, Decimal("500.00")
                )  # Default fallback rate ₹500/hr
                budget_spent += Decimal(str(e.hours)) * rate
            budget_spent = budget_spent.quantize(Decimal("0.01"))

        budget_remaining = None
        if project.budget is not None:
            budget_remaining = (project.budget - budget_spent).quantize(Decimal("0.01"))

        # Delivery Health progression:
        # Not Started -> In Progress -> On Schedule (or Needs Attention)
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
            approved_logged_hours=approved_logged_hours,
        )

    # --- Project Members ---
    def add_member(
        self,
        company_id: UUID | None,
        project_id: UUID,
        data: ProjectMemberCreate,
        actor: User | None = None,
    ) -> ProjectMemberResponse:
        from app.modules.hr.models import Department, Employee

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        p_cid = project.company_id

        # Rule 1: A member must be an active employee of the same company
        target_emp = (
            self.repo.db.query(Employee)
            .filter(
                Employee.id == data.employee_id,
                Employee.company_id == p_cid,
                Employee.is_active.is_(True),
            )
            .first()
        )
        if not target_emp:
            raise ValidationError("Member must be an active employee of the same company.")

        # Rule 1: Duplicate returns 409
        existing = self.repo.get_member(p_cid, project_id, data.employee_id)
        if existing:
            raise ConflictError("Employee is already a member of this project.")

        # Map role 'lead' to 'manager'
        assigned_role = data.role
        data_to_save = data.copy(update={"role": assigned_role})

        member = self.repo.add_member(p_cid, project_id, data_to_save)

        # Rule 4: If hourly billing rate is provided, save to effective-dated rate history
        if data.hourly_rate is not None and data.hourly_rate >= 0:
            eff_from = data.effective_from or date.today()
            self.repo.add_member_rate(
                company_id=p_cid,
                project_id=project_id,
                employee_id=data.employee_id,
                rate=data.hourly_rate,
                effective_from=eff_from,
            )

        # Rule 6: The added member is notified after the commit
        if target_emp.user_id:
            self.notifications.notify(
                company_id=p_cid,
                user_id=target_emp.user_id,
                type="project_member_added",
                title="Added to Project",
                message=f"You have been added to project {project.name}.",
                entity_type="project",
                entity_id=project.id,
            )

        # Rule 8: Audit
        self.audit.record(
            company_id=p_cid,
            actor=actor,
            action="add_member",
            entity_type="project_member",
            entity_id=member.id,
            details={"fields": ["employee_id", "role"]},
        )

        resp = ProjectMemberResponse.from_orm(member)
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

        # Mask rate if caller is not PM / HR / owner
        if not self._can_view_rates(project, actor):
            resp.hourly_rate = None

        return resp

    def _can_view_rates(self, project, actor: User | None) -> bool:
        from app.modules.hr.models import Employee

        if not actor:
            return True
        if actor.role in (UserRole.hr_admin, UserRole.owner):
            return True
        # Check if actor is project manager
        actor_emp = (
            self.repo.db.query(Employee)
            .filter(Employee.user_id == actor.id, Employee.company_id == project.company_id)
            .first()
        )
        if actor_emp:
            if project.manager_id == actor_emp.id:
                return True
            mem = self.repo.get_member(project.company_id, project.id, actor_emp.id)
            if mem and mem.role == "manager":
                return True
        return False

    def list_members(
        self, company_id: UUID | None, project_id: UUID, actor: User | None = None
    ) -> list[ProjectMemberResponse]:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        can_see_rates = self._can_view_rates(project, actor)
        results = self.repo.list_members_with_details(project.company_id, project_id)
        responses = []
        for m, emp, dept_name in results:
            resp = ProjectMemberResponse.from_orm(m)
            if not can_see_rates:
                resp.hourly_rate = None
            if emp:
                resp.employee_name = f"{emp.first_name} {emp.last_name or ''}".strip()
                resp.employee_email = emp.email
                resp.employee_code = emp.employee_code
                resp.designation = emp.position or "Staff"
                resp.department_name = dept_name or "General"
            responses.append(resp)
        return responses

    def update_member_rate(
        self,
        company_id: UUID | None,
        project_id: UUID,
        employee_id: UUID,
        data: MemberRateUpdate,
        actor: User | None = None,
    ) -> ProjectMemberResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Rule 4: Only HR and owner set or change a rate; PM gets 403
        if actor and actor.role not in (UserRole.hr_admin, UserRole.owner):
            raise ForbiddenError("Only HR and owner can set or change member billing rates.")

        member = self.repo.get_member(project.company_id, project_id, employee_id)
        if not member:
            raise NotFoundError("Project member not found.")

        member.hourly_rate = data.hourly_rate
        self.repo.db.commit()

        # Save to effective-dated rate history
        self.repo.add_member_rate(
            company_id=project.company_id,
            project_id=project_id,
            employee_id=employee_id,
            rate=data.hourly_rate,
            effective_from=data.effective_from,
        )

        # Rule 8: Rate changes are audited with field names only (no amounts)
        self.audit.record(
            company_id=project.company_id,
            actor=actor,
            action="rate_change",
            entity_type="project_member",
            entity_id=member.id,
            details={"fields": ["hourly_rate", "effective_from"]},
        )

        resp = ProjectMemberResponse.from_orm(member)
        if not self._can_view_rates(project, actor):
            resp.hourly_rate = None
        return resp

    def remove_member(
        self,
        company_id: UUID | None,
        project_id: UUID,
        employee_id: UUID,
        actor: User | None = None,
    ) -> None:
        from app.modules.projects.models import ProjectMember, Task

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        member = self.repo.get_member(project.company_id, project_id, employee_id)
        if not member:
            raise NotFoundError("Project member not found.")

        # Rule 2: A project always keeps at least one manager (removing last returns 409)
        if member.role == "manager" or (project.manager_id and project.manager_id == employee_id):
            managers_count = (
                self.repo.db.query(ProjectMember)
                .filter(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role == "manager",
                    ProjectMember.employee_id != employee_id,
                )
                .count()
            )
            if managers_count == 0:
                raise ConflictError("Cannot remove the last project manager.")

        # Rule 5: Open tasks become unassigned (assigned_to = None)
        open_tasks = (
            self.repo.db.query(Task)
            .filter(
                Task.project_id == project_id,
                Task.assigned_to == employee_id,
                Task.status.notin_(["done", "cancelled"]),
            )
            .all()
        )
        for t in open_tasks:
            t.assigned_to = None
        self.repo.db.flush()

        self.repo.remove_member(member)

        # Audit
        self.audit.record(
            company_id=project.company_id,
            actor=actor,
            action="remove_member",
            entity_type="project_member",
            entity_id=member.id,
            details={"fields": ["employee_id"]},
        )

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

    def create_task(
        self,
        company_id: UUID | None,
        project_id: UUID,
        actor_user: User,
        data: TaskCreate,
    ) -> TaskResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Check membership / authority (Rule 1)
        # Owner & HR can create in any project. Project members & PM can create.
        if actor_user.role not in (UserRole.owner, UserRole.hr_admin):
            from app.modules.hr.repository import EmployeeRepository

            emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
            if not emp:
                raise NotFoundError("Project not found.")
            member = self.repo.get_member(company_id, project_id, emp.id)
            if not member and project.manager_id != emp.id:
                raise NotFoundError("Project not found.")

        # Check project status (Rule 7)
        if project.status in ("on_hold", "completed", "archived"):
            raise ConflictError(f"Cannot create tasks in a project with status '{project.status}'.")

        # Validation (Rule 2)
        if not data.title or not data.title.strip():
            raise ValidationError("Task title cannot be blank.")
        if len(data.title.strip()) > 255:
            raise ValidationError("Task title exceeds maximum length of 255 characters.")

        # Due date check against project dates
        if data.due_date:
            if project.start_date and data.due_date < project.start_date:
                raise ValidationError("Task due date cannot precede project start date.")
            if project.end_date and data.due_date > project.end_date:
                raise ValidationError("Task due date cannot exceed project end date.")

        # Assignee validation (Rule 2 & 6)
        if data.assigned_to:
            assignee_member = self.repo.get_member(company_id, project_id, data.assigned_to)
            if not assignee_member and project.manager_id != data.assigned_to:
                raise ValidationError("Task assignee must be an active project member.")

        task = self.repo.create_task(project.company_id, project_id, actor_user.id, data)

        # Audit (Rule 9)
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="create_task",
            entity_type="task",
            entity_id=task.id,
            details={"fields": ["title", "priority", "status", "assigned_to", "due_date"]},
        )

        return self._enrich_task_response(task)

    def get_task(self, company_id: UUID | None, task_id: UUID, actor_user: User) -> TaskResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")

        # Check project membership scoping
        if actor_user.role not in (UserRole.owner, UserRole.hr_admin):
            from app.modules.hr.repository import EmployeeRepository

            emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
            if not emp:
                raise NotFoundError("Task not found.")
            project = self.repo.get_project_by_id(company_id, task.project_id)
            if not project:
                raise NotFoundError("Task not found.")
            member = self.repo.get_member(company_id, task.project_id, emp.id)
            if not member and project.manager_id != emp.id:
                raise NotFoundError("Task not found.")

        return self._enrich_task_response(task)

    def list_tasks(
        self,
        company_id: UUID | None,
        project_id: UUID,
        actor_user: User,
        status: str | None = None,
        assigned_to: UUID | None = None,
    ) -> list[TaskResponse]:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Scoping check
        if actor_user.role not in (UserRole.owner, UserRole.hr_admin):
            from app.modules.hr.repository import EmployeeRepository

            emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
            if not emp:
                raise NotFoundError("Project not found.")
            member = self.repo.get_member(company_id, project_id, emp.id)
            if not member and project.manager_id != emp.id:
                raise NotFoundError("Project not found.")

        results = self.repo.list_tasks_with_details(
            project.company_id, project_id, status, assigned_to
        )
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
        company_id: UUID | None,
        task_id: UUID,
        actor_user: User,
        data: TaskUpdate,
    ) -> TaskResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")

        project = self.repo.get_project_by_id(company_id, task.project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Determine user roles on the project
        is_hr_or_owner = actor_user.role in (UserRole.owner, UserRole.hr_admin)
        is_pm = False
        is_member = False
        caller_emp_id = None

        from app.modules.hr.repository import EmployeeRepository

        emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
        if emp:
            caller_emp_id = emp.id
            if project.manager_id == emp.id:
                is_pm = True
            mem = self.repo.get_member(company_id, project.id, emp.id)
            if mem:
                is_member = True
                if mem.role in ("lead", "manager"):
                    is_pm = True

        if not is_hr_or_owner and not is_pm and not is_member:
            raise NotFoundError("Task not found.")

        # In task edits, regular members (neither PM nor HR/Owner nor task assignee)
        # cannot edit tasks assigned to other teammates.
        if (
            not (is_pm or is_hr_or_owner)
            and task.assigned_to is not None
            and caller_emp_id != task.assigned_to
        ):
            raise ForbiddenError(
                "Only the task assignee or Project Lead/Manager can update this task."
            )

        # Cancelled is always allowed by PM, HR, owner
        is_cancelling = data.status == "cancelled"

        # Parent project status check (Rule 7)
        if project.status in ("on_hold", "completed", "archived"):
            if not (is_cancelling and (is_pm or is_hr_or_owner)):
                raise ConflictError(
                    f"Cannot edit tasks in a project with status '{project.status}'."
                )

        update_dict = data.dict(exclude_unset=True)

        # Validation
        if "title" in update_dict:
            if not update_dict["title"] or not str(update_dict["title"]).strip():
                raise ValidationError("Task title cannot be blank.")
            if len(str(update_dict["title"]).strip()) > 255:
                raise ValidationError("Task title exceeds maximum length of 255 characters.")

        if "due_date" in update_dict and update_dict["due_date"]:
            due_d = update_dict["due_date"]
            if project.start_date and due_d < project.start_date:
                raise ValidationError("Task due date cannot precede project start date.")
            if project.end_date and due_d > project.end_date:
                raise ValidationError("Task due date cannot exceed project end date.")

        if "assigned_to" in update_dict and update_dict["assigned_to"]:
            assignee_member = self.repo.get_member(
                company_id, project.id, update_dict["assigned_to"]
            )
            if not assignee_member and project.manager_id != update_dict["assigned_to"]:
                raise ValidationError("Task assignee must be an active project member.")

        # Rule 4: A done task changes only when the project manager reopens it.
        # Only PM, HR, owner can reopen or edit a done task
        if task.status == "done":
            if not (is_pm or is_hr_or_owner):
                raise ConflictError("A done task can only be reopened by the project manager.")

        # Rule 3: Status transition logic
        if "status" in update_dict and update_dict["status"] != task.status:
            new_status = update_dict["status"]
            old_status = task.status
            flow = ["todo", "in_progress", "review", "done"]

            if new_status == "cancelled":
                # Cancelling is allowed by PM, HR, owner
                if not (is_pm or is_hr_or_owner):
                    raise ForbiddenError("Only the project manager or HR can cancel tasks.")
            elif old_status == "done":
                # Reopening: PM/HR/Owner moving back to in_progress or todo
                if new_status not in ("in_progress", "todo"):
                    raise ConflictError(f"Cannot transition done task to {new_status}.")
            elif old_status in flow and new_status in flow:
                old_idx = flow.index(old_status)
                new_idx = flow.index(new_status)
                # Allowed: one step forward or backward
                if new_idx == old_idx + 1 or new_idx == old_idx - 1:
                    pass
                else:
                    raise ConflictError(
                        f"Invalid status transition from '{old_status}' to '{new_status}'. "
                        "Skipping steps is not allowed."
                    )
            elif old_status == "cancelled":
                if not (is_pm or is_hr_or_owner):
                    raise ForbiddenError("Only project manager or HR can reopen cancelled tasks.")

        updated = self.repo.update_task(task, data)

        # Audit (Rule 9)
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="update_task",
            entity_type="task",
            entity_id=task.id,
            details={"fields": list(update_dict.keys())},
        )

        return self._enrich_task_response(updated)

    def reorder_task(
        self,
        company_id: UUID | None,
        task_id: UUID,
        actor_user: User,
        position: int,
    ) -> TaskResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")

        project = self.repo.get_project_by_id(company_id, task.project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Check permissions
        if actor_user.role not in (UserRole.owner, UserRole.hr_admin):
            from app.modules.hr.repository import EmployeeRepository

            emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
            if not emp:
                raise NotFoundError("Task not found.")
            member = self.repo.get_member(company_id, project.id, emp.id)
            if not member and project.manager_id != emp.id:
                raise NotFoundError("Task not found.")

        task.position = position
        task.updated_at = datetime.utcnow()
        self.repo.db.commit()
        self.repo.db.refresh(task)

        # Audit
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="reorder_task",
            entity_type="task",
            entity_id=task.id,
            details={"fields": ["position"]},
        )

        return self._enrich_task_response(task)

    def delete_task(self, company_id: UUID | None, task_id: UUID, actor_user: User) -> None:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project tasks.")

        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")

        project = self.repo.get_project_by_id(company_id, task.project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Rule 5: Only creator, PM, HR and owner delete a task; others get 403
        is_creator = task.created_by == actor_user.id
        is_hr_or_owner = actor_user.role in (UserRole.owner, UserRole.hr_admin)
        is_pm = False

        from app.modules.hr.repository import EmployeeRepository

        emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
        if emp:
            if project.manager_id == emp.id:
                is_pm = True
            mem = self.repo.get_member(company_id, project.id, emp.id)
            if mem and mem.role in ("lead", "manager"):
                is_pm = True

        if not (is_creator or is_pm or is_hr_or_owner):
            raise ForbiddenError(
                "Only task creator, project manager, HR or owner can delete tasks."
            )

        self.repo.delete_task(task)

        # Audit
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="delete_task",
            entity_type="task",
            entity_id=task.id,
            details={"fields": ["id"]},
        )

    # --- Task Comments ---
    def add_comment(
        self, company_id: UUID, task_id: UUID, user_id: UUID, data: TaskCommentCreate
    ) -> TaskCommentResponse:
        task = self.repo.get_task_by_id(company_id, task_id)
        if not task:
            raise NotFoundError("Task not found.")
        comment = self.repo.add_comment(company_id, task_id, user_id, data.comment)
        return TaskCommentResponse.from_orm(comment)

    def list_comments(self, company_id: UUID, task_id: UUID) -> list[TaskCommentResponse]:
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
        is_admin_or_manager: bool = False,
    ) -> TimeEntryResponse:
        project = self.repo.get_project_by_id(company_id, data.project_id)
        if not project:
            raise NotFoundError("Project not found.")
        if data.task_id:
            task = self.repo.get_task_by_id(company_id, data.task_id)
            if not task:
                raise NotFoundError("Task not found.")
            # Server-side validation:
            # Regular employees can only log time against their own assigned tasks
            if not is_admin_or_manager:
                # Check if employee is Project Lead
                is_lead = False
                member = self.repo.get_member(company_id, data.project_id, employee_id)
                if member and member.role in ("lead", "manager"):
                    is_lead = True

                if task.assigned_to and task.assigned_to != employee_id and not is_lead:
                    assignee_name = (
                        task.assigned_to_name
                        if hasattr(task, "assigned_to_name")
                        else "another teammate"
                    )
                    raise ForbiddenError(
                        f"You cannot log time against a task assigned to {assignee_name}. "
                        "Employees can only log hours on their own assigned tasks."
                    )

        # Check total daily logged hours ceiling (max 14 hrs per day across all tasks combined)
        existing_entries = self.repo.list_time_entries(
            company_id, employee_id=employee_id, start_date=data.date, end_date=data.date
        )
        daily_total = sum((e.hours for e in existing_entries), Decimal("0.00"))
        if daily_total + data.hours > Decimal("14.00"):
            raise AppError(
                "Total logged time across all projects cannot exceed 14 hours per day. "
                f"(Currently logged: {daily_total} hrs, attempting: {data.hours} hrs)"
            )

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
        project_id: UUID | None = None,
        employee_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TimeEntryResponse]:
        results = self.repo.list_time_entries_with_details(
            company_id, project_id, employee_id, status, start_date, end_date
        )
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

    def update_time_entry(
        self, company_id: UUID, entry_id: UUID, user_employee_id: UUID | None, data: TimeEntryUpdate
    ) -> TimeEntryResponse:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")

        # Lock check: once submitted/pending or approved, employees cannot modify it.
        # Only draft or rejected can be edited.
        if user_employee_id:
            if entry.employee_id != user_employee_id:
                raise ForbiddenError("You can only modify your own time entries.")
            if entry.status in ("approved", "submitted"):
                raise AppError(
                    f"Cannot edit time entry in '{entry.status}' status. "
                    "Only draft or rejected entries can be edited."
                )

        target_date = data.date if data.date is not None else entry.date
        if data.hours is not None:
            existing_entries = self.repo.list_time_entries(
                company_id,
                employee_id=entry.employee_id,
                start_date=target_date,
                end_date=target_date,
            )
            daily_total = sum(
                (e.hours for e in existing_entries if e.id != entry.id), Decimal("0.00")
            )
            if daily_total + data.hours > Decimal("14.00"):
                raise AppError(
                    "Total logged time across all projects cannot exceed 14 hours per day. "
                    f"(Currently logged: {daily_total} hrs, attempting: {data.hours} hrs)"
                )

        updated = self.repo.update_time_entry(entry, data)
        return TimeEntryResponse.from_orm(updated)

    def approve_reject_time_entry(
        self,
        company_id: UUID,
        entry_id: UUID,
        status: str,
        approver_user_id: UUID,
        actor: User,
        rejection_reason: str | None = None,
    ) -> TimeEntryResponse:
        if status not in ("approved", "rejected"):
            raise AppError("Status must be either 'approved' or 'rejected'.")
        if status == "rejected" and not (rejection_reason and rejection_reason.strip()):
            raise AppError("A rejection reason is required when rejecting a time entry.")
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")

        from app.core.approval_authority import can_approve_for
        from app.modules.hr.models import Employee

        target_emp = self.repo.db.get(Employee, entry.employee_id)
        if not target_emp or not can_approve_for(self.repo.db, actor, target_emp):
            raise ForbiddenError("Not authorized to approve this request.")

        if entry.status in ("approved", "rejected"):
            raise ConflictError(f"Time entry is already {entry.status}.")

        if status == "approved" and entry.is_overtime:
            # Calculate overtime amount
            salary = (
                self.repo.db.query(EmployeeSalary)
                .filter(
                    EmployeeSalary.employee_id == entry.employee_id,
                    EmployeeSalary.company_id == company_id,
                    EmployeeSalary.deleted_at.is_(None),
                )
                .order_by(EmployeeSalary.effective_from.desc())
                .first()
            )

            if salary and salary.hourly_rate:
                multiplier = entry.overtime_multiplier or Decimal("1.00")
                entry.overtime_amount = entry.hours * salary.hourly_rate * multiplier

        updated = self.repo.approve_reject_time_entry(
            entry,
            status,
            approver_user_id,
            rejection_reason=rejection_reason.strip() if rejection_reason else None,
        )
        return TimeEntryResponse.from_orm(updated)

    def delete_time_entry(
        self, company_id: UUID, entry_id: UUID, user_employee_id: UUID | None = None
    ) -> None:
        entry = self.repo.get_time_entry_by_id(company_id, entry_id)
        if not entry:
            raise NotFoundError("Time entry not found.")
        if user_employee_id:
            if entry.employee_id != user_employee_id:
                raise ForbiddenError("You can only delete your own time entries.")
            if entry.status in ("approved", "submitted"):
                raise AppError(
                    f"Cannot delete time entry in '{entry.status}' status. "
                    "Only draft or rejected entries can be deleted."
                )
        self.repo.delete_time_entry(entry)

    # --- Milestones ---
    def create_milestone(
        self,
        company_id: UUID | None,
        project_id: UUID,
        actor_user: User,
        data: MilestoneCreate,
    ) -> MilestoneResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project milestones.")

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Permissions: PM, HR and Owner create (Rule 1)
        is_hr_or_owner = actor_user.role in (UserRole.owner, UserRole.hr_admin)
        is_pm = False

        from app.modules.hr.repository import EmployeeRepository

        emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
        if emp:
            if project.manager_id == emp.id:
                is_pm = True
            mem = self.repo.get_member(company_id, project_id, emp.id)
            if mem and mem.role in ("lead", "manager"):
                is_pm = True

        if not (is_pm or is_hr_or_owner):
            raise ForbiddenError("Only project manager, HR, or owner can create milestones.")

        # Validation (Rule 2)
        if not data.title or not data.title.strip():
            raise ValidationError("Milestone title cannot be blank.")
        if len(data.title.strip()) > 255:
            raise ValidationError("Milestone title exceeds maximum length of 255 characters.")

        if data.due_date:
            if project.start_date and data.due_date < project.start_date:
                raise ValidationError("Milestone due date cannot precede project start date.")
            if project.end_date and data.due_date > project.end_date:
                raise ValidationError("Milestone due date cannot exceed project end date.")

        milestone = self.repo.create_milestone(project.company_id, project_id, data)

        # Audit (Rule 6)
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="create_milestone",
            entity_type="milestone",
            entity_id=milestone.id,
            details={"fields": ["title", "due_date", "status"]},
        )

        return MilestoneResponse.from_orm(milestone)

    def list_milestones(
        self, company_id: UUID | None, project_id: UUID, actor_user: User
    ) -> list[MilestoneResponse]:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project milestones.")

        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")

        # Scoping: Plain employee must be a project member or PM, HR/owner can read all
        if actor_user.role not in (UserRole.owner, UserRole.hr_admin):
            from app.modules.hr.repository import EmployeeRepository

            emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
            if not emp:
                raise NotFoundError("Project not found.")
            member = self.repo.get_member(company_id, project_id, emp.id)
            if not member and project.manager_id != emp.id:
                raise NotFoundError("Project not found.")

        milestones = self.repo.list_milestones(project.company_id, project_id)
        return [MilestoneResponse.from_orm(m) for m in milestones]

    def update_milestone(
        self,
        company_id: UUID | None,
        milestone_id: UUID,
        actor_user: User,
        data: MilestoneUpdate,
    ) -> MilestoneResponse:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project milestones.")

        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")

        project = self.repo.get_project_by_id(company_id, milestone.project_id)
        if not project:
            raise NotFoundError("Milestone not found.")

        # Permissions: PM, HR, owner can edit (Rule 1)
        # Non-members get 404 (Rule 1)
        is_hr_or_owner = actor_user.role in (UserRole.owner, UserRole.hr_admin)
        is_pm = False
        is_member = False

        from app.modules.hr.repository import EmployeeRepository

        emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
        if emp:
            if project.manager_id == emp.id:
                is_pm = True
            mem = self.repo.get_member(company_id, project.id, emp.id)
            if mem:
                is_member = True
                if mem.role in ("lead", "manager"):
                    is_pm = True

        if not is_hr_or_owner and not is_pm and not is_member:
            raise NotFoundError("Milestone not found.")

        if not (is_pm or is_hr_or_owner):
            raise ForbiddenError("Only project manager, HR, or owner can edit milestones.")

        update_dict = data.dict(exclude_unset=True)

        if "title" in update_dict:
            if not update_dict["title"] or not str(update_dict["title"]).strip():
                raise ValidationError("Milestone title cannot be blank.")
            if len(str(update_dict["title"]).strip()) > 255:
                raise ValidationError("Milestone title exceeds maximum length of 255 characters.")

        if "due_date" in update_dict and update_dict["due_date"]:
            due_d = update_dict["due_date"]
            if project.start_date and due_d < project.start_date:
                raise ValidationError("Milestone due date cannot precede project start date.")
            if project.end_date and due_d > project.end_date:
                raise ValidationError("Milestone due date cannot exceed project end date.")

        # Rule 3: A milestone completes only when all associated tasks are done.
        # Completing with open tasks returns 409; milestone with only cancelled tasks can complete.
        if update_dict.get("status") == "completed" or update_dict.get(
            "completion_percentage"
        ) == Decimal("100.00"):
            tasks = (
                self.repo.db.query(Task)
                .filter(Task.milestone_id == milestone.id, Task.company_id == project.company_id)
                .all()
            )
            open_tasks = [t for t in tasks if t.status not in ("done", "cancelled")]
            if open_tasks:
                raise ConflictError("Cannot complete milestone while it has open tasks.")

        updated = self.repo.update_milestone(milestone, data)

        # Audit (Rule 6)
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="update_milestone",
            entity_type="milestone",
            entity_id=milestone.id,
            details={"fields": list(update_dict.keys())},
        )

        return MilestoneResponse.from_orm(updated)

    def delete_milestone(
        self, company_id: UUID | None, milestone_id: UUID, actor_user: User
    ) -> None:
        if actor_user.role == UserRole.super_admin or company_id is None:
            raise ForbiddenError("Super Admin cannot access tenant project milestones.")

        milestone = self.repo.get_milestone_by_id(company_id, milestone_id)
        if not milestone:
            raise NotFoundError("Milestone not found.")

        project = self.repo.get_project_by_id(company_id, milestone.project_id)
        if not project:
            raise NotFoundError("Milestone not found.")

        # Permissions: PM, HR, owner can delete (Rule 1)
        # Non-members get 404 (Rule 1)
        is_hr_or_owner = actor_user.role in (UserRole.owner, UserRole.hr_admin)
        is_pm = False
        is_member = False

        from app.modules.hr.repository import EmployeeRepository

        emp = EmployeeRepository(self.repo.db).get_by_user_id(company_id, actor_user.id)
        if emp:
            if project.manager_id == emp.id:
                is_pm = True
            mem = self.repo.get_member(company_id, project.id, emp.id)
            if mem:
                is_member = True
                if mem.role in ("lead", "manager"):
                    is_pm = True

        if not is_hr_or_owner and not is_pm and not is_member:
            raise NotFoundError("Milestone not found.")

        if not (is_pm or is_hr_or_owner):
            raise ForbiddenError("Only project manager, HR, or owner can delete milestones.")

        self.repo.delete_milestone(milestone)

        # Audit (Rule 6)
        self.audit.record(
            company_id=project.company_id,
            actor=actor_user,
            action="delete_milestone",
            entity_type="milestone",
            entity_id=milestone.id,
            details={"fields": ["id"]},
        )

    # --- Project Documents ---
    def add_document(
        self,
        company_id: UUID | None,
        project_id: UUID,
        data: ProjectDocumentCreate,
        uploaded_by: UUID | None = None,
    ) -> ProjectDocumentResponse:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        doc = self.repo.create_project_document(project.company_id, project_id, data, uploaded_by)
        resp = ProjectDocumentResponse.from_orm(doc)
        from app.modules.platform.service import FileService

        resp.download_url = FileService(self.repo.db).build_signed_url(
            project.company_id, doc.file_id
        )
        return resp

    def list_documents(
        self, company_id: UUID | None, project_id: UUID
    ) -> list[ProjectDocumentResponse]:
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
            resp.download_url = file_service.build_signed_url(project.company_id, doc.file_id)
            responses.append(resp)
        return responses

    def delete_document(self, company_id: UUID | None, project_id: UUID, document_id: UUID) -> None:
        project = self.repo.get_project_by_id(company_id, project_id)
        if not project:
            raise NotFoundError("Project not found.")
        doc = self.repo.get_project_document(project.company_id, document_id)
        if not doc:
            raise NotFoundError("Document not found.")
        self.repo.delete_project_document(doc)
