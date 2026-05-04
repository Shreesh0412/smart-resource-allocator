"""
routes/task_routes.py
FIXES:
  B11 — urgency_board used to call predict_task_risk() serially for every task,
        making one blocking Gemini API call per task (N+1 pattern). With 20
        tasks this means 20 sequential HTTP calls, causing timeouts. Fixed to
        use ThreadPoolExecutor so all predictions run concurrently, capping
        wall-clock time to roughly one API call's latency regardless of N.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity, get_jwt
from bson import ObjectId

from utils.helpers import serialize, serialize_list, to_oid, haversine_km, is_past_deadline
from utils.decorators import any_authenticated, ngo_required
from models.schemas import utcnow

task_bp = Blueprint("tasks", __name__)


# ── Single Task ───────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>", methods=["GET"])
@any_authenticated
def get_task(task_id):
    db   = current_app.db
    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from services.task_predictor import predict_task_risk
    task["prediction"] = predict_task_risk(db, task, current_app.config)

    return jsonify({"task": serialize(task)}), 200


# ── Search Tasks ──────────────────────────────────────────────────────────────

@task_bp.route("/search", methods=["GET"])
@any_authenticated
def search_tasks():
    db       = current_app.db
    q        = request.args.get("q")
    lat      = request.args.get("lat", type=float)
    lng      = request.args.get("lng", type=float)
    radius   = request.args.get("radius_km",
                                default=current_app.config["DEFAULT_MATCH_RADIUS_KM"],
                                type=float)
    urgency  = request.args.get("urgency")
    ttype    = request.args.get("task_type")
    status   = request.args.get("status", "open")
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = {}
    if status:  query["status"]    = status
    if urgency: query["urgency"]   = urgency
    if ttype:   query["task_type"] = ttype
    if q:       query["$text"]     = {"$search": q}

    if lat is not None and lng is not None:
        query["location"] = {
            "$near": {
                "$geometry":    {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": radius * 1000,
            }
        }

    tasks = list(db.tasks.find(query).skip((page - 1) * per_page).limit(per_page))

    if lat is not None and lng is not None:
        for t in tasks:
            t["distance_km"] = round(haversine_km(lat, lng, t["lat"], t["lng"]), 2)

    return jsonify({"tasks": serialize_list(tasks), "page": page, "per_page": per_page}), 200


# ── Urgency Board ─────────────────────────────────────────────────────────────

@task_bp.route("/urgency-board", methods=["GET"])
@any_authenticated
def urgency_board():
    db        = current_app.db
    user_id   = get_jwt_identity()
    claims    = get_jwt()
    user_type = claims.get("user_type")

    query = {"status": {"$in": ["open", "assigned", "in_progress"]}}
    if user_type == "ngo":
        query["ngo_id"] = user_id

    tasks = list(db.tasks.find(query))

    from services.task_predictor import predict_task_risk

    # FIX B11: Run all Gemini predictions concurrently instead of serially.
    # The old code called predict_task_risk() in a for-loop, making one blocking
    # HTTP call to Gemini per task (N+1). With ThreadPoolExecutor the calls run
    # in parallel, reducing total latency from N×T to roughly T for any board size.
    # We cap workers at 10 to avoid hammering the Gemini API rate limit.
    cfg = current_app.config

    def _predict(task):
        return task, predict_task_risk(db, task, cfg)

    predictions = {}
    with ThreadPoolExecutor(max_workers=min(10, len(tasks) or 1)) as executor:
        futures = {executor.submit(_predict, t): t for t in tasks}
        for future in as_completed(futures):
            try:
                task, pred = future.result()
                predictions[str(task["_id"])] = pred
            except Exception:
                pass

    buckets = {"urgent": [], "med": [], "low": []}
    for task in tasks:
        task["prediction"] = predictions.get(str(task["_id"]), {
            "risk_level": "on_track", "risk_score": 10, "summary": "Unknown"
        })
        bucket = task.get("urgency", "low")
        if bucket not in buckets:
            bucket = "low"
        buckets[bucket].append(serialize(task))

    return jsonify({"urgency_board": buckets}), 200


# ── Mark Complete ─────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>/complete", methods=["POST"])
@ngo_required
def mark_complete(task_id):
    db   = current_app.db
    nid  = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found or not yours"}), 404

    if task.get("status") == "completed":
        return jsonify({"message": "Task already completed"}), 200

    is_ontime = not is_past_deadline(task.get("deadline", ""))

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {
            "status":           "completed",
            "completion_notes": data.get("completion_notes", ""),
            "completed_at":     utcnow(),
            "updated_at":       utcnow(),
        }}
    )
    db.ngos.update_one({"_id": ObjectId(nid)}, {"$inc": {"total_tasks_completed": 1}})

    from services.trust_score import update_trust_score
    assigned_ids = [str(v) for v in task.get("assigned_volunteers", [])]
    inc_field    = "tasks_on_time" if is_ontime else "tasks_late"

    for vol_id in assigned_ids:
        # FIX #7: Fire "completed" (+10) AND "ontime"/"late" (±3/−4).
        # Previously only ontime/late was fired so volunteers never received
        # their +10 trust points for completing a task.
        update_trust_score(db, vol_id, event="completed")
        event = "ontime" if is_ontime else "late"
        update_trust_score(db, vol_id, event=event)
        db.volunteers.update_one(
            {"_id": ObjectId(vol_id)},
            {
                "$inc":  {"total_tasks_done": 1, inc_field: 1},
                "$set":  {"active_task_id": None},
                "$push": {"task_history": task_id}
            }
        )

    return jsonify({"message": "Task marked as completed"}), 200


# ── Cancel Task ───────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>/cancel", methods=["POST"])
@ngo_required
def cancel_task(task_id):
    db   = current_app.db
    nid  = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from models.schemas import notification_schema
    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {"status": "cancelled", "updated_at": utcnow(),
                  "completion_notes": data.get("reason", "")}}
    )

    for vol_id in task.get("assigned_volunteers", []):
        doc = notification_schema(
            str(vol_id), "volunteer",
            "Task Cancelled",
            f"Task '{task['title']}' has been cancelled by the NGO.",
            "task_cancelled", task_id
        )
        db.notifications.insert_one(doc)
        db.volunteers.update_one(
            {"_id": ObjectId(vol_id)},
            {"$set": {"active_task_id": None}}
        )

    return jsonify({"message": "Task cancelled"}), 200


# ── Delete Task ───────────────────────────────────────────────────────────────

@task_bp.route("/<task_id>", methods=["DELETE"])
@ngo_required
def delete_task(task_id):
    db  = current_app.db
    nid = get_jwt_identity()

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if task["status"] in ("assigned", "in_progress"):
        return jsonify({"error": "Cannot delete an active task. Cancel it first."}), 400

    db.tasks.delete_one({"_id": to_oid(task_id)})
    return jsonify({"message": "Task deleted"}), 200
