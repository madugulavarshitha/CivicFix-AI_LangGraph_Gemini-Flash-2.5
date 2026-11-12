from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON, func
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="citizen")  # citizen, officer, admin
    phone = Column(String(30), nullable=True)
    locality = Column(String(150), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    department = relationship("Department", back_populates="officers")
    complaints = relationship("Complaint", back_populates="citizen", foreign_keys="Complaint.citizen_id")
    comments = relationship("ComplaintComment", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    contact_email = Column(String(255), nullable=False)
    sla_hours = Column(Integer, default=48)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    officers = relationship("User", back_populates="department")
    complaints = relationship("Complaint", back_populates="assigned_department")


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    reference_number = Column(String(50), unique=True, index=True, nullable=False)
    citizen_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False, default="Other")
    location = Column(String(255), nullable=False)
    landmark = Column(String(255), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    contact_phone = Column(String(30), nullable=True)
    
    priority = Column(String(50), nullable=False, default="Medium")  # Low, Medium, High, Critical
    status = Column(String(50), nullable=False, default="Submitted")
    # Statuses: Submitted, AI Analysis, Assigned, In Progress, Resolved, Verified, Closed, Reopened, Rejected

    assigned_department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    
    ai_summary = Column(Text, nullable=True)
    classification_confidence = Column(Float, nullable=True)
    
    duplicate_of_id = Column(Integer, ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True)
    is_potential_duplicate = Column(Boolean, default=False)
    duplicate_score = Column(Float, nullable=True)
    
    rejection_reason = Column(Text, nullable=True)
    reopen_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expected_resolution_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    citizen = relationship("User", back_populates="complaints", foreign_keys=[citizen_id])
    assigned_department = relationship("Department", back_populates="complaints")
    attachments = relationship("ComplaintAttachment", back_populates="complaint", cascade="all, delete-orphan")
    comments = relationship("ComplaintComment", back_populates="complaint", cascade="all, delete-orphan")
    status_history = relationship("ComplaintStatusHistory", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintStatusHistory.created_at.desc()")
    duplicate_candidates = relationship("DuplicateCandidate", back_populates="primary_complaint", foreign_keys="DuplicateCandidate.primary_complaint_id", cascade="all, delete-orphan")
    agent_executions = relationship("AgentExecution", back_populates="complaint", cascade="all, delete-orphan", order_by="AgentExecution.started_at.desc()")
    resolution_evidence = relationship("ResolutionEvidence", back_populates="complaint", uselist=False, cascade="all, delete-orphan")
    resolution_verifications = relationship("ResolutionVerification", back_populates="complaint", cascade="all, delete-orphan", order_by="ResolutionVerification.verified_at.desc()")


class ComplaintAttachment(Base):
    __tablename__ = "complaint_attachments"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    attachment_type = Column(String(50), default="initial")  # initial, evidence, general
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="attachments")


class ComplaintComment(Base):
    __tablename__ = "complaint_comments"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment_text = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="comments")
    user = relationship("User", back_populates="comments")


class ComplaintStatusHistory(Base):
    __tablename__ = "complaint_status_history"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = Column(String(50), nullable=True)
    to_status = Column(String(50), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="status_history")
    changed_by = relationship("User")


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"

    id = Column(Integer, primary_key=True, index=True)
    primary_complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score = Column(Float, nullable=False)
    geo_distance_meters = Column(Float, nullable=True)
    match_reason = Column(Text, nullable=False)
    status = Column(String(50), default="pending")  # pending, confirmed, dismissed
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    primary_complaint = relationship("Complaint", back_populates="duplicate_candidates", foreign_keys=[primary_complaint_id])
    candidate_complaint = relationship("Complaint", foreign_keys=[candidate_complaint_id])


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)  # success, failed, needs_review
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="agent_executions")


class ResolutionEvidence(Base):
    __tablename__ = "resolution_evidence"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    officer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    completion_notes = Column(Text, nullable=False)
    photo_url = Column(String(500), nullable=True)
    resolution_timestamp = Column(DateTime(timezone=True), default=utcnow)
    supporting_details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="resolution_evidence")
    officer = relationship("User")


class ResolutionVerification(Base):
    __tablename__ = "resolution_verifications"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    outcome = Column(String(50), nullable=False)  # Verified, Needs Review, Rejected
    confidence_score = Column(Float, nullable=False)
    checks_performed = Column(Text, nullable=True)  # JSON serialized dictionary of checks
    verification_summary = Column(Text, nullable=False)
    verified_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    complaint = relationship("Complaint", back_populates="resolution_verifications")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50), nullable=False)  # status_change, assignment, duplicate, priority, verification, comment
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    user = relationship("User", back_populates="notifications")
    complaint = relationship("Complaint")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    user = relationship("User")
