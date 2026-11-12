import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.models.entities import User, Department, Complaint, ResolutionEvidence
from app.agents.classifier_agent import classifier_agent
from app.agents.duplicate_agent import duplicate_agent
from app.agents.router_agent import router_agent
from app.agents.priority_agent import priority_agent
from app.agents.verifier_agent import verifier_agent
from app.graph.workflow import run_complaint_workflow

# In-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Seed test department
    dept_roads = Department(
        name="Roads and Infrastructure",
        code="ROADS",
        description="Road repairs",
        contact_email="roads@test.gov",
        sla_hours=48
    )
    dept_sanitation = Department(
        name="Sanitation",
        code="SANITATION",
        description="Waste management",
        contact_email="sanitation@test.gov",
        sla_hours=24
    )
    db.add(dept_roads)
    db.add(dept_sanitation)
    db.flush()

    # Seed test users
    admin = User(
        full_name="Admin Test",
        email="admintest@test.gov",
        password_hash=get_password_hash("Password@123"),
        role="admin"
    )
    officer = User(
        full_name="Officer Test",
        email="officertest@test.gov",
        password_hash=get_password_hash("Password@123"),
        role="officer",
        department_id=dept_roads.id
    )
    citizen1 = User(
        full_name="Citizen One",
        email="citizen1@test.com",
        password_hash=get_password_hash("Password@123"),
        role="citizen"
    )
    citizen2 = User(
        full_name="Citizen Two",
        email="citizen2@test.com",
        password_hash=get_password_hash("Password@123"),
        role="citizen"
    )
    db.add_all([admin, officer, citizen1, citizen2])
    db.commit()
    yield
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

# ----------------- 1. TEST AGENT MODULES -----------------
def test_classifier_agent():
    # Test road damage
    res1 = classifier_agent.execute(
        title="Huge pothole on road",
        description="There is a major deep pothole in the asphalt near the intersection."
    )
    assert res1["status"] == "success"
    assert res1["category"] == "Road Damage"
    assert res1["confidence"] > 0.6

    # Test garbage
    res2 = classifier_agent.execute(
        title="Overflowing trash bin",
        description="The garbage waste is spilling out with foul odor on the sidewalk."
    )
    assert res2["status"] == "success"
    assert res2["category"] == "Garbage and Sanitation"


def test_duplicate_detector_agent():
    new_item = {
        "id": 99,
        "title": "Huge pothole on 5th Cross Road",
        "description": "Crater in the road near the corner shop.",
        "category": "Road Damage",
        "location": "5th Cross Road",
        "latitude": 12.9716,
        "longitude": 77.5946
    }
    existing = [
        {
            "id": 1,
            "reference_number": "CF-2026-0001",
            "title": "Deep pothole on 5th Cross Road",
            "description": "Deep hole in the road near corner bakery.",
            "category": "Road Damage",
            "location": "5th Cross Road",
            "latitude": 12.9717,
            "longitude": 77.5947
        },
        {
            "id": 2,
            "reference_number": "CF-2026-0002",
            "title": "Streetlight broken on North Street",
            "description": "Dark lamp pole.",
            "category": "Streetlight Failure",
            "location": "North Street",
            "latitude": 13.1000,
            "longitude": 78.0000
        }
    ]
    res = duplicate_agent.execute(new_complaint=new_item, existing_complaints=existing)
    assert res["status"] == "success"
    assert res["is_potential_duplicate"] is True
    assert res["candidate_count"] == 1
    assert res["candidates"][0]["candidate_complaint_id"] == 1


def test_department_router_agent():
    depts = [
        {"id": 1, "name": "Roads and Infrastructure", "code": "ROADS"},
        {"id": 2, "name": "Sanitation", "code": "SANITATION"}
    ]
    res = router_agent.execute(category="Road Damage", entities={}, departments=depts)
    assert res["status"] == "success"
    assert res["department_code"] == "ROADS"
    assert res["department_id"] == 1


def test_priority_assessor_agent():
    # Critical trigger: live wire
    res_crit = priority_agent.execute(
        title="Live wire hanging down",
        description="There is an exposed live wire sparking near school gate.",
        category="Public Safety"
    )
    assert res_crit["status"] == "success"
    assert res_crit["priority"] == "Critical"
    assert res_crit["urgency_hours"] <= 12

    # Medium normal issue
    res_med = priority_agent.execute(
        title="Broken road divider",
        description="Concrete curb needs repainting.",
        category="Road Damage"
    )
    assert res_med["priority"] == "Medium"


