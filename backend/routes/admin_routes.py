"""
routes/admin_routes.py
FIXES:
  B5 — homepage_stats completed_today was always 0 because today_start used
       datetime.now(timezone.utc).isoformat() which produces a timezone-aware
       string like '2024-01-01T00:00:00+00:00', but completed_at is stored by
       utcnow() as a naive string like '2024-01-01T12:00:00'. The alphabetic
       string comparison via $gte always failed. Fixed to use naive UTC
       consistently, matching how analytics.py does it.
"""

from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId

from utils.decorators import admin_required
from utils.helpers import serialize, serialize_list, to_oid
from models.schemas import utcnow
from services.trust_score import update_trust_score

admin_bp = Blueprint("admin", __name__)


# ── Verify a Volunteer (grant badge) ─────────────────────────────────────────

@admin_bp.route("/volunteers/<volunteer_id>/verify", methods=["POST"])
@admin_required
def verify_volunteer(volunteer_id):
    db  = current_app.db
    cfg = current_app.config

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    db.volunteers.update_one(
        {"_id": to_oid(volunteer_id)},
        {"$set": {"is_verified": True, "verified_badge": True, "updated_at": utcnow()}}
    )
    update_trust_score(db, volunteer_id, event="verified")

    return jsonify({"message": f"Volunteer {vol['name']} verified and badge granted"}), 200


# ── Verify an NGO ─────────────────────────────────────────────────────────────

@admin_bp.route("/ngos/<ngo_id>/verify", methods=["POST"])
@admin_required
def verify_ngo(ngo_id):
    db = current_app.db
    ngo = db.ngos.find_one({"_id": to_oid(ngo_id)})
    if not ngo:
        return jsonify({"error": "NGO not found"}), 404

    db.ngos.update_one(
        {"_id": to_oid(ngo_id)},
        {"$set": {"is_verified": True, "updated_at": utcnow()}}
    )
    return jsonify({"message": f"NGO {ngo['name']} verified"}), 200


# ── Ban / Unban Volunteer ─────────────────────────────────────────────────────

@admin_bp.route("/volunteers/<volunteer_id>/ban", methods=["POST"])
@admin_required
def ban_volunteer(volunteer_id):
    db     = current_app.db
    data   = request.get_json() or {}
    action = data.get("action", "ban")   # "ban" | "unban"

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    new_status = "banned" if action == "ban" else "active"
    db.volunteers.update_one(
        {"_id": to_oid(volunteer_id)},
        {"$set": {"status": new_status, "updated_at": utcnow()}}
    )
    return jsonify({"message": f"Volunteer {action}ned", "status": new_status}), 200


# ── Platform-wide Analytics ───────────────────────────────────────────────────

@admin_bp.route("/analytics", methods=["GET"])
@admin_required
def platform_analytics():
    db = current_app.db

    total_volunteers  = db.volunteers.count_documents({})
    total_ngos        = db.ngos.count_documents({})
    total_tasks       = db.tasks.count_documents({})
    open_tasks        = db.tasks.count_documents({"status": "open"})
    completed_tasks   = db.tasks.count_documents({"status": "completed"})
    urgent_tasks      = db.tasks.count_documents({"urgency": "urgent", "status": "open"})
    total_reports     = db.problem_reports.count_documents({})
    pending_reports   = db.problem_reports.count_documents({"status": "pending"})
    total_travel_logs = db.travel_logs.count_documents({})
    flagged_travels   = db.travel_logs.count_documents({"flagged": True})

    top_volunteers = list(db.volunteers.find(
        {}, {"name": 1, "trust_score": 1, "total_tasks_done": 1, "verified_badge": 1}
    ).sort("trust_score", -1).limit(10))

    task_type_pipeline = [
        {"$group": {"_id": "$task_type", "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}}
    ]
    task_types = list(db.tasks.aggregate(task_type_pipeline))
    for t in task_types:
        t["task_type"] = t.pop("_id")

    return jsonify({
        "volunteers": total_volunteers,
        "ngos":       total_ngos,
        "tasks": {
            "total":     total_tasks,
            "open":      open_tasks,
            "completed": completed_tasks,
            "urgent":    urgent_tasks,
        },
        "problem_reports": {
            "total":   total_reports,
            "pending": pending_reports,
        },
        "travel": {
            "total_logs": total_travel_logs,
            "flagged":    flagged_travels,
        },
        "top_volunteers": serialize_list(top_volunteers),
        "tasks_by_type":  task_types,
    }), 200


# ── All Flagged Inefficiency Reports ─────────────────────────────────────────

@admin_bp.route("/inefficiency-flags", methods=["GET"])
@admin_required
def all_inefficiency_flags():
    db   = current_app.db
    logs = list(db.travel_logs.find({"flagged": True}).sort("excess_km", -1).limit(200))
    return jsonify({"flagged_logs": serialize_list(logs)}), 200


# ── All Problem Reports ───────────────────────────────────────────────────────

@admin_bp.route("/reports", methods=["GET"])
@admin_required
def all_reports():
    db     = current_app.db
    status = request.args.get("status")
    page   = int(request.args.get("page", 1))

    query = {}
    if status:
        query["status"] = status

    reports = list(
        db.problem_reports.find(query)
        .sort("created_at", -1)
        .skip((page - 1) * 50)
        .limit(50)
    )
    return jsonify({"reports": serialize_list(reports)}), 200


# ── Public Homepage Stats ─────────────────────────────────────────────────────

@admin_bp.route("/homepage-stats", methods=["GET"])
def homepage_stats():
    """
    Public stats for the landing page hero cards.
    No auth required so the homepage can render counts immediately.
    """
    db = current_app.db

    urgent_tasks = db.tasks.count_documents({
        "urgency": "urgent",
        "status":  {"$in": ["open", "assigned", "in_progress"]},
    })

    active_volunteers = db.volunteers.count_documents({
        "status": {"$nin": ["banned", "inactive"]},
    })

    # FIX B5: Use naive UTC datetime and format as ISO string without timezone
    # suffix, matching how utcnow() stores completed_at in the database.
    # The old code used datetime.now(timezone.utc).isoformat() which produced
    # '2024-01-01T00:00:00+00:00' — a timezone-aware string that never matched
    # the naive '2024-01-01T12:00:00' strings stored by utcnow(), so
    # completed_today was always 0.
    from datetime import datetime
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    completed_today = db.tasks.count_documents({
        "status":       "completed",
        "completed_at": {"$gte": today_start},
    })

    return jsonify({
        "urgent_tasks":       urgent_tasks,
        "active_volunteers":  active_volunteers,
        "completed_today":    completed_today,
    }), 200


# ── Leaderboard ───────────────────────────────────────────────────────────────

@admin_bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    """Public leaderboard — no auth needed."""
    db  = current_app.db
    top = list(db.volunteers.find(
        {"status": "active"},
        {"name": 1, "trust_score": 1, "total_tasks_done": 1,
         "avg_rating": 1, "verified_badge": 1}
    ).sort("trust_score", -1).limit(20))
    return jsonify({"leaderboard": serialize_list(top)}), 200
