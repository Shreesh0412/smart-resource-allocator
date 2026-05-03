"""
routes/volunteer_routes.py
FIXES:
  B3 — log_travel now validates all required fields before accessing them,
       returning 400 instead of crashing with a KeyError → 500.
  B4 — task_history now uses to_oid() and filters out None values so a
       corrupt ObjectId in task_history array can't crash the endpoint.
  S6 — upload_proof now validates file magic bytes (not just extension)
       so renaming malware.php → malware.jpg no longer bypasses the check.
"""

import os
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from bson import ObjectId
from werkzeug.utils import secure_filename

from utils.decorators import volunteer_required
from utils.helpers import serialize, serialize_list, to_oid, allowed_file, haversine_km
from models.schemas import utcnow, geo_point

volunteer_bp = Blueprint("volunteer", __name__)


def _current_volunteer():
    """Returns (volunteer_doc, volunteer_id_string)."""
    vid = get_jwt_identity()
    db  = current_app.db
    doc = db.volunteers.find_one({"_id": ObjectId(vid)})
    return doc, vid


# ── S6: Magic bytes validator ─────────────────────────────────────────────────
# Maps allowed extensions to their known magic byte signatures.
# This prevents file type spoofing (e.g. malware.php renamed to malware.jpg).
_MAGIC_BYTES = {
    "jpg":  [(0, b"\xff\xd8\xff")],
    "jpeg": [(0, b"\xff\xd8\xff")],
    "png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "gif":  [(0, b"GIF87a"), (0, b"GIF89a")],
    "pdf":  [(0, b"%PDF")],
    # MP4 / MOV have variable headers — check ftyp box at offset 4
    "mp4":  [(4, b"ftyp")],
    "mov":  [(4, b"ftyp"), (4, b"moov"), (4, b"wide")],
}

def _is_valid_file_content(file_storage, ext: str) -> bool:
    """
    Reads the first 12 bytes of an uploaded file and checks them against
    known magic byte signatures for the declared extension.
    Falls back to True for extensions without a defined signature so that
    unrecognised-but-allowed types are not silently blocked.
    """
    signatures = _MAGIC_BYTES.get(ext.lower())
    if not signatures:
        return True  # no signature defined — allow it

    header = file_storage.stream.read(12)
    file_storage.stream.seek(0)  # rewind for subsequent save()

    for offset, sig in signatures:
        if header[offset: offset + len(sig)] == sig:
            return True
    return False


# ── Profile ───────────────────────────────────────────────────────────────────

@volunteer_bp.route("/profile", methods=["GET"])
@volunteer_required
def get_profile():
    volunteer, _ = _current_volunteer()
    doc = serialize(volunteer)
    doc.pop("password_hash", None)
    return jsonify(doc), 200


@volunteer_bp.route("/profile", methods=["PUT"])
@volunteer_required
def update_profile():
    db = current_app.db
    volunteer, vid = _current_volunteer()

    data    = request.get_json() or {}
    allowed = ["name", "phone", "skills", "availability", "whatsapp_opt_in"]
    update  = {k: data[k] for k in allowed if k in data}

    if "lat" in data and "lng" in data:
        update["lat"]      = float(data["lat"])
        update["lng"]      = float(data["lng"])
        update["location"] = geo_point(float(data["lat"]), float(data["lng"]))

    update["updated_at"] = utcnow()
    db.volunteers.update_one({"_id": ObjectId(vid)}, {"$set": update})
    return jsonify({"message": "Profile updated"}), 200


# ── Location Update ───────────────────────────────────────────────────────────

@volunteer_bp.route("/location", methods=["POST"])
@volunteer_required
def update_location():
    db   = current_app.db
    _, vid = _current_volunteer()
    data = request.get_json() or {}

    lat = float(data.get("lat", 0))
    lng = float(data.get("lng", 0))

    db.volunteers.update_one(
        {"_id": ObjectId(vid)},
        {"$set": {"lat": lat, "lng": lng,
                  "location": geo_point(lat, lng),
                  "updated_at": utcnow()}}
    )
    return jsonify({"message": "Location updated"}), 200


# ── Available Tasks ───────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/available", methods=["GET"])
@volunteer_required
def available_tasks():
    db = current_app.db
    volunteer, vid = _current_volunteer()

    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is None:
        lat = volunteer.get("lat")
    if lng is None:
        lng = volunteer.get("lng")

    radius_km = float(request.args.get("radius_km", current_app.config["DEFAULT_MATCH_RADIUS_KM"]))
    urgency   = request.args.get("urgency")
    task_type = request.args.get("task_type")
    page      = int(request.args.get("page", 1))
    per_page  = int(request.args.get("per_page", 20))

    query = {"status": "open"}
    if urgency:
        query["urgency"] = urgency
    if task_type:
        query["task_type"] = task_type

    if lat is not None and lng is not None:
        query["location"] = {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": radius_km * 1000,
            }
        }

    tasks = list(db.tasks.find(query).skip((page - 1) * per_page).limit(per_page))

    if lat is not None and lng is not None:
        for t in tasks:
            try:
                t["distance_km"] = round(haversine_km(lat, lng, t["lat"], t["lng"]), 2)
            except Exception:
                pass

    return jsonify({
        "tasks": serialize_list(tasks),
        "page": page,
        "per_page": per_page,
    }), 200


