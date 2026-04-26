"""
services/trust_score.py
-----------------------
★ Confidence Score / Trust Score of Volunteer / Verified Badge System
  (from your notes)

Trust Score (0–100):
  - Starts at 50
  - Earned by: completing tasks, good reviews, on-time delivery, verification
  - Lost by:   late tasks, rejection, poor reviews

Confidence Score (0–100):
  - Derived from review consistency + task success rate

Verified Badge:
  - Admin grants after manual vetting (ID + background check)
  - Gives a +20 trust boost and is displayed prominently

Events and their point deltas:
  completed  +10   (task approved by NGO)
  ontime     +3    (completed before deadline)
  late       -4    (completed after deadline)
  rejected   -2    (rejected an assigned task)
  reviewed   ±5    (based on rating 1-5)
  verified   +20   (admin verified badge)
"""

from bson import ObjectId
from utils.helpers import compute_avg_rating
from models.schemas import utcnow


# ── Event deltas ──────────────────────────────────────────────────────────────

EVENT_DELTAS = {
    "completed": 10,
    "ontime":     3,
    "late":      -4,
    "rejected":  -2,
    "verified":  20,
}


def update_trust_score(db, volunteer_id: str, event: str, rating: int = None) -> int:
    """
    Applies the appropriate delta to a volunteer's trust_score.
    For 'reviewed' event, delta is scaled from the 1-5 rating:
      rating 5 → +5, rating 4 → +3, rating 3 → 0, rating 2 → -2, rating 1 → -4

    Returns the new trust_score.
    """
    vol = db.volunteers.find_one({"_id": ObjectId(volunteer_id)})
    if not vol:
        return 0

    current_trust      = vol.get("trust_score",      50)
    current_confidence = vol.get("confidence_score", 50)

    if event == "reviewed" and rating is not None:
        delta = _rating_to_delta(rating)
    else:
        delta = EVENT_DELTAS.get(event, 0)

    new_trust = max(0, min(100, current_trust + delta))

    # Recompute confidence score from reviews + completion metrics
    new_confidence = _compute_confidence(vol)

    db.volunteers.update_one(
        {"_id": ObjectId(volunteer_id)},
        {"$set": {
            "trust_score":      new_trust,
            "confidence_score": new_confidence,
            "updated_at":       utcnow(),
        }}
    )
    return new_trust


def _rating_to_delta(rating: int) -> int:
    """Convert a 1-5 star rating to a trust delta."""
    mapping = {5: 5, 4: 3, 3: 0, 2: -2, 1: -4}
    return mapping.get(rating, 0)


def _compute_confidence(vol: dict) -> int:
    """
    Confidence score based on:
      - Average review rating (40%)
      - On-time task rate (40%)
      - Task completion rate (20%)
    Clamped 0-100.
    """
    reviews      = vol.get("reviews", [])
    total_done   = vol.get("total_tasks_done", 0)
    tasks_ontime = vol.get("tasks_on_time", 0)
    tasks_late   = vol.get("tasks_late", 0)
    tasks_rej    = vol.get("tasks_rejected", 0)

    # Review factor (0-40)
    avg_rating = compute_avg_rating(reviews)
    review_factor = (avg_rating / 5) * 40

    # On-time factor (0-40)
    total_attempted = total_done + tasks_late + tasks_rej
    if total_attempted > 0:
        ontime_rate = tasks_ontime / total_attempted
    else:
        ontime_rate = 0.5
    ontime_factor = ontime_rate * 40

    # Completion factor (0-20)
    if total_attempted > 0:
        completion_rate = total_done / total_attempted
    else:
        completion_rate = 0.5
    completion_factor = completion_rate * 20

    confidence = review_factor + ontime_factor + completion_factor
    return max(0, min(100, int(confidence)))


# ── Volunteer Reputation Profile ──────────────────────────────────────────────

def build_reputation_profile(db, volunteer_id: str) -> dict:
    """
    Returns full reputation snapshot for a volunteer.
    Used on their public profile and the NGO volunteer-selection page.
    """
    vol = db.volunteers.find_one({"_id": ObjectId(volunteer_id)})
    if not vol:
        return {}

    total_done    = vol.get("total_tasks_done", 0)
    tasks_ontime  = vol.get("tasks_on_time", 0)
    tasks_late    = vol.get("tasks_late", 0)
    tasks_rej     = vol.get("tasks_rejected", 0)
    total_att     = total_done + tasks_late + tasks_rej or 1

    return {
        "volunteer_id":    str(vol["_id"]),
        "name":            vol.get("name", ""),
        "trust_score":     vol.get("trust_score", 50),
        "confidence_score":vol.get("confidence_score", 50),
        "avg_rating":      vol.get("avg_rating", 0.0),
        "total_reviews":   len(vol.get("reviews", [])),
        "is_verified":     vol.get("is_verified", False),
        "verified_badge":  vol.get("verified_badge", False),
        "stats": {
            "total_tasks_done":  total_done,
            "tasks_on_time":     tasks_ontime,
            "tasks_late":        tasks_late,
            "tasks_rejected":    tasks_rej,
            "ontime_rate_pct":   round(tasks_ontime / total_att * 100, 1),
            "completion_rate_pct": round(total_done / total_att * 100, 1),
        },
        "badge_label":     _badge_label(vol),
        "recent_reviews":  vol.get("reviews", [])[-5:],   # last 5
    }


def _badge_label(vol: dict) -> str:
    """Human-readable reputation tier."""
    trust = vol.get("trust_score", 50)
    verified = vol.get("verified_badge", False)

    if verified and trust >= 80:
        return "⭐ Verified Champion"
    elif verified:
        return "✅ Verified Volunteer"
    elif trust >= 80:
        return "🏆 Top Volunteer"
    elif trust >= 60:
        return "🌟 Trusted Volunteer"
    elif trust >= 40:
        return "🙂 Active Volunteer"
    else:
        return "🆕 New Volunteer"