def test_resolution_verifier_agent():
    # Valid completion
    res_valid = verifier_agent.execute(
        complaint_title="Pothole repair needed",
        complaint_description="Deep hole on street",
        complaint_category="Road Damage",
        completion_notes="Work crew patched the pothole with asphalt and leveled the road surface completely.",
        has_photo=True
    )
    assert res_valid["status"] == "success"
    assert res_valid["outcome"] == "Verified"

    # Missing photo -> Needs Review
    res_no_photo = verifier_agent.execute(
        complaint_title="Pothole repair needed",
        complaint_description="Deep hole on street",
        complaint_category="Road Damage",
        completion_notes="Work crew patched the pothole with asphalt.",
        has_photo=False
    )
    assert res_no_photo["outcome"] == "Needs Review"

    # Too short / vague -> Rejected
    res_vague = verifier_agent.execute(
        complaint_title="Pothole repair needed",
        complaint_description="Deep hole on street",
        complaint_category="Road Damage",
        completion_notes="done",
        has_photo=False
    )
    assert res_vague["outcome"] == "Rejected"


# ----------------- 2. TEST LANGGRAPH WORKFLOW -----------------
def test_langgraph_full_workflow():
    complaint_dict = {
        "id": 10,
        "title": "Severe pothole causing tire damage",
        "description": "Large road hole in the street, needs asphalt patching urgently.",
        "category": "Road Damage",
        "location": "Main Boulevard",
        "latitude": 12.97,
        "longitude": 77.59
    }
    depts = [
        {"id": 1, "name": "Roads and Infrastructure", "code": "ROADS", "sla_hours": 48}
    ]
    result = run_complaint_workflow(complaint_dict=complaint_dict, existing_complaints=[], departments=depts)
    
    assert "classification" in result
    assert result["classification"]["category"] == "Road Damage"
    assert "routing" in result
    assert result["routing"]["department_code"] == "ROADS"
    assert len(result["agent_logs"]) == 4  # Classifier, Duplicate, Router, Priority


