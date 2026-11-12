import os
import json
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token
)
from app.models.entities import (
    User,
    Department,
    Complaint,
    ComplaintAttachment,
    ComplaintComment,
    ComplaintStatusHistory,
    DuplicateCandidate,
    AgentExecution,
    ResolutionEvidence,
    ResolutionVerification,
    Notification,
    AuditLog,
    utcnow
)
from app.services.complaint_service import process_complaint_pipeline, verify_complaint_resolution
from app.services.notification_service import create_notification

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")

def make_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def render_template(request: Request, name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context, status_code=status_code)

def get_current_user_from_request(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        # Check authorization header as fallback
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        return None
        
    if token.startswith("Bearer "):
        token = token[7:]
        
    payload = decode_access_token(token)
    if not payload:
        return None
        
    sub = payload.get("sub")
    if not sub:
        return None
        
    if str(sub).isdigit():
        return db.query(User).filter(User.id == int(sub), User.is_active == True).first()
    return db.query(User).filter(User.email == str(sub), User.is_active == True).first()

def get_template_context(request: Request, user: Optional[User], db: Session, active_page: str = "", **kwargs) -> dict:
    unread_count = 0
    if user:
        unread_count = db.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.is_read == False
        ).count()
        
    ctx = {
        "request": request,
        "user": user,
        "active_page": active_page,
        "unread_notifications_count": unread_count,
        "now": utcnow()
    }
    ctx.update(kwargs)
    return ctx

