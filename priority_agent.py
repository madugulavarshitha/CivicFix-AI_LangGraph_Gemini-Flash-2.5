from typing import Dict, Any
from app.agents.llm_service import ai_service

class PriorityAgent:
    """Agent 4: Assesses safety risk, severity, public impact, and sets deadline."""
    name: str = "Priority Assessor"
    purpose: str = "Evaluate public hazard, urgency, safety triggers, and establish resolution deadlines."

    def execute(self, title: str, description: str, category: str) -> Dict[str, Any]:
        try:
            priority_info = ai_service.assess_priority(title, description, category)
            return {
                "status": "success",
                "priority": priority_info.get("priority", "Medium"),
                "urgency_hours": priority_info.get("urgency_hours", 48),
                "justification": priority_info.get("justification", "Default assessment based on category."),
                "requires_human_escalation": priority_info.get("requires_human_escalation", False),
                "confidence": 0.92,
                "error": None
            }
        except Exception as e:
            return {
                "status": "failed",
                "priority": "Medium",
                "urgency_hours": 48,
                "justification": "Fallback priority due to evaluation error.",
                "requires_human_escalation": True,
                "confidence": 0.0,
                "error": str(e)
            }

priority_agent = PriorityAgent()
