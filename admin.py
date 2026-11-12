from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.core.database import get_db
from app.core.dependencies import require_admin_or_officer
from app.models.entities import (
    User,
    Complaint,
    Department,
    ComplaintStatusHistory,
    DuplicateCandidate,
    AuditLog,
    AgentExecution
)
from app.schemas.schemas import (
    AdminDashboardStats,
    ComplaintAssignDepartment,
    ComplaintSetPriority,
    ComplaintStatusUpdate,
    ComplaintDetailResponse,
    DuplicateReviewRequest
)
from app.services.notification_service import create_notification

def utcnow():
    return datetime.now(timezone.utc)

def make_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

router = APIRouter(prefix="/admin", tags=["Administration"])

@router.get("/dashboard", response_model=AdminDashboardStats)
def get_admin_dashboard_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    now = utcnow()
    all_complaints = db.query(Complaint).all()
    
    total = len(all_complaints)
    unassigned = sum(1 for c in all_complaints if c.assigned_department_id is None)
    high_priority = sum(1 for c in all_complaints if c.priority in ["High", "Critical"])
    
    # Overdue = not resolved/closed and expected_resolution_at < now
    overdue = sum(
        1 for c in all_complaints
        if c.status not in ["Resolved", "Verified", "Closed", "Rejected"]
        and c.expected_resolution_at and make_aware(c.expected_resolution_at) < now
    )
    
    resolved_list = [c for c in all_complaints if c.status in ["Resolved", "Verified", "Closed"]]
    resolved_count = len(resolved_list)
    resolution_rate = round((resolved_count / total * 100), 1) if total > 0 else 0.0

    # Calculate average resolution time
    res_durations = []
    for c in resolved_list:
        if c.resolved_at and c.created_at:
            delta = make_aware(c.resolved_at) - make_aware(c.created_at)
            res_durations.append(delta.total_seconds() / 3600.0)
    avg_hours = round(sum(res_durations) / len(res_durations), 1) if res_durations else 0.0

    # Status distribution
    status_counts = {}
    for c in all_complaints:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    # Category distribution
    cat_counts = {}
    for c in all_complaints:
        cat_counts[c.category] = cat_counts.get(c.category, 0) + 1

    # Priority distribution
    priority_counts = {}
    for c in all_complaints:
        priority_counts[c.priority] = priority_counts.get(c.priority, 0) + 1

    # Trend by date (last 7 days)
    trend_map = {}
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%b %d")
        trend_map[day] = {"date": day, "submitted": 0, "resolved": 0}

    for c in all_complaints:
        if c.created_at:
            day_str = c.created_at.strftime("%b %d")
            if day_str in trend_map:
                trend_map[day_str]["submitted"] += 1
        if c.resolved_at:
            day_str = c.resolved_at.strftime("%b %d")
            if day_str in trend_map:
                trend_map[day_str]["resolved"] += 1
                
    trend_by_date = list(trend_map.values())

    # Department performance
    departments = db.query(Department).all()
    dept_perf = []
    for d in departments:
        dept_complaints = [c for c in all_complaints if c.assigned_department_id == d.id]
        dept_total = len(dept_complaints)
        dept_resolved = sum(1 for c in dept_complaints if c.status in ["Resolved", "Verified", "Closed"])
        dept_pending = dept_total - dept_resolved
        rate = round((dept_resolved / dept_total * 100), 1) if dept_total > 0 else 100.0
        
        dept_perf.append({
            "department_id": d.id,
            "department_name": d.name,
            "code": d.code,
            "total_assigned": dept_total,
            "pending": dept_pending,
            "resolved": dept_resolved,
            "resolution_rate": rate,
            "sla_hours": d.sla_hours
        })

    # Recent activity feed from StatusHistory & AuditLog
    recent_history = db.query(ComplaintStatusHistory).order_by(desc(ComplaintStatusHistory.created_at)).limit(10).all()
    activity_feed = []
    for h in recent_history:
        complaint = db.query(Complaint).filter(Complaint.id == h.complaint_id).first()
        activity_feed.append({
            "id": h.id,
            "complaint_id": h.complaint_id,
            "reference_number": complaint.reference_number if complaint else "Unknown",
            "from_status": h.from_status,
            "to_status": h.to_status,
            "reason": h.change_reason,
            "actor": h.changed_by.full_name if h.changed_by else "System / AI",
            "timestamp": h.created_at.isoformat()
        })

    return AdminDashboardStats(
        total_complaints=total,
        unassigned_complaints=unassigned,
        high_priority_complaints=high_priority,
        overdue_complaints=overdue,
        resolved_complaints=resolved_count,
        average_resolution_hours=avg_hours,
        resolution_rate_percent=resolution_rate,
        status_distribution=status_counts,
        category_distribution=cat_counts,
        priority_distribution=priority_counts,
        trend_by_date=trend_by_date,
        department_performance=dept_perf,
        recent_activity=activity_feed
    )


