"""
services/task_predictor.py
--------------------------
★ Time-to-Failure Task Predictor  (from your notes)

Predicts whether a task is on track, at risk, or critical
based on:
  - Days remaining vs. urgency thresholds
  - Number of volunteers assigned vs. needed
  - Proof-of-work submission status
  - Volunteer trust scores of assigned volunteers
  - Historical completion rates for this task type

Urgency ladder (NGO can override):
  Low    → created with > 7 days to deadline
  Med    → 2-7 days remaining
  Urgent → ≤ 1 day remaining

Risk output:
  on_track | at_risk | critical
"""

from datetime import datetime
from typing import Dict, Any


def predict_task_risk(db, task: Dict, config: Dict) -> Dict[str, Any]:
    """
    Returns a dict:
    {
        "risk_level":    "on_track" | "at_risk" | "critical",
        "days_remaining": int,
        "urgency":       str,
        "reasons":       [str],
        "recommendations": [str],
        "score":          int  (0-100, lower = more risky)
    }
    """
    reasons         = []
    recommendations = []
    risk_score      = 100  # start healthy, subtract for issues

    # ── 1. Days remaining ────────────────────────────────────────────────────
    deadline_str = task.get("deadline", "")
    days_left = _days_left(deadline_str)

    urgency_low    = config.get("URGENCY_LOW_DAYS",    7)
    urgency_med    = config.get("URGENCY_MED_DAYS",    2)
    urgency_urgent = config.get("URGENCY_URGENT_DAYS", 1)

    if days_left <= 0:
        risk_score -= 60
        reasons.append("Deadline has passed or is today")
        recommendations.append("Contact NGO immediately — task is overdue")
    elif days_left <= urgency_urgent:
        risk_score -= 40
        reasons.append(f"Only {days_left} day(s) remaining (URGENT threshold)")
        recommendations.append("Escalate to all available volunteers now")
    elif days_left <= urgency_med:
        risk_score -= 20
        reasons.append(f"{days_left} days remaining (MED threshold)")
        recommendations.append("Check in with assigned volunteers for progress update")
    elif days_left <= urgency_low:
        risk_score -= 5
        reasons.append(f"{days_left} days remaining (LOW-MED boundary)")

    # ── 2. Volunteer assignment gap ──────────────────────────────────────────
    needed   = task.get("volunteers_needed", 1)
    assigned = len(task.get("assigned_volunteers", []))
    gap      = needed - assigned

    if gap > 0:
        penalty = min(30, gap * 10)
        risk_score -= penalty
        reasons.append(f"{gap} volunteer slot(s) still unfilled ({assigned}/{needed})")
        recommendations.append(f"Assign {gap} more volunteer(s) to this task")
    
    if assigned == 0:
        risk_score -= 20
        reasons.append("No volunteers assigned yet")
        recommendations.append("Use AI suggestions to find best-fit volunteers nearby")

    # ── 3. Proof of work status ──────────────────────────────────────────────
    status = task.get("status", "open")
    pow_list = task.get("proof_of_work", [])

    if status == "in_progress" and not pow_list and days_left <= urgency_med:
        risk_score -= 10
        reasons.append("Task is in progress but no proof submitted yet")
        recommendations.append("Remind volunteers to submit proof of work")

    pending_proofs = [p for p in pow_list if p.get("approved") is None]
    if pending_proofs:
        risk_score -= 5
        reasons.append(f"{len(pending_proofs)} proof(s) awaiting NGO review")
        recommendations.append("Review submitted proofs promptly")

    # ── 4. Volunteer trust quality ───────────────────────────────────────────
    from bson import ObjectId
    assigned_ids = task.get("assigned_volunteers", [])
    if assigned_ids:
        volunteers = list(db.volunteers.find(
            {"_id": {"$in": [ObjectId(v) for v in assigned_ids]}},
            {"trust_score": 1}
        ))
        if volunteers:
            avg_trust = sum(v.get("trust_score", 50) for v in volunteers) / len(volunteers)
            if avg_trust < 40:
                risk_score -= 15
                reasons.append(f"Assigned volunteers have low avg trust score ({avg_trust:.0f}/100)")
                recommendations.append("Consider replacing with higher-trust volunteers")
            elif avg_trust < 60:
                risk_score -= 5
                reasons.append(f"Avg volunteer trust score is moderate ({avg_trust:.0f}/100)")

    # ── 5. Historical completion rate for this task type ─────────────────────
    task_type = task.get("task_type", "")
    if task_type:
        total_of_type     = db.tasks.count_documents({"task_type": task_type})
        completed_of_type = db.tasks.count_documents({"task_type": task_type, "status": "completed"})
        if total_of_type > 5:
            completion_rate = completed_of_type / total_of_type
            if completion_rate < 0.5:
                risk_score -= 10
                reasons.append(f"Task type '{task_type}' has a low historical completion rate ({completion_rate:.0%})")
                recommendations.append("Allocate extra resources for this task type")

    # ── Clamp score ──────────────────────────────────────────────────────────
    risk_score = max(0, min(100, risk_score))

    if risk_score >= 70:
        risk_level = "on_track"
    elif risk_score >= 40:
        risk_level = "at_risk"
    else:
        risk_level = "critical"

    # Compute live urgency from deadline (separate from NGO-set urgency)
    computed_urgency = _compute_urgency(days_left, urgency_low, urgency_med, urgency_urgent)

    return {
        "risk_level":       risk_level,
        "risk_score":       risk_score,
        "days_remaining":   days_left,
        "urgency":          task.get("urgency", computed_urgency),
        "computed_urgency": computed_urgency,
        "reasons":          reasons,
        "recommendations":  recommendations,
        "summary":          _summary(risk_level, days_left, assigned, needed),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_left(deadline_str: str) -> int:
    if not deadline_str:
        return 999
    try:
        deadline = datetime.fromisoformat(deadline_str)
        return (deadline - datetime.utcnow()).days
    except Exception:
        return 999


def _compute_urgency(days_left, low_thresh, med_thresh, urgent_thresh):
    if days_left > low_thresh:
        return "low"
    elif days_left > urgent_thresh:
        return "med"
    else:
        return "urgent"


def _summary(risk_level, days_left, assigned, needed):
    msgs = {
        "on_track": f"Task is on track. {days_left} days left, {assigned}/{needed} volunteers assigned.",
        "at_risk":  f"Task needs attention. {days_left} days left, {assigned}/{needed} assigned.",
        "critical": f"⚠️ CRITICAL: {days_left} day(s) left, only {assigned}/{needed} volunteers!",
    }
    return msgs.get(risk_level, "")
