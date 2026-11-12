from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin
from app.models.entities import Department, Complaint, User
from app.schemas.schemas import DepartmentResponse, DepartmentCreate, DepartmentUpdate

router = APIRouter(prefix="/departments", tags=["Departments"])

@router.get("", response_model=List[DepartmentResponse])
def list_departments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    departments = db.query(Department).all()
    result = []
    for d in departments:
        assigned = db.query(Complaint).filter(Complaint.assigned_department_id == d.id).all()
        total_assigned = len(assigned)
        resolved = sum(1 for c in assigned if c.status in ["Resolved", "Verified", "Closed"])
        pending = total_assigned - resolved

        resp = DepartmentResponse.model_validate(d)
        resp.total_assigned = total_assigned
        resp.pending_workload = pending
        resp.resolved_cases = resolved
        result.append(resp)
    return result

@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(
    dept_in: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    exists = db.query(Department).filter(
        (Department.name == dept_in.name) | (Department.code == dept_in.code)
    ).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department with this name or code already exists."
        )

    dept = Department(**dept_in.model_dump())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return DepartmentResponse.model_validate(dept)

@router.patch("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    dept_in: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    update_data = dept_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dept, key, value)

    db.commit()
    db.refresh(dept)
    return DepartmentResponse.model_validate(dept)
