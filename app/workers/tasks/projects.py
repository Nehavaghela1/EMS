import logging
from decimal import Decimal
from uuid import UUID

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.platform.service import NotificationService
from app.modules.projects.models import Project
from app.modules.projects.service import ProjectService
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


def get_task_db_session():
    """Session factory for tasks. Overridable by tests."""
    return SessionLocal()


@celery_app.task(name="app.workers.tasks.projects.check_project_budget_alerts_task")
def check_project_budget_alerts_task() -> int:
    """Daily scheduled job to check project budget burn thresholds (80% and 100%)
    and send alerts to PM and company HR admins once per threshold.
    """
    db = get_task_db_session()
    alerts_sent = 0
    try:
        bind_tenant_to_session(db, company_id=None, is_platform_admin=True)

        projects = (
            db.query(Project)
            .filter(
                Project.budget.is_not(None),
                Project.budget > Decimal("0.00"),
                Project.status.notin_(["archived"]),
            )
            .all()
        )

        service = ProjectService(db)
        notifications = NotificationService(db)

        for project in projects:
            if project.budget_alert_80_sent_at and project.budget_alert_100_sent_at:
                continue

            summary = service.get_project_summary(
                company_id=project.company_id,
                project_id=project.id,
                actor=None,
            )

            budget_spent = summary.budget_spent
            if budget_spent is None or project.budget is None or project.budget <= Decimal("0.00"):
                continue

            ratio = budget_spent / project.budget

            recipients: set[UUID] = set()
            if project.manager_id:
                pm_emp = db.get(Employee, project.manager_id)
                if pm_emp and pm_emp.user_id:
                    recipients.add(pm_emp.user_id)

            hr_admins = (
                db.query(User)
                .filter(
                    User.company_id == project.company_id,
                    User.role == UserRole.hr_admin,
                    User.is_active.is_(True),
                )
                .all()
            )
            for hr in hr_admins:
                recipients.add(hr.id)

            should_commit = False

            if ratio >= Decimal("0.80") and not project.budget_alert_80_sent_at:
                for uid in recipients:
                    notifications.notify(
                        company_id=project.company_id,
                        user_id=uid,
                        type="budget_threshold_alert",
                        title="Budget Alert: 80% Reached",
                        message=f"Project '{project.name}' has reached 80% of its budget.",
                        entity_type="project",
                        entity_id=project.id,
                        action_url=f"/projects/{project.id}",
                    )
                project.budget_alert_80_sent_at = utcnow()
                should_commit = True
                alerts_sent += 1

            if ratio >= Decimal("1.00") and not project.budget_alert_100_sent_at:
                for uid in recipients:
                    notifications.notify(
                        company_id=project.company_id,
                        user_id=uid,
                        type="budget_threshold_alert",
                        title="Budget Alert: 100% Reached",
                        message=f"Project '{project.name}' has reached 100% of its budget.",
                        entity_type="project",
                        entity_id=project.id,
                        action_url=f"/projects/{project.id}",
                    )
                project.budget_alert_100_sent_at = utcnow()
                should_commit = True
                alerts_sent += 1

            if should_commit:
                db.commit()

        logger.info("project_budget_alerts_checked", extra={"alerts_sent": alerts_sent})
        return alerts_sent
    finally:
        db.close()