# ── Active Task ───────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/active", methods=["GET"])
@volunteer_required
def my_active_task():
    db = current_app.db
    volunteer, _ = _current_volunteer()

    task_id = volunteer.get("active_task_id")
    if not task_id:
        return jsonify({"message": "No active task", "task": None}), 200

    task = db.tasks.find_one({"_id": ObjectId(task_id)})
    return jsonify({"task": serialize(task)}), 200


# ── Task History ──────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/history", methods=["GET"])
@volunteer_required
def task_history():
    db = current_app.db
    volunteer, _ = _current_volunteer()

    # FIX B4: Use to_oid() and filter out None so a corrupt id in task_history
    # doesn't raise bson.errors.InvalidId → 500.
    raw_ids    = volunteer.get("task_history", [])
    valid_ids  = [oid for oid in (to_oid(tid) for tid in raw_ids) if oid is not None]
    tasks      = list(db.tasks.find({"_id": {"$in": valid_ids}}))
    return jsonify({"tasks": serialize_list(tasks)}), 200


# ── Apply for Task ────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/<task_id>/apply", methods=["POST"])
@volunteer_required
def apply_for_task(task_id):
    db = current_app.db
    volunteer, vid = _current_volunteer()

    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if task["status"] != "open":
        return jsonify({"error": "Task is not open for applications"}), 400

    already = any(str(a["volunteer_id"]) == vid for a in task.get("applicants", []))
    if already:
        return jsonify({"error": "Already applied"}), 409

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$push": {"applicants": {
            "volunteer_id": vid,
            "applied_at":   utcnow(),
            "status":       "pending"
        }}, "$set": {"updated_at": utcnow()}}
    )

    _notify(db, task["ngo_id"], "ngo",
            "New Task Application",
            f"Volunteer {volunteer['name']} applied for: {task['title']}",
            "task_application", task_id)

    return jsonify({"message": "Application submitted"}), 200


# ── Accept Task ───────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/<task_id>/accept", methods=["POST"])
@volunteer_required
def accept_task(task_id):
    db = current_app.db
    volunteer, vid = _current_volunteer()

    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if vid not in [str(v) for v in task.get("assigned_volunteers", [])]:
        return jsonify({"error": "You are not assigned to this task"}), 403

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {"status": "in_progress", "updated_at": utcnow()}}
    )
    db.volunteers.update_one(
        {"_id": ObjectId(vid)},
        {"$set": {"active_task_id": task_id, "updated_at": utcnow()}}
    )

    _notify(db, task["ngo_id"], "ngo",
            "Task Accepted",
            f"{volunteer['name']} accepted: {task['title']}",
            "task_accepted", task_id)

    return jsonify({"message": "Task accepted. Good luck!"}), 200


# ── Reject Task ───────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/<task_id>/reject", methods=["POST"])
@volunteer_required
def reject_task(task_id):
    db = current_app.db
    volunteer, vid = _current_volunteer()

    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$pull": {"assigned_volunteers": vid},
         "$set":  {"status": "open", "updated_at": utcnow()}}
    )
    db.volunteers.update_one(
        {"_id": ObjectId(vid)},
        {"$inc": {"tasks_rejected": 1}, "$set": {"active_task_id": None}}
    )

    from services.trust_score import update_trust_score
    update_trust_score(db, vid, event="rejected")

    _notify(db, task["ngo_id"], "ngo",
            "Task Rejected",
            f"{volunteer['name']} rejected: {task['title']}",
            "task_rejected", task_id)

    return jsonify({"message": "Task rejected"}), 200


# ── Proof of Work Upload ──────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/<task_id>/proof", methods=["POST"])
@volunteer_required
def upload_proof(task_id):
    db = current_app.db
    volunteer, vid = _current_volunteer()

    task = db.tasks.find_one({"_id": to_oid(task_id)})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    # FIX S6: Validate actual file content via magic bytes, not just extension.
    # This prevents uploading malware disguised as an image (e.g. malware.php → malware.jpg).
    ext = file.filename.rsplit(".", 1)[1].lower()
    if not _is_valid_file_content(file, ext):
        return jsonify({"error": "File content does not match its extension"}), 400

    filename  = secure_filename(f"{task_id}_{vid}_{file.filename}")
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    file.save(save_path)

    proof_entry = {
        "volunteer_id": vid,
        "file_url":     f"/uploads/proof_of_work/{filename}",
        "uploaded_at":  utcnow(),
        "approved":     None,
        "notes":        request.form.get("notes", ""),
    }
    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$push": {"proof_of_work": proof_entry}, "$set": {"updated_at": utcnow()}}
    )

    _notify(db, task["ngo_id"], "ngo",
            "Proof of Work Uploaded",
            f"{volunteer['name']} uploaded proof for: {task['title']}",
            "proof_uploaded", task_id)

    return jsonify({"message": "Proof uploaded. Awaiting NGO approval.",
                    "file_url": proof_entry["file_url"]}), 200


