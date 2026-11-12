from datetime import datetime, timezone, timedelta
import json
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, Base, engine
from app.core.security import get_password_hash
from app.models.entities import (
    User,
    Department,
    Complaint,
    ComplaintStatusHistory,
    AgentExecution,
    DuplicateCandidate,
    ResolutionEvidence,
    ResolutionVerification,
    ComplaintComment,
    Notification,
)

def utcnow():
    return datetime.now(timezone.utc)

def seed_database():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    
    try:
        # Check if already seeded
        if db.query(User).filter(User.email == "admin@civicfix.gov").first():
            print("Database already contains seed data. Skipping.")
            return

        print("Seeding CivicFix AI database...")

        # 1. Departments
        departments_data = [
            {
                "name": "Roads and Infrastructure",
                "code": "ROADS",
                "description": "Responsible for road resurfacing, pothole repairs, bridges, footpaths, and traffic infrastructure.",
                "contact_email": "roads@civicfix.gov",
                "sla_hours": 48
            },
            {
                "name": "Sanitation",
                "code": "SANITATION",
                "description": "Solid waste management, garbage collection bins, street sweeping, and public hygiene.",
                "contact_email": "sanitation@civicfix.gov",
                "sla_hours": 24
            },
            {
                "name": "Electrical Services",
                "code": "ELECTRICAL",
                "description": "Streetlight maintenance, municipal electrical poles, transformers, and public area lighting.",
                "contact_email": "electrical@civicfix.gov",
                "sla_hours": 24
            },
            {
                "name": "Water Supply",
                "code": "WATER",
                "description": "Drinking water pipelines, distribution network maintenance, water pressure, and leak fixes.",
                "contact_email": "water@civicfix.gov",
                "sla_hours": 36
            },
            {
                "name": "Drainage and Sewerage",
                "code": "DRAINAGE",
                "description": "Stormwater drains, sewer lines, manhole covers, flood mitigation, and wastewater.",
                "contact_email": "drainage@civicfix.gov",
                "sla_hours": 48
            },
            {
                "name": "Public Safety",
                "code": "SAFETY",
                "description": "Urgent civic hazards, exposed high-voltage cables, structural collapse risks, and emergency hazards.",
                "contact_email": "safety@civicfix.gov",
                "sla_hours": 12
            },
            {
                "name": "General Municipal Services",
                "code": "GENERAL",
                "description": "Parks, municipal properties, civic amenities, and uncategorized public grievances.",
                "contact_email": "general@civicfix.gov",
                "sla_hours": 72
            }
        ]

        depts = {}
        for d_info in departments_data:
            dept = Department(**d_info)
            db.add(dept)
            db.flush()
            depts[dept.code] = dept

        # 2. Users
        # Admin
        admin_user = User(
            full_name="Chief Municipal Officer (Admin)",
            email="admin@civicfix.gov",
            password_hash=get_password_hash("Admin@12345"),
            role="admin",
            phone="+1-800-555-0199"
        )
        db.add(admin_user)

        # Officers
        officer_roads = User(
            full_name="Rajesh Kumar (Roads Lead)",
            email="officer.roads@civicfix.gov",
            password_hash=get_password_hash("Officer@12345"),
            role="officer",
            phone="+1-800-555-0101",
            department_id=depts["ROADS"].id
        )
        officer_water = User(
            full_name="Elena Rostova (Water Inspector)",
            email="officer.water@civicfix.gov",
            password_hash=get_password_hash("Officer@12345"),
            role="officer",
            phone="+1-800-555-0102",
            department_id=depts["WATER"].id
        )
        db.add(officer_roads)
        db.add(officer_water)

        # Citizens
        citizen_1 = User(
            full_name="Alex Mercer (Citizen)",
            email="citizen@civicfix.gov",
            password_hash=get_password_hash("Citizen@12345"),
            role="citizen",
            phone="+1-555-014-2390"
        )
        citizen_2 = User(
            full_name="Priya Sharma (Citizen)",
            email="jane.citizen@example.com",
            password_hash=get_password_hash("Citizen@12345"),
            role="citizen",
            phone="+1-555-018-9921"
        )
        db.add(citizen_1)
        db.add(citizen_2)
        db.flush()

        # 3. Realistic Pre-seeded Complaints
        now = utcnow()
        
        # Complaint 1: Deep Pothole (In Progress, High Priority)
        c1 = Complaint(
            reference_number="CF-2026-1001",
            citizen_id=citizen_1.id,
            title="Dangerous deep pothole on 5th Cross Road",
            description="There is a severe crater-like pothole right in front of Green Grocery on 5th Cross Road. Two two-wheelers skidded yesterday evening.",
            category="Road Damage",
            location="5th Cross Road, Sector 4",
            landmark="Opposite Green Grocery",
            latitude=12.9716,
            longitude=77.5946,
            priority="Critical",
            status="In Progress",
            assigned_department_id=depts["ROADS"].id,
            ai_summary="Road Damage: Dangerous deep pothole on 5th Cross Road posing immediate vehicular skid hazard.",
            classification_confidence=0.94,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=5),
            expected_resolution_at=now + timedelta(hours=12)
        )
        db.add(c1)
        db.flush()

        # Status history for C1
        db.add(ComplaintStatusHistory(
            complaint_id=c1.id,
            from_status="Submitted",
            to_status="AI Analysis",
            change_reason="Complaint received and queued for LangGraph AI triage.",
            created_at=now - timedelta(days=2)
        ))
        db.add(ComplaintStatusHistory(
            complaint_id=c1.id,
            from_status="AI Analysis",
            to_status="Assigned",
            change_reason="AI Classifier identified Road Damage (0.94 conf); Priority Assessor elevated to Critical; routed to Roads and Infrastructure.",
            created_at=now - timedelta(days=2, hours=-1)
        ))
        db.add(ComplaintStatusHistory(
            complaint_id=c1.id,
            from_status="Assigned",
            to_status="In Progress",
            changed_by_id=officer_roads.id,
            change_reason="Road repair crew dispatched with cold-mix asphalt.",
            created_at=now - timedelta(hours=10)
        ))

        # Agent executions for C1
        db.add(AgentExecution(
            complaint_id=c1.id,
            agent_name="Complaint Classifier",
            status="success",
            input_summary="Title: Dangerous deep pothole | Desc: crater-like pothole",
            output_summary=json.dumps({"category": "Road Damage", "confidence": 0.94, "summary": "Dangerous deep pothole on 5th Cross Road."}),
            confidence=0.94,
            started_at=now - timedelta(days=2),
            completed_at=now - timedelta(days=2)
        ))
        db.add(AgentExecution(
            complaint_id=c1.id,
            agent_name="Duplicate Detector",
            status="success",
            input_summary="Compared against active complaints",
            output_summary=json.dumps({"is_duplicate": False, "candidate_count": 0}),
            confidence=0.88,
            started_at=now - timedelta(days=2),
            completed_at=now - timedelta(days=2)
        ))
        db.add(AgentExecution(
            complaint_id=c1.id,
            agent_name="Department Router",
            status="success",
            input_summary="Category: Road Damage",
            output_summary=json.dumps({"department": "Roads and Infrastructure", "code": "ROADS"}),
            confidence=0.95,
            started_at=now - timedelta(days=2),
            completed_at=now - timedelta(days=2)
        ))
        db.add(AgentExecution(
            complaint_id=c1.id,
            agent_name="Priority Assessor",
            status="success",
            input_summary="Category: Road Damage | Hazard keywords: skidded, danger",
            output_summary=json.dumps({"priority": "Critical", "urgency_hours": 12, "justification": "Vehicular safety risk identified."}),
            confidence=0.92,
            started_at=now - timedelta(days=2),
            completed_at=now - timedelta(days=2)
        ))

        # Complaint 2: Water Leakage (Assigned)
        c2 = Complaint(
            reference_number="CF-2026-1002",
            citizen_id=citizen_2.id,
            title="Clean drinking water pipeline leaking heavily onto street",
            description="Underground pipe burst near the junction. Clean water has been gushing out for 4 hours, causing water loss and local street flooding.",
            category="Water Leakage",
            location="Corner of 12th Main and 8th Avenue",
            landmark="Near Metro Pillar 142",
            latitude=12.9730,
            longitude=77.5980,
            priority="High",
            status="Assigned",
            assigned_department_id=depts["WATER"].id,
            ai_summary="Water Leakage: High-volume pipeline burst causing drinking water loss and street flooding.",
            classification_confidence=0.92,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
            expected_resolution_at=now + timedelta(hours=24)
        )
        db.add(c2)
        db.flush()

        # Complaint 3: Garbage and Sanitation (Resolved with Evidence + Verification!)
        c3 = Complaint(
            reference_number="CF-2026-1003",
            citizen_id=citizen_1.id,
            title="Overflowing community waste bin creating foul odor",
            description="The large metal dumpster has not been emptied for 5 days. Garbage is spilling across the sidewalk creating severe stench and attracting stray animals.",
            category="Garbage and Sanitation",
            location="Rose Garden Park South Gate",
            landmark="Opposite Community Library",
            latitude=12.9680,
            longitude=77.5900,
            priority="Medium",
            status="Verified",
            assigned_department_id=depts["SANITATION"].id,
            ai_summary="Garbage and Sanitation: Overflowing bin on sidewalk causing foul odor.",
            classification_confidence=0.96,
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=1),
            resolved_at=now - timedelta(days=1, hours=2),
            verified_at=now - timedelta(days=1),
            expected_resolution_at=now - timedelta(days=3)
        )
        db.add(c3)
        db.flush()

        # Evidence & Verification for C3
        c3_evidence = ResolutionEvidence(
            complaint_id=c3.id,
            officer_id=officer_roads.id,
            completion_notes="Sanitation truck #14 cleared the overflowing bin. Sidewalk was swept, disinfected, and an additional secondary bin was installed to handle weekend peak volume.",
            photo_url="/uploads/demo_garbage_resolved.jpg",
            resolution_timestamp=now - timedelta(days=1, hours=2),
            supporting_details="Disinfection log reference #SAN-8821"
        )
        db.add(c3_evidence)
        db.flush()

        c3_verif = ResolutionVerification(
            complaint_id=c3.id,
            outcome="Verified",
            confidence_score=0.95,
            checks_performed=json.dumps({
                "adequate_notes_length": True,
                "action_resolution_keywords": True,
                "actions_identified": ["cleared", "swept", "disinfected", "installed"],
                "relevancy_to_original_issue": True,
                "visual_evidence_attached": True
            }),
            verification_summary="Valid resolution evidence verified. Corrective actions directly address reported garbage overflow with photo confirmation.",
            verified_at=now - timedelta(days=1)
        )
        db.add(c3_verif)

        # Agent 5 execution record for C3
        db.add(AgentExecution(
            complaint_id=c3.id,
            agent_name="Resolution Verifier",
            status="success",
            input_summary="Completion notes: Sanitation truck #14 cleared overflowing bin | Photo attached: True",
            output_summary=json.dumps({"outcome": "Verified", "confidence": 0.95, "summary": "Valid resolution evidence verified."}),
            confidence=0.95,
            started_at=now - timedelta(days=1),
            completed_at=now - timedelta(days=1)
        ))

        # Complaint 4: Potential Duplicate of Complaint 1!
        c4 = Complaint(
            reference_number="CF-2026-1004",
            citizen_id=citizen_2.id,
            title="Huge pothole right outside grocery store on 5th cross",
            description="Deep crater in the road right in front of Green Grocery on 5th cross road. Extremely hazardous for motorists.",
            category="Road Damage",
            location="5th Cross Road, near grocery shop",
            latitude=12.9718,
            longitude=77.5948,
            priority="Critical",
            status="Assigned",
            assigned_department_id=depts["ROADS"].id,
            ai_summary="Road Damage: Hazardous pothole near grocery shop.",
            classification_confidence=0.93,
            is_potential_duplicate=True,
            duplicate_score=0.86,
            created_at=now - timedelta(hours=8),
            updated_at=now - timedelta(hours=8)
        )
        db.add(c4)
        db.flush()

        # Duplicate candidate relationship linking C4 to C1
        db.add(DuplicateCandidate(
            primary_complaint_id=c4.id,
            candidate_complaint_id=c1.id,
            similarity_score=0.86,
            geo_distance_meters=28.4,
            match_reason="Matching category 'Road Damage' & 72% descriptive term overlap & Within 28m geographic radius of CF-2026-1001",
            status="pending"
        ))

        # Complaint 5: Streetlight Failure (Submitted)
        c5 = Complaint(
            reference_number="CF-2026-1005",
            citizen_id=citizen_1.id,
            title="Three consecutive streetlights dark along Lakeview Boulevard",
            description="The street lights between poles 18 and 21 are completely dead. The road is pitch dark at night, making it unsafe for pedestrians and elderly residents.",
            category="Streetlight Failure",
            location="Lakeview Boulevard, Sector 2",
            landmark="Opposite Sunset Lake Gate 2",
            latitude=12.9650,
            longitude=77.6010,
            priority="Medium",
            status="Submitted",
            assigned_department_id=depts["ELECTRICAL"].id,
            ai_summary="Streetlight Failure: Three consecutive dead street lamps causing pedestrian safety concerns.",
            classification_confidence=0.91,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=3),
            expected_resolution_at=now + timedelta(hours=24)
        )
        db.add(c5)

        # Comments
        db.add(ComplaintComment(
            complaint_id=c1.id,
            user_id=citizen_1.id,
            comment_text="Please hurry, another motorcycle almost fell this morning.",
            is_internal=False,
            created_at=now - timedelta(days=1)
        ))
        db.add(ComplaintComment(
            complaint_id=c1.id,
            user_id=officer_roads.id,
            comment_text="Internal dispatch: Team B assigned with truck #07. Work scheduled for completion today.",
            is_internal=True,
            created_at=now - timedelta(hours=9)
        ))

        # Notifications
        db.add(Notification(
            user_id=citizen_1.id,
            complaint_id=c1.id,
            title="Complaint Assigned & In Progress",
            message="Your complaint CF-2026-1001 has been prioritized as Critical and is currently In Progress by Roads and Infrastructure.",
            notification_type="status_change",
            is_read=False,
            created_at=now - timedelta(hours=9)
        ))
        db.add(Notification(
            user_id=citizen_1.id,
            complaint_id=c3.id,
            title="Complaint Verified and Resolved",
            message="Your complaint CF-2026-1003 has been verified as resolved. Work completed on sidewalk bin.",
            notification_type="verification",
            is_read=True,
            created_at=now - timedelta(days=1)
        ))
        db.add(Notification(
            user_id=citizen_2.id,
            complaint_id=c4.id,
            title="Potential Similar Complaint Detected",
            message="Our AI detected that your report on 5th Cross Road matches an existing open issue CF-2026-1001.",
            notification_type="duplicate",
            is_read=False,
            created_at=now - timedelta(hours=8)
        ))

        db.commit()
        print("CivicFix AI seed data created successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
