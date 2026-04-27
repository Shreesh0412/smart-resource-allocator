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

    # 1. Geo query — active volunteers within radius
    candidates = list(db.volunteers.find({
        "status": "active",
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [task_lng, task_lat]},
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
                    "$geometry": {"type": "Point", "coordinates": [task_lng, task_lat]},
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
            "volunteer_id": str(vol["_id"]),
            "name": vol.get("name", ""),
            "phone": vol.get("phone", ""),
            "trust_score": vol.get("trust_score", 50),
            "verified_badge": vol.get("verified_badge", False),
            "distance_km": round(dist, 2),
            "score": score,
            "score_pct": round(score / SCORE_MAX * 100, 1),
            "breakdown": breakdown,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def _score_volunteer(vol, task, required_skills: set, radius_km: float):
    breakdown = {}

    # ── Proximity score (40 pts) ──────────────────────────────────────────────
    dist = haversine_km(task["lat"], task["lng"], vol["lat"], vol["lng"])
    proximity_score = max(0.0, W_PROXIMITY * (1 - dist / max(radius_km, 1)))
    breakdown["proximity"] = round(proximity_score, 1)

    # ── Skill match score (25 pts) ────────────────────────────────────────────
    vol_skills = set(vol.get("skills", []))
    if required_skills:
        overlap = len(required_skills & vol_skills)
        skill_score = (overlap / len(required_skills)) * W_SKILL
    else:
        skill_score = W_SKILL * 0.5
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
    Includes fallbacks so the UI still shows useful tasks when geo filters
    or skill filters are too strict.
    """
    radius_km = config.get("DEFAULT_MATCH_RADIUS_KM", 10)
    max_radius_km = config.get("MAX_MATCH_RADIUS_KM", 50)

    vol_lat = volunteer.get("lat")
    vol_lng = volunteer.get("lng")

    # If the volunteer has no location yet, still return open tasks with neutral scoring.
    if vol_lat is None or vol_lng is None:
        fallback_tasks = list(db.tasks.find({"status": "open"}).limit(top_n))
        return [_serialize_task_with_neutral_score(t) for t in fallback_tasks]

    vol_skills = set(volunteer.get("skills", []))
    urgency_weight = {"urgent": 15, "med": 8, "low": 0}
    scored = []

    def _score_tasks(tasks, use_distance_filter=True):
        local_scored = []
        for task in tasks:
            try:
                task_lat = task.get("lat")
                task_lng = task.get("lng")
                if task_lat is None or task_lng is None:
                    continue

                dist = haversine_km(vol_lat, vol_lng, task_lat, task_lng)

                if use_distance_filter and dist > max_radius_km:
                    continue

                prox = max(0.0, 40 * (1 - dist / max(radius_km, 1)))

                req = set(task.get("required_skills", []))
                if req:
                    skill = (len(req & vol_skills) / len(req)) * 25
                else:
                    skill = 12.5

                urg = urgency_weight.get(task.get("urgency", "low"), 0)
                total = round(prox + skill + urg, 2)

                local_scored.append({
                    **{
                        k: str(v) if isinstance(v, ObjectId) else v
                        for k, v in task.items()
                        if k != "_id"
                    },
                    "_id": str(task["_id"]),
                    "distance_km": round(dist, 2),
                    "match_score": total,
                    "match_pct": round(total / 80 * 100, 1),  # 80 = practical max
                })
            except Exception:
                continue
        return local_scored

    # 1) Nearby open tasks via geo query
    nearby_tasks = list(db.tasks.find({
        "status": "open",
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [vol_lng, vol_lat]},
                "$maxDistance": km_to_meters(radius_km),
            }
        }
    }))

    scored = _score_tasks(nearby_tasks)

    # 2) Expand radius once if nothing matched
    if not scored:
        expanded_tasks = list(db.tasks.find({
            "status": "open",
            "location": {
                "$near": {
                    "$geometry": {"type": "Point", "coordinates": [vol_lng, vol_lat]},
                    "$maxDistance": km_to_meters(max_radius_km),
                }
            }
        }))
        scored = _score_tasks(expanded_tasks)

    # 3) Final fallback: all open tasks, even if geo index/matching gives nothing
    if not scored:
        all_open_tasks = list(db.tasks.find({"status": "open"}).limit(50))
        scored = _score_tasks(all_open_tasks, use_distance_filter=False)

    # 4) Absolute fallback: if still nothing, return a neutral task list for the UI
    if not scored:
        fallback_tasks = list(db.tasks.find({"status": "open"}).limit(top_n))
        return [_serialize_task_with_neutral_score(t) for t in fallback_tasks]

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:top_n]


def _serialize_task_with_neutral_score(task):
    """
    Fallback serializer for tasks when scoring is unavailable.
    """
    data = {
        k: str(v) if isinstance(v, ObjectId) else v
        for k, v in task.items()
        if k != "_id"
    }
    data["_id"] = str(task["_id"])
    data["distance_km"] = None
    data["match_score"] = 50
    data["match_pct"] = 62.5
    return data
