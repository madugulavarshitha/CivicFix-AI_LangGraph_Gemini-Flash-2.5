from typing import Dict, Any
from app.agents.llm_service import ai_service

class VerifierAgent:
    """Agent 5: Validates resolution completion notes and evidence before closing issues."""
    name: str = "Resolution Verifier"
    purpose: str = "Cross-examine officer resolution evidence, action notes, and photo presence."

    def execute(
        self,
        complaint_title: str,
        complaint_description: str,
        complaint_category: str,
        completion_notes: str,
        has_photo: bool
    ) -> Dict[str, Any]:
        try:
            verification = ai_service.verify_resolution(
                complaint_title=complaint_title,
                complaint_description=complaint_description,
                complaint_category=complaint_category,
                completion_notes=completion_notes,
                has_photo=has_photo
            )
            return {
                "status": "success",
                "outcome": verification.get("outcome", "Needs Review"),
                "confidence_score": verification.get("confidence_score", 0.70),
                "checks_performed": verification.get("checks_performed", {}),
                "verification_summary": verification.get("verification_summary", ""),
                "engine": verification.get("engine", "fallback_nlp"),
                "error": None
            }
        except Exception as e:
            return {
                "status": "failed",
                "outcome": "Needs Review",
                "confidence_score": 0.0,
                "checks_performed": {"system_error": str(e)},
                "verification_summary": "Automated verification error; routed to manual officer supervisor review.",
                "engine": "fallback_nlp",
                "error": str(e)
            }

verifier_agent = VerifierAgent()
