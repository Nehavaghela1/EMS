import uuid
from app.db.session import SessionLocal
from app.modules.identity.models import User, UserRole
from app.modules.hr.models import Employee, Department, InvitationStatus
from app.modules.time_leave.models import Shift
from datetime import date

from app.db.rls import bind_tenant_to_session

def sync_employees():
    db = SessionLocal()
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)

    # 1. Fetch all admin users who don't have a linked employee record
    # Since User -> Employee linkage is actually Employee.user_id -> User.id
    # we need to find Users whose ID doesn't exist in Employee.user_id
    
    # Get all user IDs that already have an employee record
    linked_user_ids_query = db.query(Employee.user_id).filter(Employee.user_id.isnot(None))
    linked_user_ids = {row[0] for row in linked_user_ids_query.all()}

    unlinked_admins = db.query(User).filter(
        User.id.notin_(linked_user_ids),
        User.role.in_([UserRole.hr_admin, UserRole.super_admin])
    ).all()

    print(f"Found {len(unlinked_admins)} unlinked admin accounts.")

    for user in unlinked_admins:
        dept = db.query(Department).filter(Department.company_id == user.company_id).first()
        shift = db.query(Shift).filter(Shift.company_id == user.company_id).first()
        
        name_part = user.email.split("@")[0].replace(".", " ").title()
        names = name_part.split()
        first_name = names[0] if names else "Admin"
        last_name = names[1] if len(names) > 1 else None
        
        emp_count = db.query(Employee).filter(Employee.company_id == user.company_id).count() + 1
        
        new_employee = Employee(
            id=uuid.uuid4(),
            company_id=user.company_id,
            user_id=user.id,
            first_name=first_name,
            last_name=last_name,
            email=user.email,
            employee_code=f"ADMIN-{emp_count:04d}",
            position="HR Admin / Org Head",
            department_id=dept.id if dept else None,
            employment_type="full_time",
            hire_date=date.today(),
            is_active=True,
            invitation_status=InvitationStatus.activated
        )
        db.add(new_employee)
        db.flush()
        
        print(f"Linked {user.email} -> Employee ID {new_employee.id} ({new_employee.employee_code})")

    db.commit()
    db.close()
    print("All existing HR Admin accounts are now linked as Employees!")

if __name__ == "__main__":
    sync_employees()
