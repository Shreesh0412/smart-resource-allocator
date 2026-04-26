"""
routes/task_routes.py
---------------------
Shared task endpoints accessible by both volunteers and NGOs:
  - GET a single task
  - Search tasks (text / geo / filter)
  - Task status lifecycle updates
  - Time-to-failure prediction info per task
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from bson import ObjectId

from utils.helpers import serialize, serialize_list, to_oid, haversine_km
from utils.decorators import any_authenticated, ngo_required

task_bp = Blueprint("tasks", __name__)


# ── Get Single Task ───────────────────────────────────────────────────────────

@task_bp.route("/<task_id>", methods=["GET"])
@any_authenticated
def get_task(task_id):
    db   = current_app.db
    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Enrich with urgency prediction
    from services.task_predictor import predict_task_risk
    task["prediction"] = predict_task_risk(db, task, current_app.config)

    return jsonify({"task": serialize(task)}), 200


# ── Search Tasks ──────────────────────────────────────────────────────────────

@task_bp.route("/search", methods=["GET"])
@any_authenticated
def search_tasks():
    """
    Full search with optional geo filter, text filter, and urgency filter.
    Supports: ?q=text&lat=&lng=&radius_km=&urgency=&task_type=&status=&page=&per_page=
    """
    db       = current_app.db
    q        = request.args.get("q")
    lat      = request.args.get("lat", type=float)
    lng      = request.args.get("lng", type=float)
    radius   = request.args.get("radius_km", default=current_app.config["DEFAULT_MATCH_RADIUS_KM"], type=float)
    urgency  = request.args.get("urgency")
    ttype    = request.args.get("task_type")
    status   = request.args.get("status", "open")
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = {}

    if status:
        query["status"] = status

    if urgency:
        query["urgency"] = urgency

    if ttype:
        query["task_type"] = ttype

    if q:
        query["$text"] = {"$search": q}

    if lat and lng:
        query["location"] = {
            "$near": {
                "$geometry":    {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": radius * 1000,
            }
        }

    tasks = list(
        db.tasks.find(query)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    if lat and lng:
        for t in tasks:
            t["distance_km"] = round(haversine_km(lat, lng, t["lat"], t["lng"]), 2)

    return jsonify({
        "tasks":    serialize_list(tasks),
        "page":     page,
        "per_page": per_page,
    }), 200


# ── All Tasks Summary (with urgency & predictor) ──────────────────────────────

@task_bp.route("/urgency-board", methods=["GET"])
@any_authenticated
def urgency_board():
    """
    Returns tasks bucketed by urgency with predictor risk flags.
    Useful for the NGO dashboard overview.
    """
    db = current_app.db
    identity = get_jwt_identity()

    query = {"status": {"$in": ["open", "assigned", "in_progress"]}}

    # If NGO, filter to own tasks only
    if identity.get("type") == "ngo":
        query["ngo_id"] = identity["id"]

    from services.task_predictor import predict_task_risk

    buckets = {"urgent": [], "med": [], "low": []}
    for task in db.tasks.find(query):
        prediction = predict_task_risk(db, task, current_app.config)
        task["prediction"] = prediction
        buckets[task.get("urgency", "low")].append(serialize(task))

    return jsonify({"urgency_board": buckets}), 200


# ── Mark Task Complete (by NGO) ───────────────────────────────────────────────

@task_bp.route("/<task_id>/complete", methods=["POST"])
@ngo_required
def mark_complete(task_id):
    db       = current_app.db
    identity = get_jwt_identity()
    nid      = identity["id"]

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found or not yours"}), 404

    data  = request.get_json() or {}
    notes = data.get("completion_notes", "")

    from utils.helpers import days_remaining
    from models.schemas import utcnow

    deadline = task.get("deadline", "")
    is_ontime = days_remaining(deadline) >= 0

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {
            "status":           "completed",
            "completion_notes": notes,
            "completed_at":     utcnow(),
            "updated_at":       utcnow(),
        }}
    )
    db.ngos.update_one({"_id": ObjectId(nid)},
                        {"$inc": {"total_tasks_completed": 1, "active_volunteers": -1}})

    # Update trust score for all assigned volunteers
    from services.trust_score import update_trust_score
    for vol_id in task.get("assigned_volunteers", []):
        event = "ontime" if is_ontime else "late"
        update_trust_score(db, str(vol_id), event=event)
        db.volunteers.update_one(
            {"_id": ObjectId(vol_id)},
            {
                "$inc": {
                    "total_tasks_done": 1,
                    "tasks_on_time" if is_ontime else "tasks_late": 1
                },
                "$set": {"active_task_id": None},
                "$push": {"task_history": task_id}
            }
        )

    return jsonify({"message": "Task marked as completed"}), 200


# ── Cancel Task ───────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>/cancel", methods=["POST"])
@ngo_required
def cancel_task(task_id):
    db       = current_app.db
    identity = get_jwt_identity()
    nid      = identity["id"]
    data     = request.get_json() or {}

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from models.schemas import utcnow
    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {"status": "cancelled", "updated_at": utcnow(),
                  "completion_notes": data.get("reason", "")}}
    )

    # Notify assigned volunteers
    from models.schemas import notification_schema
    for vol_id in task.get("assigned_volunteers", []):
        doc = notification_schema(
            str(vol_id), "volunteer",
            "Task Cancelled",
            f"Task '{task['title']}' has been cancelled by the NGO.",
            "task_cancelled", task_id
        )
        db.notifications.insert_one(doc)
        db.volunteers.update_one({"_id": ObjectId(vol_id)},
                                  {"$set": {"active_task_id": None}})

    return jsonify({"message": "Task cancelled"}), 200


# ── Delete Task ───────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>", methods=["DELETE"])
@ngo_required
def delete_task(task_id):
    db       = current_app.db
    identity = get_jwt_identity()
    nid      = identity["id"]

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if task["status"] in ("assigned", "in_progress"):
        return jsonify({"error": "Cannot delete an active task. Cancel it first."}), 400

    db.tasks.delete_one({"_id": to_oid(task_id)})
    return jsonify({"message": "Task deleted"}), 200
