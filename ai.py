from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin_or_officer
from app.models.entities import AgentExecution, Complaint, ResolutionEvidence, User
from app.schemas.schemas import AgentCardMetric, AgentExecutionResponse
from app.services.complaint_service import process_complaint_ai, verify_complaint_resolution
from app.agents.classifier_agent import classifier_agent
from app.agents.duplicate_agent import duplicate_agent
from app.agents.router_agent import router_agent
from app.agents.priority_agent import priority_agent
from app.agents.verifier_agent import verifier_agent
from app.core.config import settings

router = APIRouter(prefix="/ai", tags=["AI Operations"])

AGENTS_METADATA = [
    {
        "name": classifier_agent.name,
        "purpose": classifier_agent.purpose,
    },
    {
        "name": duplicate_agent.name,
        "purpose": duplicate_agent.purpose,
    },
    {
        "name": router_agent.name,
        "purpose": router_agent.purpose,
    },
    {
        "name": priority_agent.name,
        "purpose": priority_agent.purpose,
    },
    {
        "name": verifier_agent.name,
        "purpose": verifier_agent.purpose,
    },
]

@router.get("/agents", response_model=List[AgentCardMetric])
def get_ai_agents_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return metrics for the 5 agents calculated directly from database execution records."""
    metrics = []
    
    for agent_meta in AGENTS_METADATA:
        name = agent_meta["name"]
        purpose = agent_meta["purpose"]

        executions = db.query(AgentExecution).filter(AgentExecution.agent_name == name).all()
        total_count = len(executions)
        success_count = sum(1 for e in executions if e.status == "success")
        failed_count = sum(1 for e in executions if e.status == "failed")

        latest = db.query(AgentExecution).filter(
            AgentExecution.agent_name == name
        ).order_by(desc(AgentExecution.started_at)).first()

        latest_summary = latest.output_summary if latest else "Standing by for incoming complaints."
        last_exec_time = latest.completed_at if latest else None

        metrics.append(AgentCardMetric(
            agent_name=name,
            purpose=purpose,
            status="Active" if total_count > 0 else "Idle",
            processed_count=total_count,
            success_count=success_count,
            failed_count=failed_count,
            last_execution_time=last_exec_time,
            latest_output_summary=latest_summary
        ))

    return metrics


@router.get("/executions/{complaint_id}", response_model=List[AgentExecutionResponse])
def get_complaint_agent_executions(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    if current_user.role == "citizen" and complaint.citizen_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    executions = db.query(AgentExecution).filter(
        AgentExecution.complaint_id == complaint_id
    ).order_by(AgentExecution.started_at.asc()).all()

    return [AgentExecutionResponse.model_validate(e) for e in executions]


@router.post("/analyze/{complaint_id}")
def rerun_complaint_ai_analysis(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    updated_complaint = process_complaint_ai(db, complaint)
    return {
        "message": "AI multi-agent workflow executed successfully.",
        "complaint_id": updated_complaint.id,
        "category": updated_complaint.category,
        "priority": updated_complaint.priority,
        "status": updated_complaint.status,
        "assigned_department_id": updated_complaint.assigned_department_id
    }


@router.post("/verify-resolution/{complaint_id}")
def rerun_resolution_verification(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    evidence = db.query(ResolutionEvidence).filter(ResolutionEvidence.complaint_id == complaint_id).first()
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No resolution evidence has been submitted for this complaint yet."
        )

    verification = verify_complaint_resolution(db=db, complaint=complaint, evidence=evidence)
    return {
        "message": "Resolution verification completed.",
        "outcome": verification.outcome,
        "confidence_score": verification.confidence_score,
        "verification_summary": verification.verification_summary
    }
