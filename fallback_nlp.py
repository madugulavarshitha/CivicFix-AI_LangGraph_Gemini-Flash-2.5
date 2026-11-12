"""
Fallback deterministic NLP, keyword matching, and heuristics engine.
Used whenever an external LLM is not configured or unavailable.
Guarantees 100% offline functionality without external API keys.
"""

import re
import math
from typing import List, Dict, Any, Tuple, Optional

# Keyword dictionaries for classification
CATEGORY_KEYWORDS = {
    "Road Damage": [
        "pothole", "potholes", "crater", "asphalt", "road", "street", "pavement",
        "cracked road", "broken road", "tar", "speed breaker", "cave-in", "tarmac",
        "uneven surface", "road damage", "hole in road"
    ],
    "Garbage and Sanitation": [
        "garbage", "trash", "waste", "dump", "debris", "litter", "rubbish",
        "smell", "foul odor", "unclean", "dustbin", "overflowing bin", "sanitation",
        "dead animal", "carcass", "plastic waste", "filth", "dumping"
    ],
    "Streetlight Failure": [
        "streetlight", "street light", "lamp", "pole", "light", "darkness",
        "flickering", "bulb", "broken light", "no lighting", "dark road", "street lamp",
        "electrical pole", "blackout"
    ],
    "Water Leakage": [
        "water leak", "pipeline", "pipe burst", "burst pipe", "water supply",
        "gushing water", "clean water", "drinking water", "tap", "valve", "hydrant",
        "water wastage", "flooding street"
    ],
    "Drainage and Sewage": [
        "drain", "drainage", "sewage", "sewer", "manhole", "gutter", "clogged drain",
        "overflowing drain", "stagnant water", "black water", "foul water", "cesspool",
        "open drain", "choked drainage"
    ],
    "Public Safety": [
        "danger", "hazard", "live wire", "hanging wire", "electric shock",
        "open manhole", "collapsing wall", "falling tree", "sinkhole", "fire hazard",
        "stray dogs", "unsafe", "accident prone", "sparking"
    ]
}

# Safety risk triggers that demand immediate Critical priority
CRITICAL_SAFETY_TRIGGERS = [
    "live wire", "hanging wire", "electric shock", "sparking wire", "open manhole",
    "sinkhole", "toxic", "chemical", "gas leak", "explosion", "fire hazard",
    "collapsing", "cave-in", "electrocution", "road collapse", "severe flooding"
]

HIGH_SEVERITY_TRIGGERS = [
    "pipe burst", "gushing water", "major pothole", "deep pothole", "complete darkness",
    "all streetlights broken", "foul smell entering homes", "blocked main road",
    "overflowing sewage", "choked main drain", "accident"
]

