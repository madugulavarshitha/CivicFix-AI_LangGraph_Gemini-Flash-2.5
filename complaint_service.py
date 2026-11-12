import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.models.entities import (
    Complaint,
    Department,
    AgentExecution,
    DuplicateCandidate,
    ComplaintStatusHistory,
    AuditLog,
    ResolutionEvidence,
    ResolutionVerification,
    User,
)
from app.graph.workflow import run_complaint_workflow
from app.agents.verifier_agent import verifier_agent
from app.services.notification_service import create_notification

def utcnow():
    return datetime.now(timezone.utc)

def generate_reference_number(db: Session) -> str:
    year = datetime.now().year
    for _ in range(10):
        ref_num = f"CF-{year}-{random.randint(1000, 9999)}"
        exists = db.query(Complaint).filter(Complaint.reference_number == ref_num).first()
        if not exists:
            return ref_num
    return f"CF-{year}-{int(datetime.now().timestamp()) % 100000}"

def process_complaint_ai(db: Session, complaint: Complaint) -> Complaint:
    """Execute the multi-agent triage workflow on a complaint."""
    # 1. Gather context
    existing_records = db.query(Complaint).filter(
        Complaint.id != complaint.id,
        Complaint.status.notin_(["Rejected", "Closed"])
    ).limit(50).all()

    existing_complaints = [
        {
            "id": c.id,
            "reference_number": c.reference_number,
            "title": c.title,
            "description": c.description,
            "category": c.category,
            "location": c.location,
            "latitude": c.latitude,
            "longitude": c.longitude,
        }
        for c in existing_records
    ]

    dept_records = db.query(Department).filter(Department.active == True).all()
    departments = [
        {
            "id": d.id,
            "name": d.name,
            "code": d.code,
            "sla_hours": d.sla_hours,
        }
        for d in dept_records
    ]

    complaint_dict = {
        "id": complaint.id,
        "title": complaint.title,
        "description": complaint.description,
        "category": complaint.category,
        "location": complaint.location,
        "latitude": complaint.latitude,
        "longitude": complaint.longitude,
    }

    # 2. Run LangGraph workflow
    workflow_result = run_complaint_workflow(
        complaint_dict=complaint_dict,
        existing_complaints=existing_complaints,
        departments=departments
    )

    # 3. Persist agent execution logs
    for log in workflow_result.get("agent_logs", []):
        execution = AgentExecution(
            complaint_id=complaint.id,
            agent_name=log["agent_name"],
            status=log["status"],
            input_summary=log.get("input_summary"),
            output_summary=log.get("output_summary"),
            confidence=log.get("confidence"),
            error_message=log.get("error_message"),
            started_at=log.get("started_at", utcnow()),
            completed_at=log.get("completed_at", utcnow()),
            retry_count=0
        )
        db.add(execution)

    # 4. Handle duplicates
    dup_res = workflow_result.get("duplicates") or {}
    if dup_res.get("is_potential_duplicate") and dup_res.get("candidates"):
        complaint.is_potential_duplicate = True
        complaint.duplicate_score = dup_res.get("highest_score")
        
        for cand in dup_res.get("candidates", []):
            dup_record = DuplicateCandidate(
                primary_complaint_id=complaint.id,
                candidate_complaint_id=cand["candidate_complaint_id"],
                similarity_score=cand["similarity_score"],
                geo_distance_meters=cand.get("geo_distance_meters"),
                match_reason=cand.get("match_reason", "High similarity"),
                status="pending"
            )
            db.add(dup_record)
            
        create_notification(
            db=db,
            user_id=complaint.citizen_id,
            complaint_id=complaint.id,
            title="Potential Similar Complaint Detected",
            message=f"Our AI detected similar reported issues nearby. An officer will review and consolidate if appropriate.",
            notification_type="duplicate"
        )

    # 5. Apply AI classification
    class_res = workflow_result.get("classification") or {}
    if class_res.get("status") == "success":
        complaint.category = class_res.get("category", complaint.category)
        complaint.ai_summary = class_res.get("summary")
        complaint.classification_confidence = class_res.get("confidence")

    # 6. Apply department routing
    routing_res = workflow_result.get("routing") or {}
    if routing_res.get("status") == "success" and routing_res.get("department_id"):
        complaint.assigned_department_id = routing_res.get("department_id")

    # 7. Apply priority assessment & SLA
    priority_res = workflow_result.get("priority") or {}
    urgency_hours = 48
    if priority_res.get("status") == "success":
        complaint.priority = priority_res.get("priority", "Medium")
        urgency_hours = priority_res.get("urgency_hours", 48)

    complaint.expected_resolution_at = utcnow() + timedelta(hours=urgency_hours)
    
    # 8. Update status
    prev_status = complaint.status
    new_status = "Assigned" if complaint.assigned_department_id else "AI Analysis"
    complaint.status = new_status
    
    history_entry = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=prev_status,
        to_status=new_status,
        change_reason=f"Multi-agent triage completed. Category: {complaint.category}, Priority: {complaint.priority}."
    )
    db.add(history_entry)

    # 9. Notify citizen
    dept_name = routing_res.get("department_name", "Municipal Operations")
    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Complaint Assigned & Prioritized",
        message=f"Your complaint #{complaint.reference_number} was classified as {complaint.category} ({complaint.priority} priority) and assigned to {dept_name}.",
        notification_type="assignment"
    )

    db.commit()
    db.refresh(complaint)
    return complaint