@router.patch("/complaints/{complaint_id}/assign")
def assign_complaint_department(
    complaint_id: int,
    assign_in: ComplaintAssignDepartment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
        
    dept = db.query(Department).filter(Department.id == assign_in.department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    old_dept_name = complaint.assigned_department.name if complaint.assigned_department else "Unassigned"
    complaint.assigned_department_id = dept.id
    
    # If currently Submitted or AI Analysis, update to Assigned
    if complaint.status in ["Submitted", "AI Analysis"]:
        complaint.status = "Assigned"

    complaint.updated_at = utcnow()
    if not complaint.expected_resolution_at:
        complaint.expected_resolution_at = utcnow() + timedelta(hours=dept.sla_hours)

    reason = f"Reassigned from '{old_dept_name}' to '{dept.name}' by {current_user.full_name}. Notes: {assign_in.notes or 'None'}"
    db.add(ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=complaint.status,
        to_status=complaint.status,
        changed_by_id=current_user.id,
        change_reason=reason
    ))

    db.add(AuditLog(
        user_id=current_user.id,
        action="DEPARTMENT_REASSIGNED",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=reason
    ))

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Department Assigned",
        message=f"Complaint #{complaint.reference_number} has been assigned to {dept.name}.",
        notification_type="assignment"
    )

    db.commit()
    db.refresh(complaint)
    return {"message": "Department assigned successfully", "assigned_department": dept.name}


@router.patch("/complaints/{complaint_id}/priority")
def set_complaint_priority(
    complaint_id: int,
    priority_in: ComplaintSetPriority,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    old_priority = complaint.priority
    complaint.priority = priority_in.priority
    complaint.updated_at = utcnow()

    reason = f"Priority changed from {old_priority} to {priority_in.priority} by {current_user.full_name}. Reason: {priority_in.reason or 'Operational update'}"
    
    db.add(AuditLog(
        user_id=current_user.id,
        action="PRIORITY_CHANGED",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=reason
    ))

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Complaint Priority Updated",
        message=f"Complaint #{complaint.reference_number} priority changed to {priority_in.priority}.",
        notification_type="priority"
    )

    db.commit()
    db.refresh(complaint)
    return {"message": "Priority updated successfully", "priority": complaint.priority}


@router.patch("/complaints/{complaint_id}/status")
def update_complaint_status(
    complaint_id: int,
    status_in: ComplaintStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    prev_status = complaint.status
    complaint.status = status_in.status
    complaint.updated_at = utcnow()

    if status_in.status in ["Resolved", "Verified"]:
        complaint.resolved_at = utcnow()
    if status_in.status == "Verified":
        complaint.verified_at = utcnow()
    if status_in.status == "Rejected":
        complaint.rejection_reason = status_in.reason

    db.add(ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=prev_status,
        to_status=status_in.status,
        changed_by_id=current_user.id,
        change_reason=status_in.reason or f"Status updated to {status_in.status} by {current_user.full_name}"
    ))

    db.add(AuditLog(
        user_id=current_user.id,
        action="STATUS_UPDATED",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"From {prev_status} to {status_in.status}"
    ))

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Complaint Status Changed",
        message=f"Your complaint #{complaint.reference_number} is now '{status_in.status}'.",
        notification_type="status_change"
    )

    db.commit()
    db.refresh(complaint)
    return {"message": "Status updated successfully", "status": complaint.status}


@router.post("/complaints/{candidate_id}/duplicate")
def review_duplicate_candidate(
    candidate_id: int,
    review_in: DuplicateReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    candidate = db.query(DuplicateCandidate).filter(DuplicateCandidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Duplicate candidate record not found")

    candidate.status = review_in.status
    candidate.reviewed_by_id = current_user.id

    primary = db.query(Complaint).filter(Complaint.id == candidate.primary_complaint_id).first()
    if review_in.status == "confirmed":
        if primary:
            primary.duplicate_of_id = review_in.relink_to_id or candidate.candidate_complaint_id
            primary.is_potential_duplicate = True
    elif review_in.status == "dismissed":
        # Check if there are other pending candidates
        other_pending = db.query(DuplicateCandidate).filter(
            DuplicateCandidate.primary_complaint_id == candidate.primary_complaint_id,
            DuplicateCandidate.id != candidate.id,
            DuplicateCandidate.status == "pending"
        ).count()
        if other_pending == 0 and primary and not primary.duplicate_of_id:
            primary.is_potential_duplicate = False

    db.add(AuditLog(
        user_id=current_user.id,
        action=f"DUPLICATE_{review_in.status.upper()}",
        entity_type="DuplicateCandidate",
        entity_id=candidate.id,
        details=f"Candidate #{candidate.id} marked as {review_in.status}"
    ))

    db.commit()
    return {"message": f"Duplicate candidate marked as {review_in.status}"}