# -------------------------------------------------------------
# Root & Authentication Routes
# -------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def index_redirect(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role in ["admin", "officer"]:
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/citizen/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None, email: Optional[str] = None, force: Optional[int] = None, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if user and not force:
        if user.role in ["admin", "officer"]:
            return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(url="/citizen/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        
    context = get_template_context(request, None, db, active_page="login", error=error, email=email)
    return render_template(request, "login.html", context)

@router.post("/login")
def handle_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    
    if not user or not verify_password(password, user.password_hash):
        context = get_template_context(
            request, None, db, active_page="login",
            error="Invalid email address or password. Please verify your credentials.",
            email=email
        )
        return render_template(request, "login.html", context, status_code=400)
        
    token = create_access_token(subject=user.email, role=user.role)
    target_url = "/admin/dashboard" if user.role in ["admin", "officer"] else "/citizen/dashboard"
    
    response = RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response

@router.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    error: Optional[str] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    locality: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Always display the register page and clear any stale session so new citizens can register
    context = get_template_context(
        request, None, db, active_page="register",
        error=error, full_name=full_name, email=email, locality=locality, phone=phone
    )
    response = render_template(request, "register.html", context)
    response.delete_cookie(key="access_token", path="/")
    response.set_cookie(key="access_token", value="", max_age=0, expires=0, path="/")
    return response

@router.post("/register")
def handle_register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    locality: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    phone: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()
    clean_locality = locality.strip()
    
    if password != confirm_password:
        context = get_template_context(
            request, None, db, active_page="register",
            error="Passwords do not match. Please ensure both passwords match.",
            full_name=full_name, email=email, locality=locality, phone=phone
        )
        return render_template(request, "register.html", context, status_code=400)
        
    if len(password) < 6:
        context = get_template_context(
            request, None, db, active_page="register",
            error="Password must contain at least 6 characters.",
            full_name=full_name, email=email, locality=locality, phone=phone
        )
        return render_template(request, "register.html", context, status_code=400)

    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        context = get_template_context(
            request, None, db, active_page="register",
            error="An account with this email address already exists. Please sign in instead.",
            full_name=full_name, email=email, locality=locality, phone=phone
        )
        return render_template(request, "register.html", context, status_code=400)

    new_user = User(
        full_name=full_name.strip(),
        email=clean_email,
        locality=clean_locality,
        phone=phone.strip() if phone else None,
        password_hash=get_password_hash(password),
        role="citizen",
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Initial welcome notification
    create_notification(
        db=db,
        user_id=new_user.id,
        title="Welcome to CivicFix AI",
        message=f"Welcome {new_user.full_name}! Your citizen account for {clean_locality} has been registered. You can now report municipal issues and track real-time resolution.",
        notification_type="status_change"
    )

    token = create_access_token(subject=new_user.email, role=new_user.role)
    response = RedirectResponse(url="/citizen/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response

@router.get("/logout")
@router.post("/logout")
def handle_logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token", path="/")
    response.set_cookie(key="access_token", value="", max_age=0, expires=0, path="/")
    return response

# -------------------------------------------------------------
# Citizen Routes (Dashboard, Submit, Track, List)
# -------------------------------------------------------------

@router.get("/citizen/dashboard", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def citizen_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role in ["admin", "officer"]:
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    complaints = db.query(Complaint).filter(Complaint.citizen_id == user.id).order_by(desc(Complaint.created_at)).all()
    
    total_count = len(complaints)
    open_count = sum(1 for c in complaints if c.status in ["Submitted", "AI Analysis", "Assigned"])
    in_progress_count = sum(1 for c in complaints if c.status in ["In Progress", "Reopened"])
    resolved_count = sum(1 for c in complaints if c.status in ["Resolved", "Verified", "Closed"])

    # Status distribution for CSS chart
    status_distribution = {}
    for c in complaints:
        status_distribution[c.status] = status_distribution.get(c.status, 0) + 1

    recent_notifications = db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(desc(Notification.created_at)).limit(5).all()

    context = get_template_context(
        request, user, db, active_page="citizen_dashboard",
        total_count=total_count,
        open_count=open_count,
        in_progress_count=in_progress_count,
        resolved_count=resolved_count,
        complaints=complaints,
        status_distribution=status_distribution,
        notifications=recent_notifications
    )
    return render_template(request, "citizen_dashboard.html", context)

@router.get("/complaints/new", response_class=HTMLResponse)
def submit_complaint_page(request: Request, error: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    context = get_template_context(request, user, db, active_page="submit_complaint", error=error)
    return render_template(request, "submit_complaint.html", context)

@router.post("/complaints/new")
async def handle_submit_complaint(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    landmark: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    latitude: Optional[str] = Form(None),
    longitude: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Safely parse optional coordinates (empty strings from HTML form shouldn't trigger 422 error)
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

    if len(title.strip()) < 5 or len(description.strip()) < 10:
        context = get_template_context(
            request, user, db, active_page="submit_complaint",
            error="Please provide a descriptive title (min 5 chars) and detailed description (min 10 chars).",
            title=title, description=description, location=location, landmark=landmark
        )
        return render_template(request, "submit_complaint.html", context, status_code=400)

    # Generate unique reference number
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    reference_number = f"CF-{date_str}-{short_uuid}"

    complaint = Complaint(
        reference_number=reference_number,
        citizen_id=user.id,
        category=category.strip(),
        title=title.strip(),
        description=description.strip(),
        location=location.strip(),
        landmark=landmark.strip() if landmark else None,
        latitude=parsed_lat,
        longitude=parsed_lon,
        status="Submitted",
        priority="Medium"
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    # Initial status history
    init_history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=None,
        to_status="Submitted",
        change_reason="Complaint submitted by citizen. Queued for autonomous AI triage."
    )
    db.add(init_history)

    # Initial audit log
    audit = AuditLog(
        user_id=user.id,
        action="CREATE_COMPLAINT",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"Complaint #{reference_number} submitted by citizen {user.full_name}"
    )
    db.add(audit)
    db.commit()

    # Handle image upload if provided
    if file and file.filename:
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp"]:
            saved_filename = f"{reference_number}_{uuid.uuid4().hex[:6]}{ext}"
            saved_path = os.path.join(settings.UPLOAD_DIR, saved_filename)
            content = await file.read()
            with open(saved_path, "wb") as f:
                f.write(content)
            
            attachment = ComplaintAttachment(
                complaint_id=complaint.id,
                file_name=filename,
                file_path=saved_path,
                file_url=f"/uploads/{saved_filename}",
                file_type=ext[1:],
                file_size=len(content)
            )
            db.add(attachment)
            db.commit()

    # Run LangGraph AI Multi-Agent Pipeline
    try:
        complaint = process_complaint_pipeline(db, complaint.id)
    except Exception as e:
        print(f"Agent pipeline notice for #{reference_number}: {e}")

    return RedirectResponse(url=f"/complaints/{complaint.id}/confirmation", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/complaints/{complaint_id}/confirmation", response_class=HTMLResponse)
def complaint_confirmation_page(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    context = get_template_context(request, user, db, active_page="complaint_confirmation", complaint=complaint)
    return render_template(request, "complaint_confirmation.html", context)

@router.get("/complaints", response_class=HTMLResponse)
def citizen_complaints_list(
    request: Request,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    query = db.query(Complaint)
    if user.role not in ["admin", "officer"]:
        query = query.filter(Complaint.citizen_id == user.id)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Complaint.title.ilike(search_term),
                Complaint.reference_number.ilike(search_term),
                Complaint.location.ilike(search_term),
                Complaint.description.ilike(search_term)
            )
        )
    if status:
        query = query.filter(Complaint.status == status)

    complaints = query.order_by(desc(Complaint.created_at)).all()

    context = get_template_context(
        request, user, db, active_page="complaints_list",
        complaints=complaints,
        search=search,
        status=status
    )
    return render_template(request, "complaints_list.html", context)

@router.get("/complaints/{complaint_id}", response_class=HTMLResponse)
def track_complaint_page(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Citizen ownership guard
    if user.role not in ["admin", "officer"] and complaint.citizen_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to complaint record")

    departments = db.query(Department).all()
    comments = db.query(ComplaintComment).filter(ComplaintComment.complaint_id == complaint_id).order_by(ComplaintComment.created_at.asc()).all()
    status_history = db.query(ComplaintStatusHistory).filter(ComplaintStatusHistory.complaint_id == complaint_id).order_by(ComplaintStatusHistory.created_at.asc()).all()
    duplicate_candidates = db.query(DuplicateCandidate).filter(
        or_(
            DuplicateCandidate.primary_complaint_id == complaint_id,
            DuplicateCandidate.candidate_complaint_id == complaint_id
        )
    ).all()
    
    # Load verification checks if present
    verification = complaint.resolution_verification
    checks_dict = {}
    if verification and verification.checks_performed:
        try:
            checks_dict = json.loads(verification.checks_performed)
        except Exception:
            checks_dict = {}

    context = get_template_context(
        request, user, db, active_page="track_complaint",
        complaint=complaint,
        departments=departments,
        comments=comments,
        status_history=status_history,
        duplicate_candidates=duplicate_candidates,
        verification_checks=checks_dict
    )
    return render_template(request, "track_complaint.html", context)

@router.post("/complaints/{complaint_id}/comments")
def add_complaint_comment(
    complaint_id: int,
    request: Request,
    comment_text: str = Form(...),
    is_internal: bool = Form(False),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if user.role not in ["admin", "officer"] and complaint.citizen_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    new_comment = ComplaintComment(
        complaint_id=complaint_id,
        user_id=user.id,
        comment_text=comment_text.strip(),
        is_internal=(is_internal and user.role in ["admin", "officer"])
    )
    db.add(new_comment)

    audit = AuditLog(
        user_id=user.id,
        action="ADD_COMMENT",
        entity_type="Complaint",
        entity_id=complaint_id,
        details=f"Comment added by {user.full_name} ({user.role})"
    )
    db.add(audit)
    db.commit()

    return RedirectResponse(url=f"/complaints/{complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/complaints/{complaint_id}/reopen")
def reopen_complaint(
    complaint_id: int,
    request: Request,
    reopen_reason: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    prev_status = complaint.status
    complaint.status = "Reopened"
    complaint.is_reopened = True
    complaint.reopened_reason = reopen_reason.strip()
    complaint.reopened_at = utcnow()

    history = ComplaintStatusHistory(
        complaint_id=complaint_id,
        from_status=prev_status,
        to_status="Reopened",
        change_reason=f"Citizen requested reopening: {reopen_reason.strip()}"
    )
    db.add(history)

    # Notify admins/officers
    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Resolution Reopened",
        message=f"You requested to reopen complaint #{complaint.reference_number}. Municipal staff will review the field resolution.",
        notification_type="status_change"
    )

    audit = AuditLog(
        user_id=user.id,
        action="REOPEN_COMPLAINT",
        entity_type="Complaint",
        entity_id=complaint_id,
        details=f"Complaint reopened by citizen. Reason: {reopen_reason.strip()}"
    )
    db.add(audit)
    db.commit()

    return RedirectResponse(url=f"/complaints/{complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

# -------------------------------------------------------------
# Admin & Municipal Officer Routes
# -------------------------------------------------------------

@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    now = utcnow()
    all_complaints = db.query(Complaint).all()
    departments = db.query(Department).all()

    total_count = len(all_complaints)
    unassigned_count = sum(1 for c in all_complaints if c.assigned_department_id is None)
    high_priority_count = sum(1 for c in all_complaints if c.priority in ["High", "Critical"])
    overdue_count = sum(
        1 for c in all_complaints
        if c.status not in ["Resolved", "Verified", "Closed", "Rejected"]
        and c.expected_resolution_at and make_aware(c.expected_resolution_at) < now
    )

    resolved_list = [c for c in all_complaints if c.status in ["Resolved", "Verified", "Closed"]]
    resolved_count = len(resolved_list)
    resolution_rate = round((resolved_count / total_count * 100), 1) if total_count > 0 else 0.0

    durations = []
    for c in resolved_list:
        if c.resolved_at and c.created_at:
            durations.append((make_aware(c.resolved_at) - make_aware(c.created_at)).total_seconds() / 3600.0)
    avg_resolution_hours = round(sum(durations) / len(durations), 1) if durations else 0.0

    category_distribution = {}
    for c in all_complaints:
        category_distribution[c.category] = category_distribution.get(c.category, 0) + 1

    priority_distribution = {}
    for c in all_complaints:
        priority_distribution[c.priority] = priority_distribution.get(c.priority, 0) + 1

    department_stats = []
    for d in departments:
        assigned = [c for c in all_complaints if c.assigned_department_id == d.id]
        tot = len(assigned)
        res = sum(1 for c in assigned if c.status in ["Resolved", "Verified", "Closed"])
        pend = tot - res
        rate = round((res / tot * 100), 1) if tot > 0 else 0.0
        department_stats.append({
            "name": d.name,
            "total_assigned": tot,
            "pending": pend,
            "resolved": res,
            "sla_hours": d.sla_hours,
            "resolution_rate": rate
        })

    # Recent activity logs from status history
    recent_history = db.query(ComplaintStatusHistory).order_by(desc(ComplaintStatusHistory.created_at)).limit(8).all()
    recent_activity = []
    for h in recent_history:
        recent_activity.append({
            "reference_number": h.complaint.reference_number if h.complaint else "CF-System",
            "from_status": h.from_status,
            "to_status": h.to_status,
            "reason": h.change_reason or "Status updated",
            "timestamp": h.created_at.strftime("%b %d, %H:%M") if h.created_at else ""
        })

    context = get_template_context(
        request, user, db, active_page="admin_dashboard",
        total_count=total_count,
        unassigned_count=unassigned_count,
        high_priority_count=high_priority_count,
        overdue_count=overdue_count,
        resolved_count=resolved_count,
        resolution_rate=resolution_rate,
        avg_resolution_hours=avg_resolution_hours,
        category_distribution=category_distribution,
        priority_distribution=priority_distribution,
        department_stats=department_stats,
        recent_activity=recent_activity
    )
    return render_template(request, "admin_dashboard.html", context)

@router.get("/admin/complaints", response_class=HTMLResponse)
def admin_complaint_management_page(
    request: Request,
    search: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    department_id: Optional[int] = None,
    page: int = 1,
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    query = db.query(Complaint)
    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Complaint.title.ilike(search_term),
                Complaint.reference_number.ilike(search_term),
                Complaint.location.ilike(search_term),
                Complaint.description.ilike(search_term)
            )
        )
    if status:
        query = query.filter(Complaint.status == status)
    if category:
        query = query.filter(Complaint.category == category)
    if priority:
        query = query.filter(Complaint.priority == priority)
    if department_id:
        query = query.filter(Complaint.assigned_department_id == department_id)

    total_matching = query.count()
    limit = 12
    offset = (max(1, page) - 1) * limit
    total_pages = max(1, (total_matching + limit - 1) // limit)
    
    complaints = query.order_by(desc(Complaint.created_at)).offset(offset).limit(limit).all()
    departments = db.query(Department).all()

    context = get_template_context(
        request, user, db, active_page="complaint_management",
        complaints=complaints,
        departments=departments,
        search=search,
        status=status,
        category=category,
        priority=priority,
        department_id=department_id,
        current_page=page,
        total_pages=total_pages,
        total_matching=total_matching
    )
    return render_template(request, "complaint_management.html", context)

@router.get("/admin/complaints/{complaint_id}")
def admin_complaint_detail_redirect(complaint_id: int):
    return RedirectResponse(url=f"/complaints/{complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/complaints/{complaint_id}/assign")
def admin_assign_department(
    complaint_id: int,
    request: Request,
    department_id: int = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    department = db.query(Department).filter(Department.id == department_id).first()
    if not complaint or not department:
        raise HTTPException(status_code=404, detail="Complaint or Department not found")

    complaint.assigned_department_id = department.id
    if complaint.status in ["Submitted", "AI Analysis"]:
        complaint.status = "Assigned"

    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=complaint.status,
        to_status=complaint.status,
        change_reason=f"Department assigned to {department.name} by {user.full_name}. Notes: {notes or 'Direct officer dispatch'}"
    )
    db.add(history)

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Department Assigned",
        message=f"Complaint #{complaint.reference_number} assigned to {department.name}.",
        notification_type="assignment"
    )

    audit = AuditLog(
        user_id=user.id,
        action="ASSIGN_DEPARTMENT",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"Assigned to {department.name}"
    )
    db.add(audit)
    db.commit()

    referer = request.headers.get("referer") or f"/complaints/{complaint_id}"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/complaints/{complaint_id}/priority")
def admin_update_priority(
    complaint_id: int,
    request: Request,
    priority: str = Form(...),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    prev_prio = complaint.priority
    complaint.priority = priority

    sla_hours = {"Critical": 12, "High": 24, "Medium": 48, "Low": 72}.get(priority, 48)
    complaint.expected_resolution_at = utcnow() + timedelta(hours=sla_hours)

    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=complaint.status,
        to_status=complaint.status,
        change_reason=f"Priority updated from {prev_prio} to {priority} by {user.full_name}. Reason: {reason or 'Administrative assessment'}"
    )
    db.add(history)

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title="Priority Calibrated",
        message=f"Priority updated to {priority} ({sla_hours}h SLA commitment).",
        notification_type="priority"
    )

    audit = AuditLog(
        user_id=user.id,
        action="UPDATE_PRIORITY",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"Priority changed from {prev_prio} to {priority}"
    )
    db.add(audit)
    db.commit()

    referer = request.headers.get("referer") or f"/complaints/{complaint_id}"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/complaints/{complaint_id}/status")
def admin_update_status(
    complaint_id: int,
    request: Request,
    status: str = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    prev_status = complaint.status
    complaint.status = status

    if status in ["Resolved", "Verified", "Closed"] and not complaint.resolved_at:
        complaint.resolved_at = utcnow()

    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        from_status=prev_status,
        to_status=status,
        change_reason=f"Status changed by {user.full_name}. Notes: {notes or 'Operational progression'}"
    )
    db.add(history)

    create_notification(
        db=db,
        user_id=complaint.citizen_id,
        complaint_id=complaint.id,
        title=f"Status: {status}",
        message=f"Your complaint #{complaint.reference_number} is now marked as {status}.",
        notification_type="status_change"
    )

    audit = AuditLog(
        user_id=user.id,
        action="UPDATE_STATUS",
        entity_type="Complaint",
        entity_id=complaint.id,
        details=f"Status changed from {prev_status} to {status}"
    )
    db.add(audit)
    db.commit()

    referer = request.headers.get("referer") or f"/complaints/{complaint_id}"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/complaints/{complaint_id}/review-duplicate")
def admin_review_duplicate(
    complaint_id: int,
    request: Request,
    candidate_id: int = Form(...),
    action: str = Form(...),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    candidate = db.query(DuplicateCandidate).filter(DuplicateCandidate.id == candidate_id).first()
    if candidate:
        if action == "confirm":
            candidate.status = "confirmed"
        elif action == "dismiss":
            candidate.status = "dismissed"
        db.commit()

    return RedirectResponse(url=f"/complaints/{complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

# -------------------------------------------------------------
# AI Operations Center
# -------------------------------------------------------------

@router.get("/admin/ai-operations", response_class=HTMLResponse)
def ai_operations_page(
    request: Request,
    inspect_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    all_executions = db.query(AgentExecution).all()

    # Pre-defined 5 autonomous agents
    agent_configs = [
        {
            "name": "Complaint Classifier",
            "purpose": "NLP categorization, keyword extraction, and clarity triage.",
            "keys": ["Complaint Classifier", "complaint_classifier"]
        },
        {
            "name": "Duplicate Detector",
            "purpose": "Text similarity and GPS proximity matching across database records.",
            "keys": ["Duplicate Detector", "duplicate_detector"]
        },
        {
            "name": "Department Router",
            "purpose": "Responsible department routing based on civic jurisdiction rules.",
            "keys": ["Department Router", "department_router"]
        },
        {
            "name": "Priority Assessor",
            "purpose": "Urgency, public hazard assessment, and SLA deadline calculation.",
            "keys": ["Priority Assessor", "priority_assessor"]
        },
        {
            "name": "Resolution Verifier",
            "purpose": "Officer field note analysis and photographic completion audit.",
            "keys": ["Resolution Verifier", "resolution_verifier"]
        }
    ]

    agent_cards = []
    for cfg in agent_configs:
        matches = [e for e in all_executions if e.agent_name in cfg["keys"]]
        total = len(matches)
        success = sum(1 for e in matches if e.status == "success")
        failed = sum(1 for e in matches if e.status == "failed")
        
        latest_match = max(matches, key=lambda x: make_aware(x.completed_at) or make_aware(x.started_at)) if matches else None
        latest_output = latest_match.output_summary if latest_match else "Awaiting next pipeline trigger"

        agent_cards.append({
            "agent_name": cfg["name"],
            "purpose": cfg["purpose"],
            "status": "Operational",
            "processed_count": total,
            "success_count": success,
            "failed_count": failed,
            "latest_output_summary": latest_output
        })

    recent_complaints = db.query(Complaint).order_by(desc(Complaint.created_at)).limit(10).all()
    selected_complaint = None
    selected_trace = []

    if inspect_id:
        selected_complaint = db.query(Complaint).filter(Complaint.id == inspect_id).first()
    elif recent_complaints:
        selected_complaint = recent_complaints[0]

    if selected_complaint:
        selected_trace = db.query(AgentExecution).filter(
            AgentExecution.complaint_id == selected_complaint.id
        ).order_by(AgentExecution.started_at.asc()).all()

    context = get_template_context(
        request, user, db, active_page="ai_operations",
        agents=agent_cards,
        recent_complaints=recent_complaints,
        selected_complaint=selected_complaint,
        selected_trace=selected_trace
    )
    return render_template(request, "ai_operations.html", context)

@router.post("/admin/ai-operations/{complaint_id}/retry")
def retry_ai_operations(complaint_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        process_complaint_pipeline(db, complaint_id)
    except Exception as e:
        print(f"Retry error for #{complaint_id}: {e}")

    return RedirectResponse(url=f"/admin/ai-operations?inspect_id={complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

# -------------------------------------------------------------
# Department Management
# -------------------------------------------------------------

@router.get("/admin/departments", response_class=HTMLResponse)
def departments_page(request: Request, message: Optional[str] = None, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    departments = db.query(Department).all()
    all_complaints = db.query(Complaint).all()

    # Calculate workload for each department
    for d in departments:
        assigned = [c for c in all_complaints if c.assigned_department_id == d.id]
        d.total_assigned = len(assigned)
        d.resolved_cases = sum(1 for c in assigned if c.status in ["Resolved", "Verified", "Closed"])
        d.pending_workload = d.total_assigned - d.resolved_cases

    context = get_template_context(
        request, user, db, active_page="departments",
        departments=departments,
        message=message
    )
    return render_template(request, "departments.html", context)

@router.post("/admin/departments")
def create_department(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    description: Optional[str] = Form(None),
    sla_hours: int = Form(48),
    contact_email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    dept = Department(
        name=name.strip(),
        code=code.strip().upper(),
        description=description.strip() if description else None,
        sla_hours=sla_hours,
        contact_email=contact_email.strip() if contact_email else None
    )
    db.add(dept)
    db.commit()

    return RedirectResponse(url="/admin/departments", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/admin/departments/{department_id}/update")
def update_department(
    department_id: int,
    request: Request,
    sla_hours: int = Form(...),
    contact_email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    dept = db.query(Department).filter(Department.id == department_id).first()
    if dept:
        dept.sla_hours = sla_hours
        if contact_email:
            dept.contact_email = contact_email.strip()
        db.commit()

    return RedirectResponse(url="/admin/departments", status_code=status.HTTP_303_SEE_OTHER)

# -------------------------------------------------------------
# Resolution Verification
# -------------------------------------------------------------

@router.get("/admin/verification", response_class=HTMLResponse)
def resolution_verification_page(
    request: Request,
    complaint_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    pending_complaints = db.query(Complaint).filter(
        Complaint.status.in_(["Assigned", "In Progress", "Reopened"])
    ).order_by(desc(Complaint.created_at)).all()

    recent_verifications = db.query(ResolutionVerification).order_by(
        desc(ResolutionVerification.verified_at)
    ).limit(10).all()

    verification_result = None
    if complaint_id:
        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if complaint and complaint.resolution_verification:
            v = complaint.resolution_verification
            checks = {}
            if v.checks_performed:
                try:
                    checks = json.loads(v.checks_performed)
                except Exception:
                    checks = {}
            verification_result = {
                "outcome": v.outcome,
                "confidence_score": v.confidence_score,
                "verification_summary": v.verification_summary,
                "checks": checks
            }

    context = get_template_context(
        request, user, db, active_page="verification",
        pending_complaints=pending_complaints,
        recent_verifications=recent_verifications,
        verification_result=verification_result
    )
    return render_template(request, "resolution_verification.html", context)

@router.post("/admin/verification")
async def handle_resolution_verification(
    request: Request,
    complaint_id: int = Form(...),
    completion_notes: str = Form(...),
    supporting_details: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_request(request, db)
    if not user or user.role not in ["admin", "officer"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    photo_url = None
    if file and file.filename:
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp"]:
            saved_filename = f"RES_{complaint.reference_number}_{uuid.uuid4().hex[:6]}{ext}"
            saved_path = os.path.join(settings.UPLOAD_DIR, saved_filename)
            content = await file.read()
            with open(saved_path, "wb") as f:
                f.write(content)
            photo_url = f"/uploads/{saved_filename}"

    # Remove prior evidence if re-submitting
    existing_evidence = db.query(ResolutionEvidence).filter(ResolutionEvidence.complaint_id == complaint_id).first()
    if existing_evidence:
        db.delete(existing_evidence)
        db.commit()

    evidence = ResolutionEvidence(
        complaint_id=complaint_id,
        officer_id=user.id,
        completion_notes=completion_notes.strip(),
        photo_url=photo_url,
        supporting_details=supporting_details.strip() if supporting_details else None
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    # Run Agent 5: Resolution Verifier
    verification = verify_complaint_resolution(db, complaint, evidence)

    return RedirectResponse(url=f"/admin/verification?complaint_id={complaint_id}", status_code=status.HTTP_303_SEE_OTHER)

# -------------------------------------------------------------
# Notifications & Activity Center (Page 11)
# -------------------------------------------------------------

@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    notifications = db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(desc(Notification.created_at)).all()

    unread_count = sum(1 for n in notifications if not n.is_read)

    audit_logs = []
    if user.role in ["admin", "officer"]:
        audit_logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(20).all()
    else:
        # Show audit actions on citizen's complaints
        citizen_complaint_ids = [c.id for c in db.query(Complaint.id).filter(Complaint.citizen_id == user.id).all()]
        audit_logs = db.query(AuditLog).filter(
            AuditLog.entity_type == "Complaint",
            AuditLog.entity_id.in_(citizen_complaint_ids)
        ).order_by(desc(AuditLog.created_at)).limit(15).all()

    context = get_template_context(
        request, user, db, active_page="notifications",
        notifications=notifications,
        unread_count=unread_count,
        audit_logs=audit_logs
    )
    return render_template(request, "notifications.html", context)

@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    notif = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == user.id).first()
    if notif:
        notif.is_read = True
        db.commit()

    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/notifications/read-all")
def mark_all_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()

    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)
