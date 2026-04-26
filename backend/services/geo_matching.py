"""
services/geo_matching.py
------------------------
★ Geo-based Auto Matching  (from your notes)

Core intelligence layer — matches volunteers to tasks using:
  1. Proximity   (MongoDB $near geospatial query)
  2. Skill match (intersection of required vs. volunteer skills)
  3. Trust score (higher trust → higher rank)
  4. Availability
  5. Workload    (no active task = bonus)
  6. Distance    (closer = higher score)

Exposes:
  auto_match_volunteers(db, task_id, config)  → list of volunteer_ids
  get_best_volunteers_for_task(db, task, config, top_n) → scored list
  get_ai_suggestions_for_volunteer(db, volunteer, config) → scored task list
"""

from bson import ObjectId
from utils.helpers import haversine_km, km_to_meters


# ── Weights ─────────────────────────────────────────────────────────────────

W_PROXIMITY   = 40   # 0-40 pts based on distance
W_SKILL       = 25   # 0-25 pts based on skill overlap
W_TRUST       = 20   # 0-20 pts based on trust score (0-100)
W_AVAILABLE   = 10   # 10 pts if volunteer has no active task
W_VERIFIED    = 5    # 5 pts if verified badge

SCORE_MAX = W_PROXIMITY + W_SKILL + W_TRUST + W_AVAILABLE + W_VERIFIED


# ── Main Auto-Match ───────────────────────────────────────────────────────────

def auto_match_volunteers(db, task_id, config, top_n: int = 5):
    """
    Called whenever a new task is posted.
    Finds the best-fit volunteers within the match radius and
    saves them as `auto_matches` on the task document.
    Returns list of volunteer_ids (strings).
    """
    task = db.tasks.find_one({"_id": ObjectId(task_id)})
    if not task:
        return []

    scored = get_best_volunteers_for_task(db, task, config, top_n=top_n)
    matched_ids = [s["volunteer_id"] for s in scored]

    db.tasks.update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"auto_matches": matched_ids}}
    )
    return matched_ids


def get_best_volunteers_for_task(db, task, config, top_n: int = 10):
    """
    Returns a ranked list of dicts, each with:
      volunteer_id, name, score, breakdown, distance_km
    """
    radius_km = config.get("DEFAULT_MATCH_RADIUS_KM", 10)
    task_lat  = task["lat"]
    task_lng  = task["lng"]

    # 1. Geo query — active volunteers within radius with no active task priority
    candidates = list(db.volunteers.find({
        "status": "active",
        "location": {
            "$near": {
                "$geometry":    {"type": "Point", "coordinates": [task_lng, task_lat]},
                "$maxDistance": km_to_meters(radius_km),
            }
        }
    }))

    if not candidates:
        # Expand radius once
        candidates = list(db.volunteers.find({
            "status": "active",
            "location": {
                "$near": {
                    "$geometry":    {"type": "Point", "coordinates": [task_lng, task_lat]},
                    "$maxDistance": km_to_meters(config.get("MAX_MATCH_RADIUS_KM", 50)),
                }
            }
        }))

    required_skills = set(task.get("required_skills", []))
    scored = []

    for vol in candidates:
        score, breakdown = _score_volunteer(vol, task, required_skills, radius_km)
        dist = haversine_km(task_lat, task_lng, vol["lat"], vol["lng"])
        scored.append({
            "volunteer_id":  str(vol["_id"]),
            "name":          vol.get("name", ""),
            "phone":         vol.get("phone", ""),
            "trust_score":   vol.get("trust_score", 50),
            "verified_badge":vol.get("verified_badge", False),
            "distance_km":   round(dist, 2),
            "score":         score,
            "score_pct":     round(score / SCORE_MAX * 100, 1),
            "breakdown":     breakdown,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def _score_volunteer(vol, task, required_skills: set, radius_km: float):
    breakdown = {}

    # ── Proximity score (40 pts) ──────────────────────────────────────────────
    dist = haversine_km(task["lat"], task["lng"], vol["lat"], vol["lng"])
    # Linear decay: 0 km → 40pts, radius_km+ → 0pts
    proximity_score = max(0.0, W_PROXIMITY * (1 - dist / max(radius_km, 1)))
    breakdown["proximity"] = round(proximity_score, 1)

    # ── Skill match score (25 pts) ────────────────────────────────────────────
    vol_skills = set(vol.get("skills", []))
    if required_skills:
        overlap     = len(required_skills & vol_skills)
        skill_score = (overlap / len(required_skills)) * W_SKILL
    else:
        skill_score = W_SKILL * 0.5    # no requirements = neutral
    breakdown["skill"] = round(skill_score, 1)

    # ── Trust score (20 pts) ──────────────────────────────────────────────────
    trust = min(100, max(0, vol.get("trust_score", 50)))
    trust_score = (trust / 100) * W_TRUST
    breakdown["trust"] = round(trust_score, 1)

    # ── Availability / workload (10 pts) ──────────────────────────────────────
    if not vol.get("active_task_id"):
        avail_score = W_AVAILABLE
    else:
        avail_score = 0
    breakdown["availability"] = avail_score

    # ── Verified badge bonus (5 pts) ──────────────────────────────────────────
    verified_score = W_VERIFIED if vol.get("verified_badge") else 0
    breakdown["verified"] = verified_score

    total = proximity_score + skill_score + trust_score + avail_score + verified_score
    return round(total, 2), breakdown


# ── AI Suggestions for Volunteer (tasks they'd be good at) ───────────────────

def get_ai_suggestions_for_volunteer(db, volunteer, config, top_n: int = 5):
    """
    Given a volunteer, find and rank the open tasks that best suit them.
    Mirror of get_best_volunteers_for_task but from the volunteer's perspective.
    """
    radius_km = config.get("DEFAULT_MATCH_RADIUS_KM", 10)
    vol_lat   = volunteer["lat"]
    vol_lng   = volunteer["lng"]

    # Geo query for nearby open tasks
    open_tasks = list(db.tasks.find({
        "status":   "open",
        "location": {
            "$near": {
                "$geometry":    {"type": "Point", "coordinates": [vol_lng, vol_lat]},
                "$maxDistance": km_to_meters(radius_km),
            }
        }
    }))

    vol_skills = set(volunteer.get("skills", []))

    urgency_weight = {"urgent": 15, "med": 8, "low": 0}
    scored = []

    for task in open_tasks:
        dist  = haversine_km(vol_lat, vol_lng, task["lat"], task["lng"])
        prox  = max(0.0, 40 * (1 - dist / max(radius_km, 1)))

        req   = set(task.get("required_skills", []))
        skill = (len(req & vol_skills) / len(req) * 25) if req else 12.5

        urg   = urgency_weight.get(task.get("urgency", "low"), 0)
        total = round(prox + skill + urg, 2)

        scored.append({
            **{k: str(v) if isinstance(v, ObjectId) else v
               for k, v in task.items() if k != "_id"},
            "_id":         str(task["_id"]),
            "distance_km": round(dist, 2),
            "match_score": total,
            "match_pct":   round(total / 80 * 100, 1),  # 80 = max possible
        })

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:top_n]
