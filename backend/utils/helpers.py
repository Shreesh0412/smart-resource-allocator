"""
utils/helpers.py
FIXES:
  B10 — compute_urgency_from_deadline, days_remaining, and is_past_deadline all
        used datetime.fromisoformat() which on Python < 3.11 does not support
        timezone-aware suffixes like '+05:30'. Any such string caused a silent
        ValueError fallback to "low" urgency. Fixed by stripping the timezone
        portion before parsing so both aware and naive ISO strings work on all
        Python versions.
  S9  — paginate() loaded the entire MongoDB collection into memory before
        slicing (list(cursor.clone())). This would exhaust RAM on large datasets.
        Replaced with proper count_documents() + skip/limit so only the
        requested page is ever fetched from the database.
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
    """Haversine formula → great-circle distance in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
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
                params={"format": "jsonv2", "q": f"{pin}, India",
                        "countrycodes": "in", "limit": 1},
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
    """Resolve location from explicit lat/lng first; fall back to pincode geocoding."""
    pincode = normalize_pincode(payload.get("pincode", ""))

    lat = payload.get("lat")
    lng = payload.get("lng")

    if lat is not None and lng is not None:
        try:
            return {"lat": float(lat), "lng": float(lng), "pincode": pincode}
        except Exception:
            pass

    if pincode:
        geo_lat, geo_lng = geocode_pincode(pincode)
        if geo_lat is not None and geo_lng is not None:
            return {"lat": geo_lat, "lng": geo_lng, "pincode": pincode}

        if require_pincode:
            return {"error": "Could not resolve the provided pincode. "
                             "Please enter a valid Indian pincode."}

    if require_pincode:
        return {"error": "Please provide a valid Indian pincode."}

    return {"lat": None, "lng": None, "pincode": pincode}


# ── ISO datetime helper ───────────────────────────────────────────────────────

def _parse_iso(iso_str: str) -> Optional[datetime]:
    """
    FIX B10: Parse an ISO 8601 datetime string that may or may not carry a
    timezone offset (e.g. '+05:30', '+00:00', 'Z').

    datetime.fromisoformat() on Python < 3.11 raises ValueError for any
    timezone-aware string, silently falling back to 'low' urgency everywhere
    a deadline was parsed. This helper strips the offset so the naive UTC
    portion is parsed correctly on all Python versions (3.8+).
    """
    if not iso_str:
        return None
    # Remove a trailing 'Z' (UTC indicator used by JavaScript Date.toISOString)
    s = iso_str.strip().rstrip("Z")
    # Strip any '+HH:MM' or '-HH:MM' timezone offset
    s = re.sub(r"[+-]\d{2}:\d{2}$", "", s)
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ── Task Urgency ───────────────────────────────────────────────────────────────

def compute_urgency_from_deadline(deadline_iso: str) -> str:
    """
    Given an ISO deadline string, compute the current urgency level.
        > 7 days  → "low"
        2-7 days  → "med"
        ≤ 1 day   → "urgent"
    """
    cfg      = current_app.config
    deadline = _parse_iso(deadline_iso)
    if deadline is None:
        return "low"

    days_left = (deadline - datetime.utcnow()).days
    if days_left > cfg["URGENCY_LOW_DAYS"]:
        return "low"
    elif days_left > cfg["URGENCY_URGENT_DAYS"]:
        return "med"
    else:
        return "urgent"


def days_remaining(deadline_iso: str) -> int:
    deadline = _parse_iso(deadline_iso)
    if deadline is None:
        return 0
    return max(0, (deadline - datetime.utcnow()).days)


def is_past_deadline(deadline_iso: str) -> bool:
    deadline = _parse_iso(deadline_iso)
    if deadline is None:
        return False
    return deadline < datetime.utcnow()


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

def paginate(collection, query: dict, page: int = 1, per_page: int = 20):
    """
    FIX S9: The old implementation called list(cursor.clone()) which fetched
    the ENTIRE collection into memory before slicing. On a large dataset this
    exhausts RAM and is O(N) for every page request.

    This version uses count_documents() + skip/limit so only the requested
    page is transferred from MongoDB — O(per_page) regardless of collection size.

    Usage:
        docs, total = paginate(db.tasks, {"status": "open"}, page=2, per_page=20)
    """
    total = collection.count_documents(query)
    docs  = list(
        collection.find(query)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return docs, total


# ── Rating average ─────────────────────────────────────────────────────────────

def compute_avg_rating(reviews: List[Dict]) -> float:
    if not reviews:
        return 0.0
    return round(sum(r.get("rating", 0) for r in reviews) / len(reviews), 2)