# ── Log Travel ────────────────────────────────────────────────────────────────

@volunteer_bp.route("/tasks/<task_id>/log-travel", methods=["POST"])
@volunteer_required
def log_travel(task_id):
    db   = current_app.db
    _, vid = _current_volunteer()
    data = request.get_json() or {}

    # FIX B3: Validate all required fields before accessing them.
    # Previously, missing fields caused a KeyError → unhandled 500.
    required_fields = ["start_lat", "start_lng", "end_lat", "end_lng",
                       "actual_distance_km", "optimal_distance_km"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        start_lat           = float(data["start_lat"])
        start_lng           = float(data["start_lng"])
        end_lat             = float(data["end_lat"])
        end_lng             = float(data["end_lng"])
        actual_distance_km  = float(data["actual_distance_km"])
        optimal_distance_km = float(data["optimal_distance_km"])
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid numeric value: {exc}"}), 400

    from models.schemas import travel_log_schema
    from services.inefficiency_detector import analyze_travel

    log = travel_log_schema(
        volunteer_id        = vid,
        task_id             = task_id,
        start_lat           = start_lat,
        start_lng           = start_lng,
        end_lat             = end_lat,
        end_lng             = end_lng,
        actual_distance_km  = actual_distance_km,
        optimal_distance_km = optimal_distance_km,
    )

    result = db.travel_logs.insert_one(log)
    report = analyze_travel(db, str(result.inserted_id), current_app.config)
    return jsonify({"logged": True, "inefficiency_report": report}), 200


# ── Reviews ───────────────────────────────────────────────────────────────────

@volunteer_bp.route("/reviews", methods=["GET"])
@volunteer_required
def my_reviews():
    db = current_app.db
    volunteer, _ = _current_volunteer()
    return jsonify({
        "reviews":    volunteer.get("reviews", []),
        "avg_rating": volunteer.get("avg_rating", 0.0),
        "trust_score":volunteer.get("trust_score", 50),
    }), 200


# ── Stats ─────────────────────────────────────────────────────────────────────

@volunteer_bp.route("/stats", methods=["GET"])
@volunteer_required
def my_stats():
    db = current_app.db
    volunteer, _ = _current_volunteer()
    return jsonify({
        "total_tasks_done":  volunteer.get("total_tasks_done", 0),
        "tasks_on_time":     volunteer.get("tasks_on_time", 0),
        "tasks_late":        volunteer.get("tasks_late", 0),
        "tasks_rejected":    volunteer.get("tasks_rejected", 0),
        "avg_rating":        volunteer.get("avg_rating", 0.0),
        "trust_score":       volunteer.get("trust_score", 50),
        "confidence_score":  volunteer.get("confidence_score", 50),
        "is_verified":       volunteer.get("is_verified", False),
        "verified_badge":    volunteer.get("verified_badge", False),
    }), 200


# ── Notifications ─────────────────────────────────────────────────────────────

@volunteer_bp.route("/notifications", methods=["GET"])
@volunteer_required
def my_notifications():
    db = current_app.db
    _, vid = _current_volunteer()

    notifs = list(db.notifications.find(
        {"recipient_id": vid, "recipient_type": "volunteer"}
    ).sort("created_at", -1).limit(50))

    db.notifications.update_many(
        {"recipient_id": vid, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return jsonify({"notifications": serialize_list(notifs)}), 200


# ── AI Suggestions ────────────────────────────────────────────────────────────

@volunteer_bp.route("/ai-suggestions", methods=["GET"])
@volunteer_required
def ai_suggestions():
    db = current_app.db
    volunteer, vid = _current_volunteer()

    if not volunteer:
        return jsonify({"tasks": []}), 200

    from services.geo_matching import get_ai_suggestions_for_volunteer

    suggestions = get_ai_suggestions_for_volunteer(
        db, volunteer, current_app.config
    )

    return jsonify({
        "suggestions": suggestions,
        "tasks": suggestions
    }), 200


# ── Internal helper ───────────────────────────────────────────────────────────

def _notify(db, recipient_id, recipient_type, title, message, notif_type, ref_id=None):
    from models.schemas import notification_schema
    doc = notification_schema(recipient_id, recipient_type, title, message, notif_type, ref_id)
    db.notifications.insert_one(doc)
