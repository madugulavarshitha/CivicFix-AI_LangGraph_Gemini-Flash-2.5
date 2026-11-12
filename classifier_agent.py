from typing import Dict, Any
from app.agents.llm_service import ai_service

class ClassifierAgent:
    """Agent 1: Analyzes title and description to categorize and summarize the complaint."""
    name: str = "Complaint Classifier"
    purpose: str = "Classify civic issue category, extract key entities, and generate an executive summary."

    def execute(self, title: str, description: str) -> Dict[str, Any]:
        try:
            result = ai_service.classify_complaint(title, description)
            return {
                "status": "success",
                "category": result.get("category", "Other"),
                "summary": result.get("summary", title),
                "confidence": result.get("confidence", 0.5),
                "entities": result.get("entities", {}),
                "needs_review": result.get("needs_review", False),
                "engine": result.get("engine", "fallback_nlp"),
                "error": None
            }
        except Exception as e:
            return {
                "status": "failed",
                "category": "Other",
                "summary": title,
                "confidence": 0.0,
                "entities": {},
                "needs_review": True,
                "engine": "fallback_nlp",
                "error": str(e)
            }

classifier_agent = ClassifierAgent()