def clean_tokens(text: str) -> List[str]:
    """Tokenize and normalize text."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    tokens = [t for t in text.split() if len(t) > 2]
    # Simple stop words removal
    stopwords = {"the", "and", "for", "with", "from", "that", "this", "there", "here", "are", "was", "were", "been"}
    return [t for t in tokens if t not in stopwords]

def classify_text_deterministic(title: str, description: str) -> Dict[str, Any]:
    full_text = f"{title} {description}".lower()
    scores = {}
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in full_text:
                # Direct phrase match gives higher weight
                score += 3 if " " in kw else 1.5
        scores[category] = score

    best_category, max_score = max(scores.items(), key=lambda x: x[1])
    
    if max_score == 0:
        return {
            "category": "Other",
            "summary": title.strip()[:150],
            "confidence": 0.45,
            "entities": {
                "issue_type": "Unspecified civic issue",
                "infrastructure": "General municipal asset"
            },
            "needs_review": True,
            "engine": "fallback_nlp"
        }
    
    confidence = min(0.95, 0.65 + (max_score * 0.05))
    
    # Extract entities
    entities = {
        "issue_type": best_category,
        "infrastructure": "Public municipal asset"
    }
    if "pothole" in full_text:
        entities["issue_type"] = "Road Pothole"
        entities["infrastructure"] = "Road surface"
    elif "manhole" in full_text:
        entities["issue_type"] = "Open/Damaged Manhole"
        entities["infrastructure"] = "Drainage network"
    elif "wire" in full_text:
        entities["issue_type"] = "Exposed/Live Cable"
        entities["infrastructure"] = "Electrical grid"
    elif "garbage" in full_text or "dump" in full_text:
        entities["issue_type"] = "Garbage Pile"
        entities["infrastructure"] = "Public street/bin"
    elif "pipe" in full_text or "pipeline" in full_text:
        entities["issue_type"] = "Water Pipe Leak"
        entities["infrastructure"] = "Water supply line"
        
    summary = f"{best_category}: {title.strip()}. {description.strip()[:100]}..."
    
    return {
        "category": best_category,
        "summary": summary,
        "confidence": round(confidence, 2),
        "entities": entities,
        "needs_review": confidence < 0.60,
        "engine": "fallback_nlp"
    }

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two coordinates."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def compute_text_similarity(text1: str, text2: str) -> float:
    tokens1 = set(clean_tokens(text1))
    tokens2 = set(clean_tokens(text2))
    
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = len(tokens1.intersection(tokens2))
    union = len(tokens1.union(tokens2))
    
    return round(intersection / union, 3)

def detect_duplicates_deterministic(
    new_complaint: Dict[str, Any],
    existing_complaints: List[Dict[str, Any]],
    similarity_threshold: float = 0.40,
    max_geo_distance_meters: float = 500.0
) -> List[Dict[str, Any]]:
    candidates = []
    new_text = f"{new_complaint.get('title', '')} {new_complaint.get('description', '')}"
    new_cat = new_complaint.get('category', '')
    new_lat = new_complaint.get('latitude')
    new_lon = new_complaint.get('longitude')
    new_loc = (new_complaint.get('location') or '').lower()

    for item in existing_complaints:
        # Ignore closed/rejected items if checking active duplicates
        if item.get('id') == new_complaint.get('id'):
            continue
            
        same_category = (item.get('category') == new_cat)
        exist_text = f"{item.get('title', '')} {item.get('description', '')}"
        text_sim = compute_text_similarity(new_text, exist_text)
        
        # Check location match
        loc_match = False
        item_loc = (item.get('location') or '').lower()
        if new_loc and item_loc and (new_loc in item_loc or item_loc in new_loc):
            loc_match = True
            
        # Geographic proximity
        geo_dist = None
        geo_bonus = 0.0
        if new_lat is not None and new_lon is not None and item.get('latitude') is not None and item.get('longitude') is not None:
            try:
                geo_dist = haversine_distance(float(new_lat), float(new_lon), float(item['latitude']), float(item['longitude']))
                if geo_dist <= max_geo_distance_meters:
                    geo_bonus = max(0.0, 0.35 * (1 - (geo_dist / max_geo_distance_meters)))
            except Exception:
                geo_dist = None
                
        # Total combined similarity
        category_factor = 0.2 if same_category else 0.0
        location_factor = 0.15 if loc_match else 0.0
        
        total_score = min(1.0, (text_sim * 0.5) + category_factor + location_factor + geo_bonus)
        
        if total_score >= similarity_threshold or (geo_dist is not None and geo_dist < 100 and same_category):
            reason_parts = []
            if same_category:
                reason_parts.append(f"Matching category '{new_cat}'")
            if text_sim > 0.3:
                reason_parts.append(f"{int(text_sim*100)}% descriptive term overlap")
            if loc_match:
                reason_parts.append(f"Near address '{item.get('location')}'")
            if geo_dist is not None:
                reason_parts.append(f"Within {int(geo_dist)}m geographic radius")
                
            candidates.append({
                "candidate_complaint_id": item.get('id'),
                "candidate_reference": item.get('reference_number'),
                "candidate_title": item.get('title'),
                "similarity_score": round(total_score, 2),
                "geo_distance_meters": round(geo_dist, 1) if geo_dist is not None else None,
                "match_reason": " & ".join(reason_parts) or "High thematic and location similarity"
            })
            
    # Sort highest similarity first
    candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
    return candidates

def route_department_deterministic(category: str, departments: List[Dict[str, Any]]) -> Dict[str, Any]:
    dept_map = {
        "Road Damage": "ROADS",
        "Garbage and Sanitation": "SANITATION",
        "Streetlight Failure": "ELECTRICAL",
        "Water Leakage": "WATER",
        "Drainage and Sewage": "DRAINAGE",
        "Public Safety": "SAFETY",
        "Other": "GENERAL"
    }
    target_code = dept_map.get(category, "GENERAL")
    
    matched_dept = next((d for d in departments if d.get("code") == target_code), None)
    if not matched_dept and departments:
        matched_dept = departments[0]
        
    return {
        "department_id": matched_dept.get("id") if matched_dept else None,
        "department_name": matched_dept.get("name") if matched_dept else "General Municipal Services",
        "department_code": target_code,
        "explanation": f"Automatically routed to {matched_dept.get('name') if matched_dept else target_code} based on complaint category '{category}'.",
        "requires_override_check": category == "Other",
        "engine": "fallback_nlp"
    }

def assess_priority_deterministic(title: str, description: str, category: str) -> Dict[str, Any]:
    full_text = f"{title} {description}".lower()
    
    # 1. Deterministic Critical triggers
    for trigger in CRITICAL_SAFETY_TRIGGERS:
        if trigger in full_text:
            return {
                "priority": "Critical",
                "urgency_hours": 12,
                "justification": f"Urgent safety hazard detected: '{trigger}' poses immediate public safety risk.",
                "requires_human_escalation": True,
                "engine": "fallback_nlp"
            }
            
    # 2. Category specific high severity
    if category == "Public Safety":
        return {
            "priority": "High",
            "urgency_hours": 24,
            "justification": "Public Safety category defaults to High urgency unless confirmed otherwise.",
            "requires_human_escalation": False,
            "engine": "fallback_nlp"
        }
        
    for trigger in HIGH_SEVERITY_TRIGGERS:
        if trigger in full_text:
            return {
                "priority": "High",
                "urgency_hours": 24,
                "justification": f"High severity condition detected: '{trigger}'.",
                "requires_human_escalation": False,
                "engine": "fallback_nlp"
            }
            
    # 3. Medium for standard infrastructure issues
    if category in ["Water Leakage", "Drainage and Sewage", "Road Damage"]:
        return {
            "priority": "Medium",
            "urgency_hours": 48,
            "justification": f"Standard municipal service request for {category}.",
            "requires_human_escalation": False,
            "engine": "fallback_nlp"
        }
        
    # 4. Low priority for minor/aesthetic or general
    return {
        "priority": "Low",
        "urgency_hours": 72,
        "justification": f"Non-hazardous complaint categorized as {category}.",
        "requires_human_escalation": False,
        "engine": "fallback_nlp"
    }

def verify_resolution_deterministic(
    complaint_title: str,
    complaint_description: str,
    complaint_category: str,
    completion_notes: str,
    has_photo: bool
) -> Dict[str, Any]:
    notes_lower = completion_notes.lower()
    checks = {}
    
    # Check 1: Adequate length
    checks["adequate_notes_length"] = len(completion_notes.strip()) >= 15
    
    # Check 2: Action words indicating physical resolution
    action_words = [
        "fixed", "repaired", "replaced", "cleared", "cleaned", "patched",
        "sealed", "restored", "installed", "removed", "resurfaced", "unclogged",
        "rectified", "completed", "tested", "operational"
    ]
    actions_found = [w for w in action_words if w in notes_lower]
    checks["action_resolution_keywords"] = len(actions_found) > 0
    checks["actions_identified"] = actions_found
    
    # Check 3: Relevancy to category
    cat_words = CATEGORY_KEYWORDS.get(complaint_category, [])
    has_cat_relevance = any(w in notes_lower for w in cat_words) or any(t in notes_lower for t in clean_tokens(complaint_title))
    checks["relevancy_to_original_issue"] = has_cat_relevance
    
    # Check 4: Photo evidence attached
    checks["visual_evidence_attached"] = has_photo
    
    # Determine Outcome
    # Passing all checks with photo -> Verified
    # Notes good but photo missing -> Needs Review (manual officer review)
    # Notes empty or completely unrelated -> Rejected or Needs Review
    if not checks["adequate_notes_length"] or not checks["action_resolution_keywords"]:
        outcome = "Rejected"
        summary = "Resolution notes are too vague or do not specify corrective actions taken."
        confidence = 0.85
    elif not checks["visual_evidence_attached"]:
        outcome = "Needs Review"
        summary = "Action notes provided, but visual photo evidence is missing. Officer visual sign-off required."
        confidence = 0.70
    elif not checks["relevancy_to_original_issue"]:
        outcome = "Needs Review"
        summary = "Resolution notes do not clearly reference the specific reported issue or category."
        confidence = 0.65
    else:
        outcome = "Verified"
        summary = f"Valid resolution evidence submitted. Actions taken ({', '.join(actions_found)}) directly address reported {complaint_category}."
        confidence = 0.92

    return {
        "outcome": outcome,
        "confidence_score": confidence,
        "checks_performed": checks,
        "verification_summary": summary,
        "engine": "fallback_nlp"
    }
