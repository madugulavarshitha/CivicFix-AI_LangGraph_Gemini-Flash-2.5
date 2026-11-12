from typing import Dict, Any, List
from app.agents.llm_service import ai_service

class DuplicateAgent:
    """Agent 2: Checks candidate complaints for semantic and geographic similarity."""
    name: str = "Duplicate Detector"
    purpose: str = "Scan existing active municipal complaints for semantic duplication and geographic proximity."

    def execute(
        self,
        new_complaint: Dict[str, Any],
        existing_complaints: List[Dict[str, Any]],
        similarity_threshold: float = 0.40
    ) -> Dict[str, Any]:
        try:
            candidates = ai_service.detect_duplicates(
                new_complaint=new_complaint,
                existing_complaints=existing_complaints,
                similarity_threshold=similarity_threshold
            )
            is_dup = len(candidates) > 0
            highest_score = candidates[0]["similarity_score"] if candidates else 0.0
            
            return {
                "status": "success",
                "is_potential_duplicate": is_dup,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "highest_score": highest_score,
                "confidence": 0.90 if is_dup else 0.85,
                "error": None
            }
        except Exception as e:
            return {
                "status": "failed",
                "is_potential_duplicate": False,
                "candidate_count": 0,
                "candidates": [],
                "highest_score": 0.0,
                "confidence": 0.0,
                "error": str(e)
            }

duplicate_agent = DuplicateAgent()
