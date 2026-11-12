from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

# ----------------- AUTH SCHEMAS -----------------
class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)
    role: Optional[str] = "citizen"  # Only citizen allowed for public registration
    department_id: Optional[int] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(UserBase):
    id: int
    role: str
    department_id: Optional[int] = None
    created_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[str] = None


# ----------------- DEPARTMENT SCHEMAS -----------------
class DepartmentBase(BaseModel):
    name: str
    code: str
    description: str
    contact_email: EmailStr
    sla_hours: int = 48
    active: bool = True

class DepartmentCreate(DepartmentBase):
    pass

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    sla_hours: Optional[int] = None
    active: Optional[bool] = None

class DepartmentResponse(DepartmentBase):
    id: int
    created_at: datetime
    total_assigned: Optional[int] = 0
    pending_workload: Optional[int] = 0
    resolved_cases: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)


# ----------------- ATTACHMENT SCHEMAS -----------------
class AttachmentResponse(BaseModel):
    id: int
    complaint_id: int
    file_name: str
    file_path: str
    file_type: str
    file_size: int
    attachment_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- COMMENT SCHEMAS -----------------
class CommentCreate(BaseModel):
    comment_text: str = Field(..., min_length=2)
    is_internal: bool = False

class CommentResponse(BaseModel):
    id: int
    complaint_id: int
    user_id: int
    user_name: Optional[str] = None
    user_role: Optional[str] = None
    comment_text: str
    is_internal: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- STATUS HISTORY SCHEMAS -----------------
class StatusHistoryResponse(BaseModel):
    id: int
    complaint_id: int
    from_status: Optional[str] = None
    to_status: str
    change_reason: Optional[str] = None
    changed_by_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- DUPLICATE SCHEMAS -----------------
class DuplicateCandidateResponse(BaseModel):
    id: int
    primary_complaint_id: int
    candidate_complaint_id: int
    candidate_reference: Optional[str] = None
    candidate_title: Optional[str] = None
    similarity_score: float
    geo_distance_meters: Optional[float] = None
    match_reason: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DuplicateReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(confirmed|dismissed)$")
    relink_to_id: Optional[int] = None


# ----------------- AGENT EXECUTION SCHEMAS -----------------
class AgentExecutionResponse(BaseModel):
    id: int
    complaint_id: int
    agent_name: str
    status: str
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AgentCardMetric(BaseModel):
    agent_name: str
    purpose: str
    status: str
    processed_count: int
    success_count: int
    failed_count: int
    last_execution_time: Optional[datetime] = None
    latest_output_summary: Optional[str] = None


# ----------------- RESOLUTION EVIDENCE & VERIFICATION -----------------
class ResolutionEvidenceCreate(BaseModel):
    completion_notes: str = Field(..., min_length=10)
    photo_url: Optional[str] = None
    supporting_details: Optional[str] = None

class ResolutionEvidenceResponse(BaseModel):
    id: int
    complaint_id: int
    officer_id: int
    officer_name: Optional[str] = None
    completion_notes: str
    photo_url: Optional[str] = None
    resolution_timestamp: datetime
    supporting_details: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ResolutionVerificationResponse(BaseModel):
    id: int
    complaint_id: int
    outcome: str  # Verified, Needs Review, Rejected
    confidence_score: float
    checks_performed: Optional[Any] = None
    verification_summary: str
    verified_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- COMPLAINT SCHEMAS -----------------
class ComplaintCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=15)
    category: str = "Other"
    location: str = Field(..., min_length=3)
    landmark: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    contact_phone: Optional[str] = None

class ComplaintUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    landmark: Optional[str] = None

class ComplaintAssignDepartment(BaseModel):
    department_id: int
    notes: Optional[str] = None

class ComplaintSetPriority(BaseModel):
    priority: str = Field(..., pattern="^(Low|Medium|High|Critical)$")
    reason: Optional[str] = None

class ComplaintStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(Submitted|AI Analysis|Assigned|In Progress|Resolved|Verified|Closed|Reopened|Rejected)$")
    reason: Optional[str] = None

class ComplaintReopen(BaseModel):
    reopen_reason: str = Field(..., min_length=10)

class ComplaintReject(BaseModel):
    rejection_reason: str = Field(..., min_length=5)

class ComplaintResponse(BaseModel):
    id: int
    reference_number: str
    citizen_id: int
    citizen_name: Optional[str] = None
    title: str
    description: str
    category: str
    location: str
    landmark: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    priority: str
    status: str
    assigned_department_id: Optional[int] = None
    assigned_department_name: Optional[str] = None
    ai_summary: Optional[str] = None
    classification_confidence: Optional[float] = None
    is_potential_duplicate: bool
    duplicate_of_id: Optional[int] = None
    duplicate_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    expected_resolution_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class ComplaintDetailResponse(ComplaintResponse):
    attachments: List[AttachmentResponse] = []
    comments: List[CommentResponse] = []
    status_history: List[StatusHistoryResponse] = []
    duplicate_candidates: List[DuplicateCandidateResponse] = []
    agent_executions: List[AgentExecutionResponse] = []
    resolution_evidence: Optional[ResolutionEvidenceResponse] = None
    resolution_verifications: List[ResolutionVerificationResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ----------------- NOTIFICATION SCHEMAS -----------------
class NotificationResponse(BaseModel):
    id: int
    user_id: int
    complaint_id: Optional[int] = None
    title: str
    message: str
    notification_type: str
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- ADMIN DASHBOARD STATS -----------------
class AdminDashboardStats(BaseModel):
    total_complaints: int
    unassigned_complaints: int
    high_priority_complaints: int
    overdue_complaints: int
    resolved_complaints: int
    average_resolution_hours: float
    resolution_rate_percent: float
    status_distribution: dict[str, int]
    category_distribution: dict[str, int]
    priority_distribution: dict[str, int]
    trend_by_date: List[dict[str, Any]]
    department_performance: List[dict[str, Any]]
    recent_activity: List[dict[str, Any]]
