# CivicFix AI — Autonomous Citizen Complaint Resolution Platform

CivicFix AI is a municipal complaint management system built strictly using **Python, FastAPI, Jinja2, HTML5, and CSS3**, orchestrated by a **LangGraph 5-agent AI workflow**, with **SQLAlchemy ORM** and **PostgreSQL** support.

The application adheres to a strict **zero-JavaScript constraint**: all interactions, forms, filters, navigation, status updates, modals, timelines, and metric charts are rendered on the server using semantic HTML5, pure CSS3, and standard HTTP POST/GET requests.

---

## 🏛️ System Architecture

```
+---------------------------------------------------------------------------------------+
|                       SERVER-RENDERED HTML5 & CSS3 FRONTEND                           |
|  - Jinja2 Templates (11 Dedicated Pages)          - Pure CSS Bar Charts & Indicators  |
|  - Semantic HTML5 Forms (POST / GET)              - Inline SVG Icon Assets            |
|  - Pure CSS Lifecycle Status Timeline             - Pastel Theme Design Tokens        |
|  - Strictly Zero JavaScript (0 .js, 0 scripts)   - Post/Redirect/Get (PRG) Pattern   |
+-------------------------------------------+-------------------------------------------+
                                            | HTTP Form Submissions / Secure Cookie Auth
                                            v
+---------------------------------------------------------------------------------------+
|                                    FASTAPI BACKEND                                    |
|  - Auth & RBAC (Citizen vs Officer/Admin)                 - Photo Uploads & Storage   |
|  - Complaint CRUD & Filtered Search                       - Audit Logging             |
|  - Notifications & Comments System                        - Analytics Aggregator      |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                        LANGGRAPH MULTI-AGENT WORKFLOW ORCHESTRATION                   |
|                                                                                       |
|  [Citizen Submission]                                                                 |
|         |                                                                             |
|         v                                                                             |
|  [Agent 1: Complaint Classifier]    --> Category, Summary, Confidence, Entities       |
|         |                                                                             |
|         v                                                                             |
|  [Agent 2: Duplicate Detector]      --> Semantic Overlap & Haversine Geo Proximity    |
|         |                                                                             |
|         v                                                                             |
|  [Agent 3: Department Router]       --> Department Matching & SLA Target Binding      |
|         |                                                                             |
|         v                                                                             |
|  [Agent 4: Priority Assessor]       --> Safety/Risk Assessment & Urgency Deadlines    |
|         |                                                                             |
|         v                                                                             |
|  [Database Persistence]             --> Executions, Audit Trail, Lifecycles           |
|         |                                                                             |
|  (Officer Submits Resolution Evidence)                                                |
|         v                                                                             |
|  [Agent 5: Resolution Verifier]     --> Note Analysis, Repair Verification Checklist  |
+---------------------------------------------------------------------------------------+
```

---

## 🎨 Pastel Municipal Design System

The user interface follows the municipal pastel color palette:
- **Primary Pastel Blue**: `#B8D8F8`
- **Soft Lavender**: `#D9CCFF`
- **Mint Green**: `#C9F2DF`
- **Pale Peach**: `#FFE0CC`
- **Light Yellow**: `#FFF1B8`
- **Main Background**: `#F8FAFC`
- **Card Background**: `#FFFFFF`
- **Primary Text**: `#243247`
- **Secondary Text**: `#718096`
- **Border**: `#E7ECF2`
- **Primary Action Button**: `#6478D8`
- **Success / Warning / Error**: `#27966F` / `#D99036` / `#D95D67`

---

## 📑 11 Server-Rendered HTML Pages

