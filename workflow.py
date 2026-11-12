from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime, timezone
import json

from langgraph.graph import StateGraph, END
from app.agents.classifier_agent import classifier_agent
from app.agents.duplicate_agent import duplicate_agent
from app.agents.router_agent import router_agent
from app.agents.priority_agent import priority_agent

def utcnow():
    return datetime.now(timezone.utc)

class ComplaintWorkflowState(TypedDict):
    complaint_id: int
    title: str
    description: str
    category: str
    location: str
    latitude: Optional[float]
    longitude: Optional[float]
    existing_complaints: List[Dict[str, Any]]
    departments: List[Dict[str, Any]]
    
    # Agent outputs
    classification: Optional[Dict[str, Any]]
    duplicates: Optional[Dict[str, Any]]
    routing: Optional[Dict[str, Any]]
    priority: Optional[Dict[str, Any]]
    
    # Tracking
    agent_logs: List[Dict[str, Any]]
    errors: List[str]
    final_status: str


def classify_node(state: ComplaintWorkflowState) -> Dict[str, Any]:
    started_at = utcnow()
    title = state.get("title", "")
    description = state.get("description", "")
    
    res = classifier_agent.execute(title=title, description=description)
    completed_at = utcnow()
    
    log_entry = {
        "agent_name": classifier_agent.name,
        "status": res["status"],
        "input_summary": f"Title: {title[:50]} | Desc: {description[:80]}",
        "output_summary": json.dumps({
            "category": res["category"],
            "summary": res["summary"],
            "confidence": res["confidence"]
        }),
        "confidence": res["confidence"],
        "error_message": res.get("error"),
        "started_at": started_at,
        "completed_at": completed_at,
        "engine": res.get("engine")
    }
    
    new_logs = list(state.get("agent_logs", [])) + [log_entry]
    new_errors = list(state.get("errors", []))
    if res.get("error"):
        new_errors.append(f"Classifier error: {res['error']}")
        
    return {
        "category": res["category"],
        "classification": res,
        "agent_logs": new_logs,
        "errors": new_errors
    }


def duplicate_node(state: ComplaintWorkflowState) -> Dict[str, Any]:
    started_at = utcnow()
    new_complaint = {
        "id": state.get("complaint_id"),
        "title": state.get("title"),
        "description": state.get("description"),
        "category": state.get("category"),
        "location": state.get("location"),
        "latitude": state.get("latitude"),
        "longitude": state.get("longitude")
    }
    
    existing = state.get("existing_complaints", [])
    res = duplicate_agent.execute(new_complaint=new_complaint, existing_complaints=existing)
    completed_at = utcnow()
    
    log_entry = {
        "agent_name": duplicate_agent.name,
        "status": res["status"],
        "input_summary": f"Compared against {len(existing)} active issues.",
        "output_summary": json.dumps({
            "is_duplicate": res["is_potential_duplicate"],
            "candidates_found": res["candidate_count"],
            "highest_similarity": res["highest_score"]
        }),
        "confidence": res["confidence"],
        "error_message": res.get("error"),
        "started_at": started_at,
        "completed_at": completed_at
    }
    
    new_logs = list(state.get("agent_logs", [])) + [log_entry]
    new_errors = list(state.get("errors", []))
    if res.get("error"):
        new_errors.append(f"Duplicate detector error: {res['error']}")
        
    return {
        "duplicates": res,
        "agent_logs": new_logs,
        "errors": new_errors
    }


def router_node(state: ComplaintWorkflowState) -> Dict[str, Any]:
    started_at = utcnow()
    category = state.get("category", "Other")
    classification = state.get("classification") or {}
    entities = classification.get("entities", {})
    departments = state.get("departments", [])
    
    res = router_agent.execute(category=category, entities=entities, departments=departments)
    completed_at = utcnow()
    
    log_entry = {
        "agent_name": router_agent.name,
        "status": res["status"],
        "input_summary": f"Category: {category} | Entities: {entities}",
        "output_summary": json.dumps({
            "department": res["department_name"],
            "code": res["department_code"],
            "explanation": res["explanation"]
        }),
        "confidence": res["confidence"],
        "error_message": res.get("error"),
        "started_at": started_at,
        "completed_at": completed_at
    }
    
    new_logs = list(state.get("agent_logs", [])) + [log_entry]
    new_errors = list(state.get("errors", []))
    if res.get("error"):
        new_errors.append(f"Router error: {res['error']}")
        
    return {
        "routing": res,
        "agent_logs": new_logs,
        "errors": new_errors
    }


def priority_node(state: ComplaintWorkflowState) -> Dict[str, Any]:
    started_at = utcnow()
    title = state.get("title", "")
    description = state.get("description", "")
    category = state.get("category", "Other")
    
    res = priority_agent.execute(title=title, description=description, category=category)
    completed_at = utcnow()
    
    log_entry = {
        "agent_name": priority_agent.name,
        "status": res["status"],
        "input_summary": f"Title: {title[:40]} | Category: {category}",
        "output_summary": json.dumps({
            "priority": res["priority"],
            "urgency_hours": res["urgency_hours"],
            "justification": res["justification"]
        }),
        "confidence": res["confidence"],
        "error_message": res.get("error"),
        "started_at": started_at,
        "completed_at": completed_at
    }
    
    new_logs = list(state.get("agent_logs", [])) + [log_entry]
    new_errors = list(state.get("errors", []))
    if res.get("error"):
        new_errors.append(f"Priority assessor error: {res['error']}")
        
    return {
        "priority": res,
        "agent_logs": new_logs,
        "errors": new_errors,
        "final_status": "Assigned" if res["status"] == "success" else "AI Analysis"
    }


def build_complaint_graph():
    """Build and compile the LangGraph complaint processing workflow."""
    workflow = StateGraph(ComplaintWorkflowState)
    
    # Add nodes
    workflow.add_node("classify", classify_node)
    workflow.add_node("detect_duplicates", duplicate_node)
    workflow.add_node("route_department", router_node)
    workflow.add_node("assess_priority", priority_node)
    
    # Set entry point
    workflow.set_entry_point("classify")
    
    # Linear and conditional workflow
    workflow.add_edge("classify", "detect_duplicates")
    workflow.add_edge("detect_duplicates", "route_department")
    workflow.add_edge("route_department", "assess_priority")
    workflow.add_edge("assess_priority", END)
    
    return workflow.compile()

complaint_graph = build_complaint_graph()

def run_complaint_workflow(
    complaint_dict: Dict[str, Any],
    existing_complaints: List[Dict[str, Any]],
    departments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Execute the multi-agent graph on a complaint."""
    initial_state: ComplaintWorkflowState = {
        "complaint_id": complaint_dict.get("id", 0),
        "title": complaint_dict.get("title", ""),
        "description": complaint_dict.get("description", ""),
        "category": complaint_dict.get("category", "Other"),
        "location": complaint_dict.get("location", ""),
        "latitude": complaint_dict.get("latitude"),
        "longitude": complaint_dict.get("longitude"),
        "existing_complaints": existing_complaints,
        "departments": departments,
        "classification": None,
        "duplicates": None,
        "routing": None,
        "priority": None,
        "agent_logs": [],
        "errors": [],
        "final_status": "Assigned"
    }
    
    final_state = complaint_graph.invoke(initial_state)
    return final_state
