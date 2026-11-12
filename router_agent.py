from typing import Dict, Any, List
from app.agents.llm_service import ai_service

class RouterAgent:
    """Agent 3: Assigns the appropriate municipal department based on category and rules."""
    name: str = "Department Router"
    purpose: str = "Route complaint to responsible municipal department and compute service-level targets."

    def execute(
        self,
        category: str,
        entities: Dict[str, Any],
        departments: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        try:
            routing = ai_service.route_department(category, entities, departments)
            return {
                "status": "success",
                "department_id": routing.get("department_id"),
                "department_name": routing.get("department_name"),
                "department_code": routing.get("department_code"),
                "explanation": routing.get("explanation"),
                "requires_override_check": routing.get("requires_override_check", False),
                "confidence": 0.95 if category != "Other" else 0.50,
                "error": None
            }
        except Exception as e:
            return {
                "status": "failed",
                "department_id": None,
                "department_name": "General Municipal Services",
                "department_code": "GENERAL",
                "explanation": "Routing fallback due to execution failure.",
                "requires_override_check": True,
                "confidence": 0.0,
                "error": str(e)
            }

router_agent = RouterAgent()