1. **Login Page (`/login`)**: Clean authentication with CivicFix branding, email/password fields, server-side validation error banners, and 1-click test login buttons (pure HTML forms).
2. **Citizen Registration (`/register`)**: Full name, email, phone, password confirmation, duplicate email prevention, and default `citizen` role assignment.
3. **Citizen Dashboard (`/citizen/dashboard`)**: Welcome banner, grievance KPI stats (Total, Open, In Progress, Resolved), recent complaints table, pure CSS status distribution bar chart, and recent notifications.
4. **Submit Complaint (`/complaints/new`)**: Category selector cards, title, description, address, GPS coordinates (for duplicate detection), and photo upload.
5. **Complaint Confirmation (`/complaints/{id}/confirmation`)**: Displays assigned reference ID (`CF-YYYYMMDD-XXXXXX`), classified category, assigned department, priority SLA, and duplicate detection alert.
6. **Complaint Tracking (`/complaints/{id}`)**: Pure CSS lifecycle status timeline (`Submitted` → `AI Analysis` → `Assigned` → `In Progress` → `Resolved` → `Verified` → `Closed`), AI summary card, duplicate warning, citizen comments thread, and unsatisfactory resolution reopening form.
7. **My Complaints List (`/complaints`)**: Filterable table with search, status filtering, category filtering, and direct links to tracking.
8. **Operations Dashboard (`/admin/dashboard`)**: Municipal command center with total complaints, critical issues count, resolution rate, average resolution hours, category CSS bar chart, priority breakdown, and department caseload table.
9. **Complaint Management (`/admin/complaints`)**: Advanced search, multi-criteria filtering, server-side pagination, and HTML `<details>` popups for direct department reassignment, priority update, and status change.
10. **AI Operations Center (`/admin/ai-operations`)**: Visual 5-agent LangGraph workflow diagram, 5 distinct agent cards with real calculated telemetry (processed count, successes, failures, latest output summary), and chronological execution trace inspector.
11. **Departments & SLAs (`/admin/departments`)**: All 7 municipal departments, contact info, workload counters (assigned, pending, resolved), and SLA configuration forms.
12. **Resolution Verification (`/admin/verification`)**: Officer evidence submission form with completion notes, work order number, after-photo upload, and Agent 5 automated verification checklist.
13. **Notifications & Activity Center (`/notifications`)**: User alerts feed with unread counters, "Mark as Read" actions, and real-time municipal audit log stream.

---

## 👥 Seeded Demonstration Accounts

The database seeds automatically upon startup:

| Role | Name | Email | Password |
|---|---|---|---|
| **Chief Admin** | Chief Municipal Officer | `admin@civicfix.gov` | `Admin@12345` |
| **Roads Officer** | Rajesh Kumar | `officer.roads@civicfix.gov` | `Officer@12345` |
| **Water Officer** | Elena Rostova | `officer.water@civicfix.gov` | `Officer@12345` |
| **Citizen 1** | Alex Mercer | `citizen@civicfix.gov` | `Citizen@12345` |
| **Citizen 2** | Priya Sharma | `citizen1@test.com` | `Password@123` |

> 💡 **1-Click Test Login**: The login screen (`/login`) includes pure HTML buttons for Chief Admin, Roads Officer, and Citizen to authenticate instantly with zero typing.

---

## 🤖 The 5 Multi-Agent AI Workflow

1. **Agent 1: Complaint Classifier (`classifier_agent.py`)**: Categorizes complaints into one of 7 municipal classes (`Road Damage`, `Garbage and Sanitation`, `Streetlight Failure`, `Water Leakage`, `Drainage and Sewage`, `Public Safety`, `Other`), generates a concise summary, extracts entities, and computes a confidence score.
2. **Agent 2: Duplicate Detector (`duplicate_agent.py`)**: Computes keyword overlap, text token similarity, and Haversine geographic proximity (radius ≤ 500m) against active complaints. Flags duplicate candidates without deleting citizen submissions.
3. **Agent 3: Department Router (`router_agent.py`)**: Recommends the responsible department based on civic jurisdiction rules and SLA target commitments.
4. **Agent 4: Priority Assessor (`priority_agent.py`)**: Assesses public hazard severity (e.g. live wire, sinkhole, toxic chemical spill triggers `Critical` priority with 12h SLA; water pipe burst triggers `High` priority; general issues default to `Medium` or `Low`).
5. **Agent 5: Resolution Verifier (`verifier_agent.py`)**: Evaluates officer completion notes and photographic evidence. Verifies action verbs (patched, replaced, cleared, unclogged, repaired), checks relevancy against the original report, and produces an automated verification checklist.

### 🛡️ Dual-Mode LLM & Deterministic Fallback Engine
- If `LLM_PROVIDER=openai` (or `gemini`, `anthropic`) with an API key is configured, the system uses external LLM calls.
- If no external API key is configured, the system runs its **deterministic local NLP and heuristic fallback engine**. Every execution record is transparently labeled `engine: "fallback_nlp"`.

---

## 🚀 Quickstart & Setup Guide

### 1. Prerequisites
- Python 3.10 or 3.11 installed.

### 2. Installation
```bash
cd backend
python -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Run Application Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open your browser at: **`http://127.0.0.1:8000/login`**

### 4. Run Pytest Test Suite
```bash
pytest app/tests/test_civicfix.py -v
```

### 5. PostgreSQL (Optional Production Database)
To run with PostgreSQL instead of the default local SQLite:
```bash
docker-compose up -d
```
Update `DATABASE_URL` in `backend/.env`:
```
DATABASE_URL=postgresql://civicfix:civicfix_secret@localhost:5432/civicfix_db
```
The application will automatically connect and create all tables.
