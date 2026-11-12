import os
import shutil
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin_or_officer
from app.core.config import settings
from app.models.entities import (
    User,
    Complaint,
    ComplaintAttachment,
    ComplaintComment,
    ComplaintStatusHistory,
    ResolutionEvidence,
    AuditLog,
    Department
)
from app.schemas.schemas import (
    ComplaintCreate,
    ComplaintResponse,
    ComplaintDetailResponse,
    CommentCreate,
    CommentResponse,
    ComplaintReopen,
    ResolutionEvidenceCreate,
    ResolutionEvidenceResponse
)
from app.services.complaint_service import (
    generate_reference_number,
    process_complaint_ai,
    verify_complaint_resolution
)
from app.services.notification_service import create_notification

def utcnow():
    return datetime.now(timezone.utc)

router = APIRouter(prefix="/complaints", tags=["Complaints"])

@router.post("", response_model=ComplaintDetailResponse, status_code=status.HTTP_201_CREATED)
def create_complaint(
    complaint_in: ComplaintCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ref_num = generate_reference_number(db)
    
    complaint = Complaint(
        reference_number=ref_num,
        citizen_id=current_user.id,
        title=complaint_in.title,
        description=complaint_in.description,
        category=complaint_in.category or "Other",
        location=complaint_in.location,
        landmark=complaint_in.landmark,
        latitude=complaint_in.latitude,
        longitude=complaint_in.longitude,
        contact_phone=complaint_in.contact_phone,
        priority="Medium",
        status="Submitted",
        created_at=utcnow(),
        updated_at=utcnow()
    )
    db.add(complaint)
    db.flush()

    # Initial history record
    db.add(ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=None,
        to_status="Submitted",
        changed_by_id=current_user.id,
        change_reason="Complaint submitted by citizen."
    ))

    # Audit log
    db.add(AuditLog(
        user_id=current_user.id,
        action="COMPLAINT_CREATED",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"Created complaint {ref_num}"
    ))

    db.commit()
    db.refresh(complaint)

    # Run AI multi-agent workflow
    try:
        complaint = process_complaint_ai(db, complaint)
    except Exception as e:
        # If AI workflow fails, keep the complaint safe as Submitted or AI Analysis
        complaint.status = "AI Analysis"
        db.commit()
        db.refresh(complaint)

    return complaint


