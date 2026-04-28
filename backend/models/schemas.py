"""
models/schemas.py
-----------------
Pydantic-style Python dataclass schemas that define
the shape of every MongoDB document in the platform.
MongoDB is schema-less but we enforce structure here
so every insert is predictable and documented.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any


# ── Shared helpers ─────────────────────────────────────────────────────────────

def utcnow() -> str:
    return datetime.utcnow().isoformat()

def geo_point(lat: float, lng: float) -> Dict:
    """GeoJSON Point — required for MongoDB $near / $geoWithin queries."""
    return {"type": "Point", "coordinates": [lng, lat]}   # NOTE: [lng, lat] order!


# ── Volunteer ──────────────────────────────────────────────────────────────────

def volunteer_schema(
    name: str,
    email: str,
    password_hash: str,
    phone: str,
    lat: float,
    lng: float,
    skills: List[str] = None,
    availability: List[str] = None,          # ["Mon", "Tue", ...]
    pincode: str = "",
) -> Dict:
    return {
        "type":             "volunteer",
        "name":             name,
        "email":            email.lower(),
        "password_hash":    password_hash,
        "phone":            phone,
        "location":         geo_point(lat, lng),  # current/home location
        "lat":              lat,
        "lng":              lng,
        "skills":           skills or [],
        "availability":     availability or [],
        "pincode":          pincode or "",

        # Trust / Reputation
        "trust_score":      50,              # starts at 50/100
        "confidence_score": 50,
        "is_verified":      False,
        "verified_badge":   False,
        "total_tasks_done": 0,
        "tasks_on_time":    0,
        "tasks_late":       0,
        "tasks_rejected":   0,
        "reviews":          [],              # [{ngo_id, rating, comment, date}]
        "avg_rating":       0.0,

        # Operational
        "active_task_id":   None,
        "task_history":     [],              # list of task_ids
        "whatsapp_opt_in":  True,
        "status":           "active",        # active | inactive | banned
        "created_at":       utcnow(),
        "updated_at":       utcnow(),
    }


# ── NGO ───────────────────────────────────────────────────────────────────────

def ngo_schema(
    name: str,
    email: str,
    password_hash: str,
    phone: str,
    registration_number: str,
    lat: float,
    lng: float,
    focus_areas: List[str] = None,
    pincode: str = "",
) -> Dict:
    return {
        "type":                "ngo",
        "name":                name,
        "email":               email.lower(),
        "password_hash":       password_hash,
        "phone":               phone,
        "registration_number": registration_number,
        "location":            geo_point(lat, lng),
        "lat":                 lat,
        "lng":                 lng,
        "focus_areas":         focus_areas or [],    # ["education","health", ...]
        "pincode":             pincode or "",

        # Stats
        "total_tasks_posted":     0,
        "total_tasks_completed":  0,
        "active_volunteers":      0,

        # Resources they manage
        "resources":           [],              # see resource_schema

        "is_verified":         False,
        "status":              "active",
        "created_at":          utcnow(),
        "updated_at":          utcnow(),
    }


# ── Task ──────────────────────────────────────────────────────────────────────

def task_schema(
    ngo_id: str,
    title: str,
    description: str,
    task_type: str,                         # "education"|"health"|"food"|"rescue"|...
    lat: float,
    lng: float,
    address: str,
    deadline: str,                          # ISO date string
    urgency: str,                           # "low"|"med"|"urgent"
    volunteers_needed: int = 1,
    pincode: str = "",
    required_skills: List[str] = None,
    resources_needed: List[Dict] = None,
) -> Dict:
    return {
        "ngo_id":            ngo_id,
        "title":             title,
        "description":       description,
        "task_type":         task_type,
        "location":          geo_point(lat, lng),
        "lat":               lat,
        "lng":               lng,
        "address":           address,
        "pincode":           pincode or "",
        "deadline":          deadline,
        "urgency":           urgency,        # "low" | "med" | "urgent"
        "volunteers_needed": volunteers_needed,
        "required_skills":   required_skills or [],
        "resources_needed":  resources_needed or [],

        # Assignment
        "assigned_volunteers": [],           # list of volunteer_ids
        "applicants":          [],           # [{volunteer_id, applied_at, status}]

        # Lifecycle
        "status":            "open",         # open|assigned|in_progress|completed|cancelled
        "proof_of_work":     [],             # [{volunteer_id, file_url, uploaded_at, approved}]
        "completion_notes":  None,
        "completed_at":      None,

        # AI / Predictor metadata
        "predicted_risk":    None,           # "on_track"|"at_risk"|"critical"
        "auto_matches":      [],             # volunteer_ids suggested by geo-matcher

        "created_at":        utcnow(),
        "updated_at":        utcnow(),
    }


# ── Problem Report (Community → NGO) ──────────────────────────────────────────

def problem_report_schema(
    reporter_name: str,
    reporter_contact: str,
    problem_type: str,
    description: str,
    lat: float,
    lng: float,
    address: str,
    urgency_self_reported: str = "low",
    media_urls: List[str] = None,
    pincode: str = "",
    extracted_resources: Dict = None,
) -> Dict:
    return {
        "reporter_name":        reporter_name,
        "reporter_contact":     reporter_contact,
        "problem_type":         problem_type,
        "description":          description,
        "location":             geo_point(lat, lng),
        "lat":                  lat,
        "lng":                  lng,
        "address":              address,
        "urgency_self_reported":urgency_self_reported,
        "pincode":              pincode or "",
        "media_urls":           media_urls or [],
        "extracted_resources":  extracted_resources or {},

        # Approval flow
        "status":               "pending",   # pending|approved|rejected|converted_to_task
        "reviewed_by_ngo_id":   None,
        "ngo_review_note":      None,
        "converted_task_id":    None,
        "reviewed_at":          None,
        "created_at":           utcnow(),
    }


# ── Resource ──────────────────────────────────────────────────────────────────

def resource_schema(
    ngo_id: str,
    name: str,
    category: str,                          # "food"|"medicine"|"transport"|"equipment"
    quantity: float,
    unit: str,                              # "kg","units","liters",...
    lat: float,
    lng: float,
    available_from: str = None,
    available_until: str = None,
    notes: str = "",
) -> Dict:
    return {
        "ngo_id":          ngo_id,
        "name":            name,
        "category":        category,
        "quantity":        quantity,
        "unit":            unit,
        "location":        geo_point(lat, lng),
        "lat":             lat,
        "lng":             lng,
        "available_from":  available_from,
        "available_until": available_until,
        "notes":           notes,
        "allocated_to":    [],              # [{task_id, amount}]
        "status":          "available",    # available|partially_used|depleted
        "created_at":      utcnow(),
        "updated_at":      utcnow(),
    }


# ── Notification ──────────────────────────────────────────────────────────────

def notification_schema(
    recipient_id: str,
    recipient_type: str,                    # "volunteer"|"ngo"
    title: str,
    message: str,
    notif_type: str,                        # "task_assigned"|"task_update"|"review"|...
    reference_id: str = None,
    channel: str = "in_app",               # "in_app"|"whatsapp"|"both"
) -> Dict:
    return {
        "recipient_id":   recipient_id,
        "recipient_type": recipient_type,
        "title":          title,
        "message":        message,
        "type":           notif_type,
        "reference_id":   reference_id,
        "channel":        channel,
        "is_read":        False,
        "whatsapp_sent":  False,
        "created_at":     utcnow(),
    }


# ── Travel Log (for Inefficiency Detector) ────────────────────────────────────

def travel_log_schema(
    volunteer_id: str,
    task_id: str,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    actual_distance_km: float,
    optimal_distance_km: float,
) -> Dict:
    excess = max(0.0, actual_distance_km - optimal_distance_km)
    return {
        "volunteer_id":       volunteer_id,
        "task_id":            task_id,
        "start_lat":          start_lat,
        "start_lng":          start_lng,
        "end_lat":            end_lat,
        "end_lng":            end_lng,
        "actual_distance_km": actual_distance_km,
        "optimal_distance_km":optimal_distance_km,
        "excess_km":          excess,
        "flagged":            False,
        "logged_at":          utcnow(),
    }