def verify_complaint_resolution(
    db: Session,
    complaint: Complaint,
    evidence: ResolutionEvidence
) -> ResolutionVerification:
    """Run Agent 5 (Resolution Verifier) on submitted evidence."""
    started_at = utcnow()
    has_photo = bool(evidence.photo_url)
    
    result = verifier_agent.execute(
        complaint_title=complaint.title,
        complaint_description=complaint.description,
        complaint_category=complaint.category,
        completion_notes=evidence.completion_notes,
        has_photo=has_photo
    )
    completed_at = utcnow()
    
    # Record Agent 5 execution in agent_executions
    import json
    execution = AgentExecution(
        complaint_id=complaint.id,
        agent_name=verifier_agent.name,
        status=result["status"],
        input_summary=f"Notes: {evidence.completion_notes[:60]} | Photo attached: {has_photo}",
        output_summary=json.dumps({
            "outcome": result["outcome"],
            "confidence": result["confidence_score"],
            "summary": result["verification_summary"]
        }),
        confidence=result["confidence_score"],
        error_message=result.get("error"),
        started_at=started_at,
        completed_at=completed_at,
        retry_count=0
    )
    db.add(execution)

    # Create verification record
    verification = ResolutionVerification(
        complaint_id=complaint.id,
        outcome=result["outcome"],
        confidence_score=result["confidence_score"],
        checks_performed=json.dumps(result.get("checks_performed", {})),
        verification_summary=result["verification_summary"],
        verified_at=completed_at
    )
    db.add(verification)

    # Update complaint status based on verification outcome
    prev_status = complaint.status
    if result["outcome"] == "Verified":
        complaint.status = "Verified"
        complaint.verified_at = completed_at
    else:
        # Needs Review / Pending Officer Supervisor Confirmation
        complaint.status = "Resolved"  # Remains in resolved until officer supervisor confirms or requests review

    complaint.resolved_at = completed_at

    history_entry = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=prev_status,
        to_status=complaint.status,
        changed_by_id=evidence.officer_id,
        change_reason=f"Resolution evidence submitted. AI Verifier outcome: {result['outcome']} ({result['verification_summary']})"
    )
    db.add(history_entry)

    # Notify Citizen
    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title=f"Complaint Resolution: {result['outcome']}",
        message=f"Work has been completed for #{complaint.reference_number}. Verification outcome: {result['outcome']}. Please review.",
        notification_type="verification"
    )

    db.commit()
    db.refresh(verification)
    return verification

def process_complaint_pipeline(db: Session, complaint_id: int) -> Complaint:
    """Wrapper to process a complaint by ID through the multi-agent AI pipeline."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise ValueError(f"Complaint with ID {complaint_id} not found")
    return process_complaint_ai(db, complaint)