@router.post("/with-file", response_model=ComplaintDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_complaint_with_file(
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form("Other"),
    location: str = Form(...),
    landmark: Optional[str] = Form(None),
    latitude: Optional[str] = Form(None),
    longitude: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ref_num = generate_reference_number(db)
    
    parsed_lat: Optional[float] = None
    parsed_lon: Optional[float] = None
    if latitude and str(latitude).strip():
        try:
            parsed_lat = float(str(latitude).strip())
        except (ValueError, TypeError):
            parsed_lat = None
    if longitude and str(longitude).strip():
        try:
            parsed_lon = float(str(longitude).strip())
        except (ValueError, TypeError):
            parsed_lon = None

    complaint = Complaint(
        reference_number=ref_num,
        citizen_id=current_user.id,
        title=title,
        description=description,
        category=category,
        location=location,
        landmark=landmark,
        latitude=parsed_lat,
        longitude=parsed_lon,
        contact_phone=contact_phone,
        priority="Medium",
        status="Submitted",
        created_at=utcnow(),
        updated_at=utcnow()
    )
    db.add(complaint)
    db.flush()

    # Handle file upload if provided
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in settings.ALLOWED_EXTENSIONS:
            safe_filename = f"{ref_num}_{int(datetime.now().timestamp())}{ext}"
            file_path = os.path.join(settings.UPLOAD_DIR, safe_filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            file_size = os.path.getsize(file_path)
            attachment = ComplaintAttachment(
                complaint_id=complaint.id,
                file_name=file.filename,
                file_path=f"/uploads/{safe_filename}",
                file_type=file.content_type or "image/jpeg",
                file_size=file_size,
                attachment_type="initial",
                uploaded_by_id=current_user.id
            )
            db.add(attachment)

    db.add(ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=None,
        to_status="Submitted",
        changed_by_id=current_user.id,
        change_reason="Complaint submitted with supporting attachment."
    ))

    db.commit()
    db.refresh(complaint)

    # Run AI multi-agent workflow
    try:
        complaint = process_complaint_ai(db, complaint)
    except Exception:
        complaint.status = "AI Analysis"
        db.commit()
        db.refresh(complaint)

    return complaint


@router.get("", response_model=List[ComplaintResponse])
def list_complaints(
    status_filter: Optional[str] = Query(None, alias="status"),
    category_filter: Optional[str] = Query(None, alias="category"),
    department_id: Optional[int] = Query(None),
    priority_filter: Optional[str] = Query(None, alias="priority"),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Complaint)
    
    # If citizen, only see their own complaints
    if current_user.role == "citizen":
        query = query.filter(Complaint.citizen_id == current_user.id)
    # If officer assigned to specific department, optionally filter or see all
    
    if status_filter:
        query = query.filter(Complaint.status == status_filter)
    if category_filter:
        query = query.filter(Complaint.category == category_filter)
    if department_id:
        query = query.filter(Complaint.assigned_department_id == department_id)
    if priority_filter:
        query = query.filter(Complaint.priority == priority_filter)
    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            or_(
                Complaint.title.ilike(search_fmt),
                Complaint.description.ilike(search_fmt),
                Complaint.reference_number.ilike(search_fmt),
                Complaint.location.ilike(search_fmt)
            )
        )
        
    records = query.order_by(desc(Complaint.created_at)).offset(skip).limit(limit).all()
    
    # Format department name & citizen name
    result = []
    for c in records:
        resp = ComplaintResponse.model_validate(c)
        if c.assigned_department:
            resp.assigned_department_name = c.assigned_department.name
        if c.citizen:
            resp.citizen_name = c.citizen.full_name
        result.append(resp)
        
    return result


@router.get("/{complaint_id}", response_model=ComplaintDetailResponse)
def get_complaint_detail(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
        
    # Check access permission: citizen can only view their own
    if current_user.role == "citizen" and complaint.citizen_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this complaint."
        )

    # Filter internal comments for citizens
    if current_user.role == "citizen":
        complaint.comments = [c for c in complaint.comments if not c.is_internal]

    resp = ComplaintDetailResponse.model_validate(complaint)
    if complaint.assigned_department:
        resp.assigned_department_name = complaint.assigned_department.name
    if complaint.citizen:
        resp.citizen_name = complaint.citizen.full_name

    # Populate candidate complaint details
    for idx, cand in enumerate(resp.duplicate_candidates):
        cand_obj = db.query(Complaint).filter(Complaint.id == cand.candidate_complaint_id).first()
        if cand_obj:
            cand.candidate_reference = cand_obj.reference_number
            cand.candidate_title = cand_obj.title

    # Populate comment user details
    for c_resp in resp.comments:
        u = db.query(User).filter(User.id == c_resp.user_id).first()
        if u:
            c_resp.user_name = u.full_name
            c_resp.user_role = u.role

    # Populate status history user details
    for h_resp in resp.status_history:
        orig = next((h for h in complaint.status_history if h.id == h_resp.id), None)
        if orig and orig.changed_by:
            h_resp.changed_by_name = orig.changed_by.full_name

    return resp


@router.post("/{complaint_id}/comments", response_model=CommentResponse)
def add_comment(
    complaint_id: int,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
        
    if current_user.role == "citizen" and complaint.citizen_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Citizens cannot create internal officer comments
    is_internal = comment_in.is_internal if current_user.role in ["admin", "officer"] else False

    comment = ComplaintComment(
        complaint_id=complaint.id,
        user_id=current_user.id,
        comment_text=comment_in.comment_text,
        is_internal=is_internal,
        created_at=utcnow()
    )
    db.add(comment)

    # Notify counterpart
    if current_user.role == "citizen" and complaint.assigned_department:
        # Officer notified
        pass
    elif current_user.role in ["admin", "officer"] and not is_internal:
        create_notification(
            db=db,
            user_id=complaint.citizen_id,
            complaint_id=complaint.id,
            title="New Update on Your Complaint",
            message=f"Officer added an update to #{complaint.reference_number}: '{comment_in.comment_text[:60]}...'",
            notification_type="comment"
        )

    db.commit()
    db.refresh(comment)
    
    resp = CommentResponse.model_validate(comment)
    resp.user_name = current_user.full_name
    resp.user_role = current_user.role
    return resp


@router.post("/{complaint_id}/reopen", response_model=ComplaintDetailResponse)
def reopen_complaint(
    complaint_id: int,
    reopen_in: ComplaintReopen,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")
        
    if current_user.role == "citizen" and complaint.citizen_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if complaint.status not in ["Resolved", "Verified", "Closed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only resolved or closed complaints can be reopened. Current status: {complaint.status}"
        )

    prev_status = complaint.status
    complaint.status = "Reopened"
    complaint.reopen_reason = reopen_in.reopen_reason
    complaint.updated_at = utcnow()

    db.add(ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=prev_status,
        to_status="Reopened",
        changed_by_id=current_user.id,
        change_reason=f"Citizen reopened issue: {reopen_in.reopen_reason}"
    ))

    db.add(AuditLog(
        user_id=current_user.id,
        action="COMPLAINT_REOPENED",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=reopen_in.reopen_reason
    ))

    db.commit()
    db.refresh(complaint)
    return get_complaint_detail(complaint_id=complaint.id, db=db, current_user=current_user)


@router.post("/{complaint_id}/evidence", response_model=ComplaintDetailResponse)
def submit_resolution_evidence(
    complaint_id: int,
    evidence_in: ResolutionEvidenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_officer)
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found")

    # Save evidence
    evidence = db.query(ResolutionEvidence).filter(ResolutionEvidence.complaint_id == complaint.id).first()
    if not evidence:
        evidence = ResolutionEvidence(
            complaint_id=complaint.id,
            officer_id=current_user.id,
            completion_notes=evidence_in.completion_notes,
            photo_url=evidence_in.photo_url,
            supporting_details=evidence_in.supporting_details,
            resolution_timestamp=utcnow()
        )
        db.add(evidence)
    else:
        evidence.officer_id = current_user.id
        evidence.completion_notes = evidence_in.completion_notes
        evidence.photo_url = evidence_in.photo_url
        evidence.supporting_details = evidence_in.supporting_details
        evidence.resolution_timestamp = utcnow()

    db.commit()
    db.refresh(evidence)

    # Automatically trigger Agent 5: Resolution Verifier
    verify_complaint_resolution(db=db, complaint=complaint, evidence=evidence)

    return get_complaint_detail(complaint_id=complaint.id, db=db, current_user=current_user)
