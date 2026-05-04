"""
services/inefficiency_detector.py
----------------------------------
★ Inefficiency Detector  (from your notes)
  "This volunteer traveled 10 km unnecessarily"

Analyzes travel logs submitted by volunteers when they complete tasks.
Compares actual distance traveled vs. optimal (straight-line) distance,
flags cases where excess travel exceeds the configured threshold.

Also provides:
  - Per-volunteer inefficiency summary
  - Per-NGO inefficiency report (which task assignments caused waste)
  - Route optimization suggestions
"""

from bson import ObjectId
from utils.helpers import haversine_km


# ── Analyze a single travel log entry ────────────────────────────────────────

def analyze_travel(db, log_id: str, config: dict) -> dict:
    """
    Called after a volunteer logs their travel.
    Compares actual vs. optimal distance and flags if wasteful.
    Returns a human-readable inefficiency report dict.
    """
    threshold_km = config.get("INEFFICIENCY_THRESHOLD_KM", 5)

    log = db.travel_logs.find_one({"_id": ObjectId(log_id)})
    if not log:
        return {"error": "Log not found"}

    actual   = log.get("actual_distance_km",  0)
    optimal  = log.get("optimal_distance_km", 0)
    excess   = log.get("excess_km",           0)
    flagged  = excess >= threshold_km

    if flagged:
        db.travel_logs.update_one({"_id": ObjectId(log_id)}, {"$set": {"flagged": True}})

        # Notify the associated NGO
        task = db.tasks.find_one({"_id": ObjectId(log["task_id"])}) if log.get("task_id") else None
        if task:
            _notify_ngo_of_inefficiency(db, task["ngo_id"], log, excess)

    return {
        "flagged":         flagged,
        "actual_km":       round(actual, 2),
        "optimal_km":      round(optimal, 2),
        "excess_km":       round(excess, 2),
        "threshold_km":    threshold_km,
        "message":         _build_message(flagged, excess, actual, optimal),
        "recommendation":  _recommend(flagged, excess),
    }


# ── Per-volunteer Inefficiency Summary ───────────────────────────────────────

def volunteer_inefficiency_summary(db, volunteer_id: str) -> dict:
    """
    Aggregated inefficiency stats for a volunteer.
    Used in the volunteer's own stats page and in NGO analytics.
    """
    logs = list(db.travel_logs.find({"volunteer_id": volunteer_id}))
    if not logs:
        return {"total_logs": 0, "flagged": 0, "total_excess_km": 0, "avg_excess_km": 0}

    flagged    = [l for l in logs if l.get("flagged")]
    total_excess = sum(l.get("excess_km", 0) for l in logs)

    return {
        "total_logs":      len(logs),
        "flagged":         len(flagged),
        "total_actual_km": round(sum(l.get("actual_distance_km", 0) for l in logs), 2),
        "total_optimal_km":round(sum(l.get("optimal_distance_km", 0) for l in logs), 2),
        "total_excess_km": round(total_excess, 2),
        "avg_excess_km":   round(total_excess / len(logs), 2),
        "efficiency_pct":  _efficiency_pct(logs),
    }


# ── Optimal distance from volunteer home to task ──────────────────────────────

def compute_optimal_distance(vol_lat: float, vol_lng: float,
                              task_lat: float, task_lng: float) -> float:
    """
    Straight-line (Haversine) distance — the theoretical minimum.
    Real road distance will be higher; this is the baseline for comparison.
    """
    return haversine_km(vol_lat, vol_lng, task_lat, task_lng)


# ── Route optimization suggestion ─────────────────────────────────────────────

def suggest_optimal_assignment(db, task_id: str, config: dict) -> dict:
    """
    For a given task, find which nearby volunteer would minimize total
    travel distance. Returns the optimal volunteer recommendation.
    """
    task = db.tasks.find_one({"_id": ObjectId(task_id)})
    if not task:
        return {"error": "Task not found"}

    radius_km = config.get("DEFAULT_MATCH_RADIUS_KM", 10)
    from utils.helpers import km_to_meters

    candidates = list(db.volunteers.find({
        "status":         "active",
        "active_task_id": None,
        "location": {
            "$near": {
                "$geometry":    {"type": "Point", "coordinates": [task["lng"], task["lat"]]},
                "$maxDistance": km_to_meters(radius_km),
            }
        }
    }))

    if not candidates:
        return {"message": "No volunteers found in range", "optimal_volunteer": None}

    best   = None
    best_d = float("inf")
    for vol in candidates:
        d = haversine_km(vol["lat"], vol["lng"], task["lat"], task["lng"])
        if d < best_d:
            best_d = d
            best   = vol

    return {
        "optimal_volunteer": {
            "id":          str(best["_id"]),
            "name":        best.get("name", ""),
            "distance_km": round(best_d, 2),
        },
        "task_id": task_id,
        "note":    f"Assigning {best['name']} minimizes travel to {round(best_d, 2)} km",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_message(flagged: bool, excess: float, actual: float, optimal: float) -> str:
    if not flagged:
        return (f"Travel was efficient. Actual: {actual:.1f} km, "
                f"Optimal: {optimal:.1f} km (Δ {actual - optimal:.1f} km).")
    return (f"⚠️ Inefficiency detected! Volunteer traveled {actual:.1f} km "
            f"but the optimal route was {optimal:.1f} km "
            f"— {excess:.1f} km of unnecessary travel.")


def _recommend(flagged: bool, excess: float) -> str:
    if not flagged:
        return "No action needed."
    if excess < 10:
        return "Minor inefficiency. Consider reviewing task assignment proximity."
    if excess < 25:
        return ("Significant inefficiency. Review volunteer assignment — "
                "a closer volunteer was likely available.")
    return ("Severe inefficiency. This volunteer was poorly matched geographically. "
            "Enable geo-based auto-matching to prevent this.")


def _efficiency_pct(logs: list) -> float:
    total_optimal = sum(l.get("optimal_distance_km", 0) for l in logs)
    total_actual  = sum(l.get("actual_distance_km",  0) for l in logs)
    if total_actual == 0:
        return 100.0
    return round(min(100.0, total_optimal / total_actual * 100), 1)


def _notify_ngo_of_inefficiency(db, ngo_id: str, log: dict, excess: float):
    from models.schemas import notification_schema
    doc = notification_schema(
        recipient_id   = ngo_id,
        recipient_type = "ngo",
        title          = "⚠️ Travel Inefficiency Detected",
        message        = (f"A volunteer traveled {excess:.1f} km more than necessary "
                          f"for task {log.get('task_id', '')}. "
                          "Consider enabling geo-based auto-matching."),
        notif_type     = "inefficiency",
        reference_id   = log.get("task_id"),
    )
    db.notifications.insert_one(doc)
