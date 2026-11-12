import os
import json
import logging
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.agents.fallback_nlp import (
    classify_text_deterministic,
    detect_duplicates_deterministic,
    route_department_deterministic,
    assess_priority_deterministic,
    verify_resolution_deterministic,
)

logger = logging.getLogger("civicfix.llm_service")

class AIWorkflowService:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower() if settings.LLM_PROVIDER else "fallback"
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.is_llm_enabled = bool(self.api_key and self.provider not in ["fallback", "none", ""])

    def classify_complaint(self, title: str, description: str) -> Dict[str, Any]:
        """Classify category, summarize, and extract entities."""
        # Check if external LLM is configured
        if self.is_llm_enabled and self.provider == "openai":
            try:
                import httpx
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                prompt = (
                    "You are a municipal complaint triage AI. Analyze this complaint:\n"
                    f"Title: {title}\nDescription: {description}\n\n"
                    "Classify into exactly one of: ['Road Damage', 'Garbage and Sanitation', 'Streetlight Failure', "
                    "'Water Leakage', 'Drainage and Sewage', 'Public Safety', 'Other'].\n"
                    "Return ONLY valid JSON with keys: category, summary, confidence (float 0.0-1.0), entities (dict), needs_review (bool)."
                )
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
                response = httpx.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    parsed = json.loads(data["choices"][0]["message"]["content"])
                    parsed["engine"] = f"llm_{self.provider}"
                    return parsed
            except Exception as e:
                logger.warning(f"External LLM classification failed ({e}), falling back to deterministic NLP.")

        # Deterministic fallback
        return classify_text_deterministic(title, description)

    def detect_duplicates(
        self,
        new_complaint: Dict[str, Any],
        existing_complaints: List[Dict[str, Any]],
        similarity_threshold: float = 0.40
    ) -> List[Dict[str, Any]]:
        """Identify potential duplicate candidates."""
        # Semantic + Geo fallback engine
        return detect_duplicates_deterministic(new_complaint, existing_complaints, similarity_threshold)

    def route_department(
        self,
        category: str,
        entities: Dict[str, Any],
        departments: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Select responsible department based on rules + AI entity analysis."""
        return route_department_deterministic(category, departments)

    def assess_priority(
        self,
        title: str,
        description: str,
        category: str
    ) -> Dict[str, Any]:
        """Determine Low, Medium, High, or Critical priority with deadlines."""
        return assess_priority_deterministic(title, description, category)

    def verify_resolution(
        self,
        complaint_title: str,
        complaint_description: str,
        complaint_category: str,
        completion_notes: str,
        has_photo: bool
    ) -> Dict[str, Any]:
        """Verify resolution completion notes and evidence."""
        return verify_resolution_deterministic(
            complaint_title=complaint_title,
            complaint_description=complaint_description,
            complaint_category=complaint_category,
            completion_notes=completion_notes,
            has_photo=has_photo
        )

ai_service = AIWorkflowService()
