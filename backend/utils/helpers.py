"""
utils/helpers.py
----------------
Miscellaneous helpers used across routes and services.
"""

import math
import re
from datetime import datetime
import requests
from bson import ObjectId
from typing import Any, Dict, List, Optional
from flask import current_app


# ── ObjectId ──────────────────────────────────────────────────────────────────

def to_oid(id_str: str) -> Optional[ObjectId]:
    """Safely convert string → ObjectId, return None if invalid."""
    try:
        return ObjectId(id_str)
    except Exception:
        return None


def serialize(doc: Dict) -> Dict:
    """
    Recursively convert ObjectIds and datetimes in a MongoDB document
    to JSON-serialisable strings.
    """
    if doc is None:
        return None
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = serialize(v)
        elif isinstance(v, list):
            out[k] = [serialize(i) if isinstance(i, dict) else
                      (str(i) if isinstance(i, ObjectId) else i)
                      for i in v]
        else:
            out[k] = v
    return out


def serialize_list(docs: List[Dict]) -> List[Dict]:
    return [serialize(d) for d in docs]


# ── Geo / Distance ─────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Haversine formula → great-circle distance in kilometres.
    """
    R = 6371.0
    phi1, phi2   = math.radians(lat1), math.radians(lat2)
    dphi         = math.radians(lat2 - lat1)
    dlambda      = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def km_to_meters(km: float) -> float:
    return km * 1000.0


# ── India pincode geocoding ───────────────────────────────────────────────────

def normalize_pincode(pincode: str) -> str:
    """Keep only 6 digits."""
    digits = re.sub(r"\D", "", str(pincode or ""))
    return digits if len(digits) == 6 else ""


def geocode_pincode(pincode: str):
    """Convert an Indian pincode to approximate lat/lng using Nominatim."""
    pin = normalize_pincode(pincode)
    if not pin:
        return None, None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "jsonv2", "postalcode": pin, "countrycodes": "in", "limit": 1},
            headers={"User-Agent": "Saarthi/1.0 (hackathon project)"},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json() or []
        if not results:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "jsonv2", "q": f"{pin}, India", "countrycodes": "in", "limit": 1},
                headers={"User-Agent": "Saarthi/1.0 (hackathon project)"},
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json() or []
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None, None


def resolve_location_payload(payload: Dict, *, require_pincode: bool = False):
    """Resolve location from pincode first; fall back to explicit lat/lng if present."""
    pincode = normalize_pincode(payload.get("pincode", ""))
    if pincode:
        lat, lng = geocode_pincode(pincode)
        if lat is not None and lng is not None:
            return {"lat": lat, "lng": lng, "pincode": pincode}
        if require_pincode:
            return {"error": "Could not resolve the provided pincode. Please enter a valid Indian pincode."}

    lat = payload.get("lat")
    lng = payload.get("lng")
    if lat is not None and lng is not None:
        try:
            return {"lat": float(lat), "lng": float(lng), "pincode": pincode}
        except Exception:
            pass

    if require_pincode:
        return {"error": "Please provide a valid Indian pincode."}
    return {"lat": None, "lng": None, "pincode": pincode}


# ── Task Urgency ───────────────────────────────────────────────────────────────

def compute_urgency_from_deadline(deadline_iso: str) -> str:
    """
    Given an ISO deadline string, compute the current urgency level
    based on days remaining.
        > 7 days  → "low"
        2-7 days  → "med"
        ≤ 1 day   → "urgent"
    """
    cfg = current_app.config
    try:
        deadline = datetime.fromisoformat(deadline_iso)
    except ValueError:
        return "low"
    days_left = (deadline - datetime.utcnow()).days
    if days_left > cfg["URGENCY_LOW_DAYS"]:
        return "low"
    elif days_left > cfg["URGENCY_URGENT_DAYS"]:
        return "med"
    else:
        return "urgent"


def days_remaining(deadline_iso: str) -> int:
    try:
        deadline = datetime.fromisoformat(deadline_iso)
        return max(0, (deadline - datetime.utcnow()).days)
    except Exception:
        return 0


def is_past_deadline(deadline_iso: str) -> bool:
    try:
        deadline = datetime.fromisoformat(deadline_iso)
        return deadline < datetime.utcnow()
    except Exception:
        return False


# ── File Upload ────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]
    )


# ── Validation ─────────────────────────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$", email))

def is_valid_phone(phone: str) -> bool:
    return bool(re.match(r"^\+?[\d\s\-]{7,15}$", phone))


# ── Pagination ─────────────────────────────────────────────────────────────────

def paginate(query_cursor, page: int = 1, per_page: int = 20):
    """Skip/limit pagination; returns (docs, total)."""
    total = query_cursor.count()
    docs  = list(query_cursor.skip((page - 1) * per_page).limit(per_page))
    return docs, total


# ── Rating average ─────────────────────────────────────────────────────────────

def compute_avg_rating(reviews: List[Dict]) -> float:
    if not reviews:
        return 0.0
    return round(sum(r.get("rating", 0) for r in reviews) / len(reviews), 2)