# ----------------- 3. TEST AUTH & ACCESS CONTROL -----------------
def test_auth_login():
    # Citizen login
    res = client.post("/api/auth/login", json={"email": "citizen1@test.com", "password": "Password@123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["role"] == "citizen"

    # Invalid login
    res_bad = client.post("/api/auth/login", json={"email": "citizen1@test.com", "password": "WrongPassword"})
    assert res_bad.status_code == 401


def test_auth_register_defaults_to_citizen():
    # Ensure cannot register as admin
    res = client.post("/api/auth/register", json={
        "full_name": "Hacker Attempt",
        "email": "hacker@test.com",
        "password": "Password@123",
        "role": "admin"
    })
    assert res.status_code == 201
    data = res.json()
    assert data["user"]["role"] == "citizen"  # Strictly forced to citizen


# ----------------- 4. TEST COMPLAINT CREATION & CITIZEN ISOLATION -----------------
def test_complaint_lifecycle_and_rbac():
    # 1. Citizen 1 submits complaint
    token_c1 = create_access_token(subject=3, role="citizen")
    headers_c1 = {"Authorization": f"Bearer {token_c1}"}
    
    payload = {
        "title": "Broken road asphalt outside market",
        "description": "There is a massive pothole in front of supermarket on Main Street.",
        "category": "Road Damage",
        "location": "Main Street, Block A"
    }
    create_res = client.post("/api/complaints", json=payload, headers=headers_c1)
    assert create_res.status_code == 201
    comp_data = create_res.json()
    comp_id = comp_data["id"]
    assert comp_data["reference_number"].startswith("CF-")
    assert comp_data["category"] == "Road Damage"
    assert comp_data["status"] == "Assigned"

    # 2. Citizen 2 tries to access Citizen 1's complaint -> 403 Forbidden
    token_c2 = create_access_token(subject=4, role="citizen")
    headers_c2 = {"Authorization": f"Bearer {token_c2}"}
    unauthorized_res = client.get(f"/api/complaints/{comp_id}", headers=headers_c2)
    assert unauthorized_res.status_code == 403

    # 3. Officer/Admin accesses complaint -> 200 OK
    token_admin = create_access_token(subject=1, role="admin")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}
    admin_res = client.get(f"/api/complaints/{comp_id}", headers=headers_admin)
    assert admin_res.status_code == 200

    # 4. Officer submits resolution evidence
    token_officer = create_access_token(subject=2, role="officer")
    headers_officer = {"Authorization": f"Bearer {token_officer}"}
    evidence_payload = {
        "completion_notes": "Road maintenance crew repaired the broken asphalt and leveled the road surface completely.",
        "photo_url": "/uploads/road_fixed.jpg"
    }
    ev_res = client.post(f"/api/complaints/{comp_id}/evidence", json=evidence_payload, headers=headers_officer)
    assert ev_res.status_code == 200
    ev_data = ev_res.json()
    assert ev_data["status"] == "Verified"
    assert ev_data["resolution_evidence"] is not None


def test_admin_dashboard_metrics():
    token_admin = create_access_token(subject=1, role="admin")
    headers = {"Authorization": f"Bearer {token_admin}"}
    res = client.get("/api/admin/dashboard", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_complaints" in data
    assert "resolution_rate_percent" in data
    assert "department_performance" in data


# ----------------- 4. TEST SERVER-RENDERED HTML PAGES (ZERO-JS) -----------------

def test_html_login_page_and_form():
    # GET /login returns 200 with HTML content
    res = client.get("/login")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "CivicFix" in res.text
    assert "Sign In" in res.text

    # POST /login with invalid credentials
    bad_login = client.post("/login", data={"email": "citizen1@test.com", "password": "WrongPassword"})
    assert bad_login.status_code == 400
    assert "Invalid email address or password" in bad_login.text

    # POST /login with valid credentials sets cookie and redirects
    good_login = client.post(
        "/login",
        data={"email": "citizen1@test.com", "password": "Password@123"},
        follow_redirects=False
    )
    assert good_login.status_code == 303
    assert "access_token" in good_login.cookies
    assert good_login.headers["location"] == "/citizen/dashboard"


def test_html_citizen_pages():
    client.cookies.clear()
    token = create_access_token(subject="citizen1@test.com", role="citizen")
    client.cookies.set("access_token", token)

    # 1. Citizen Dashboard
    dash_res = client.get("/citizen/dashboard")
    assert dash_res.status_code == 200
    assert "Citizen Grievance Portal" in dash_res.text
    assert "My Recent Complaints" in dash_res.text

    # 2. Submit Complaint Form
    new_res = client.get("/complaints/new")
    assert new_res.status_code == 200
    assert "Report a Municipal Issue" in new_res.text

    # 3. Submit Complaint POST (HTML Form)
    post_res = client.post(
        "/complaints/new",
        data={
            "category": "Road Damage",
            "title": "Severe pothole on 10th Main Road",
            "description": "Deep dangerous pothole damaging vehicles and causing traffic jam.",
            "location": "10th Main Road, Sector 4",
            "landmark": "Near Central Bank",
            "latitude": 12.9716,
            "longitude": 77.5946
        },
        follow_redirects=False
    )
    assert post_res.status_code == 303
    confirm_url = post_res.headers["location"]
    assert "/confirmation" in confirm_url

    # 4. Confirmation Page
    conf_res = client.get(confirm_url)
    assert conf_res.status_code == 200
    assert "Complaint Successfully Registered" in conf_res.text
    assert "Road Damage" in conf_res.text

    # 5. Complaints List
    list_res = client.get("/complaints")
    assert list_res.status_code == 200
    assert "My Reported Complaints" in list_res.text


def test_html_admin_and_ai_pages():
    client.cookies.clear()
    admin_token = create_access_token(subject="admintest@test.gov", role="admin")
    client.cookies.set("access_token", admin_token)

    # 1. Admin Dashboard
    admin_dash = client.get("/admin/dashboard")
    assert admin_dash.status_code == 200
    assert "City Operations Command Center" in admin_dash.text
    assert "Resolution Rate" in admin_dash.text

    # 2. Complaint Management Table
    mgmt_res = client.get("/admin/complaints")
    assert mgmt_res.status_code == 200
    assert "Complaint Management" in mgmt_res.text

    # 3. AI Operations Center
    ai_ops = client.get("/admin/ai-operations")
    assert ai_ops.status_code == 200
    assert "AI Operations Center" in ai_ops.text
    assert "Complaint Classifier" in ai_ops.text
    assert "Duplicate Detector" in ai_ops.text
    assert "Department Router" in ai_ops.text
    assert "Priority Assessor" in ai_ops.text
    assert "Resolution Verifier" in ai_ops.text

    # 4. Departments & SLA Page
    depts_res = client.get("/admin/departments")
    assert depts_res.status_code == 200
    assert "Departments & SLA Targets" in depts_res.text

    # 5. Resolution Verification Page
    verif_res = client.get("/admin/verification")
    assert verif_res.status_code == 200
    assert "Resolution Evidence & Verification" in verif_res.text

    # 6. Notifications & Activity Center
    # 6. Notifications & Activity Center
    notif_res = client.get("/notifications")
    assert notif_res.status_code == 200
    assert "Notifications & Activity Center" in notif_res.text
