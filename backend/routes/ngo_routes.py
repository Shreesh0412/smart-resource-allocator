"""
routes/ngo_routes.py — FIXED
- _current_ngo() uses plain string identity.
- Reports route no longer crashes on missing/partial geo data.
- Task creation is safer and supports pincode-based payloads.
- JSON parsing is resilient with silent=True.
- ObjectId conversions are guarded.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from bson import ObjectId

from utils.decorators import ngo_required
from utils.helpers import (
    serialize,
    serialize_list,
    to_oid,
    compute_urgency_from_deadline,
    resolve_location_payload,
)
from models.schemas import task_schema, resource_schema, utcnow

ngo_bp = Blueprint("ngo", __name__)


def _current_ngo():
    """Returns (ngo_doc, ngo_id_string)."""
    nid = get_jwt_identity()
    db = current_app.db

    try:
        doc = db.ngos.find_one({"_id": ObjectId(nid)})
    except Exception:
        return None, None

    return doc, nid


def _safe_object_ids(values):
    """Convert a list of strings/ObjectIds to valid ObjectId objects only."""
    out = []
    for value in values or []:
        try:
            out.append(ObjectId(str(value)))
        except Exception:
            continue
    return out


# ── Profile ───────────────────────────────────────────────────────────────────

@ngo_bp.route("/profile", methods=["GET"])
@ngo_required
def get_profile():
    ngo, _ = _current_ngo()
    doc = serialize(ngo)
    if doc:
        doc.pop("password_hash", None)
    return jsonify(doc), 200


@ngo_bp.route("/profile", methods=["PUT"])
@ngo_required
def update_profile():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = ["name", "phone", "focus_areas", "pincode"]
    update = {k: data[k] for k in allowed if k in data}
    update["updated_at"] = utcnow()

    db.ngos.update_one({"_id": ObjectId(nid)}, {"$set": update})
    return jsonify({"message": "Profile updated"}), 200


# ── Post a Need ───────────────────────────────────────────────────────────────

@ngo_bp.route("/tasks", methods=["POST"])
@ngo_required
def post_task():
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}

    required = ["title", "description", "task_type", "deadline", "volunteers_needed", "pincode"]
    missing = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    loc = resolve_location_payload(data, require_pincode=True)
    if loc.get("error"):
        return jsonify({"error": loc["error"]}), 400

    urgency = data.get("urgency") or compute_urgency_from_deadline(data["deadline"])

    doc = task_schema(
        ngo_id=nid,
        title=data["title"],
        description=data["description"],
        task_type=data["task_type"],
        lat=float(loc["lat"]),
        lng=float(loc["lng"]),
        address=data.get("address", ""),
        deadline=data["deadline"],
        urgency=urgency,
        volunteers_needed=int(data["volunteers_needed"]),
        required_skills=data.get("required_skills", []),
        resources_needed=data.get("resources_needed", []),
    )

    # Keep pincode even if task_schema does not define it.
    doc["pincode"] = loc.get("pincode", data.get("pincode", ""))

    result = db.tasks.insert_one(doc)
    tid = str(result.inserted_id)

    db.ngos.update_one({"_id": ObjectId(nid)}, {"$inc": {"total_tasks_posted": 1}})

    from services.geo_matching import auto_match_volunteers
    matches = auto_match_volunteers(db, tid, current_app.config)

    from services.notification_service import notify_matched_volunteers
    notify_matched_volunteers(db, matches, doc, current_app.config)

    return jsonify({
        "message": "Task posted successfully",
        "task_id": tid,
        "urgency": urgency,
        "auto_matched_volunteers": len(matches),
    }), 201


# ── Change Task Urgency ───────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/urgency", methods=["PATCH"])
@ngo_required
def change_urgency(task_id):
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}

    urgency = data.get("urgency", "").lower()
    if urgency not in ("low", "med", "urgent"):
        return jsonify({"error": "urgency must be 'low', 'med', or 'urgent'"}), 400

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found or not yours"}), 404

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {"$set": {"urgency": urgency, "updated_at": utcnow()}}
    )

    if urgency == "urgent":
        for vol_id in task.get("assigned_volunteers", []):
            _notify(
                db,
                str(vol_id),
                "volunteer",
                "Task Urgency Escalated",
                f"Task '{task['title']}' is now URGENT. Please act immediately.",
                "urgency_escalated",
                task_id
            )

    return jsonify({"message": f"Urgency updated to {urgency}"}), 200


# ── Dashboard — Active ────────────────────────────────────────────────────────

@ngo_bp.route("/dashboard/active", methods=["GET"])
@ngo_required
def active_requests():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"tasks": []}), 200

    tasks = list(
        db.tasks.find({"ngo_id": nid, "status": {"$in": ["open", "assigned", "in_progress"]}})
        .sort("urgency", -1)
    )

    for task in tasks:
        valid_ids = _safe_object_ids(task.get("assigned_volunteers", []))
        task["volunteer_details"] = serialize_list(list(
            db.volunteers.find(
                {"_id": {"$in": valid_ids}},
                {"name": 1, "trust_score": 1, "phone": 1}
            )
        ))

    return jsonify({"tasks": serialize_list(tasks)}), 200


# ── Dashboard — Completed ─────────────────────────────────────────────────────

@ngo_bp.route("/dashboard/completed", methods=["GET"])
@ngo_required
def completed_requests():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"tasks": []}), 200

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    tasks = list(
        db.tasks.find({"ngo_id": nid, "status": "completed"})
        .sort("completed_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return jsonify({"tasks": serialize_list(tasks)}), 200


# ── Applicants ────────────────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/applicants", methods=["GET"])
@ngo_required
def task_applicants(task_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    enriched = []
    for app in task.get("applicants", []):
        volunteer_id = app.get("volunteer_id")
        vol = None
        try:
            vol = db.volunteers.find_one({"_id": ObjectId(volunteer_id)}, {"password_hash": 0})
        except Exception:
            vol = None
        enriched.append({**app, "volunteer": serialize(vol) if vol else None})

    return jsonify({"applicants": enriched}), 200


# ── Assign Volunteer ──────────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/assign/<volunteer_id>", methods=["POST"])
@ngo_required
def assign_volunteer(task_id, volunteer_id):
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {
            "$addToSet": {"assigned_volunteers": volunteer_id},
            "$set": {"status": "assigned", "updated_at": utcnow()},
        }
    )
    db.ngos.update_one({"_id": ObjectId(nid)}, {"$inc": {"active_volunteers": 1}})

    _notify(
        db,
        volunteer_id,
        "volunteer",
        "You have been assigned a task!",
        f"NGO {ngo['name']} assigned you to: {task['title']}. Accept or reject in the app.",
        "task_assigned",
        task_id
    )

    from services.notification_service import send_whatsapp
    if vol.get("whatsapp_opt_in") and vol.get("phone"):
        send_whatsapp(
            to=vol["phone"],
            message=(
                f"Hi {vol['name']}! You've been assigned to task: {task['title']} "
                f"by {ngo['name']}. Location: {task.get('address', 'See app')}. "
                f"Open the app to accept."
            ),
            config=current_app.config
        )

    return jsonify({"message": f"Volunteer {vol['name']} assigned"}), 200


# ── Review Proof of Work ──────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/proof/<volunteer_id>/review", methods=["POST"])
@ngo_required
def review_proof(task_id, volunteer_id):
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}
    approved = data.get("approved", False)
    notes = data.get("notes", "")

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    db.tasks.update_one(
        {"_id": to_oid(task_id), "proof_of_work.volunteer_id": volunteer_id},
        {"$set": {
            "proof_of_work.$.approved": approved,
            "proof_of_work.$.review_notes": notes,
            "proof_of_work.$.reviewed_at": utcnow(),
        }}
    )

    if approved:
        db.tasks.update_one(
            {"_id": to_oid(task_id)},
            {"$set": {"status": "completed", "completed_at": utcnow()}}
        )
        db.volunteers.update_one(
            {"_id": to_oid(volunteer_id)},
            {
                "$inc": {"total_tasks_done": 1},
                "$set": {"active_task_id": None, "updated_at": utcnow()},
                "$push": {"task_history": task_id}
            }
        )
        db.ngos.update_one(
            {"_id": ObjectId(nid)},
            {"$inc": {"total_tasks_completed": 1, "active_volunteers": -1}}
        )

        from services.trust_score import update_trust_score
        update_trust_score(db, volunteer_id, event="completed")

        _notify(
            db,
            volunteer_id,
            "volunteer",
            "Proof Approved!",
            f"Your work on '{task['title']}' has been approved. Great job!",
            "proof_approved",
            task_id
        )
    else:
        _notify(
            db,
            volunteer_id,
            "volunteer",
            "Proof Rejected",
            f"Your proof for '{task['title']}' was rejected. Reason: {notes}",
            "proof_rejected",
            task_id
        )

    return jsonify({"message": "Proof reviewed", "approved": approved}), 200


# ── Review Volunteer ──────────────────────────────────────────────────────────

@ngo_bp.route("/volunteers/<volunteer_id>/review", methods=["POST"])
@ngo_required
def review_volunteer(volunteer_id):
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}
    rating = int(data.get("rating", 3))
    comment = data.get("comment", "")
    task_id = data.get("task_id", "")

    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be 1-5"}), 400

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    review = {
        "ngo_id": nid,
        "ngo_name": ngo["name"],
        "rating": rating,
        "comment": comment,
        "task_id": task_id,
        "date": utcnow(),
    }

    from utils.helpers import compute_avg_rating
    existing = vol.get("reviews", []) + [review]
    avg = compute_avg_rating(existing)

    db.volunteers.update_one(
        {"_id": to_oid(volunteer_id)},
        {"$push": {"reviews": review}, "$set": {"avg_rating": avg, "updated_at": utcnow()}}
    )

    from services.trust_score import update_trust_score
    update_trust_score(db, volunteer_id, event="reviewed", rating=rating)

    _notify(
        db,
        volunteer_id,
        "volunteer",
        "New Review",
        f"{ngo['name']} gave you {rating}/5 stars. {comment}",
        "review",
        task_id
    )

    return jsonify({"message": "Review submitted", "new_avg_rating": avg}), 200


# ── Community Reports ─────────────────────────────────────────────────────────

@ngo_bp.route("/reports", methods=["GET"], strict_slashes=False)
@ngo_required
def get_pending_reports():
    """
    Safe version:
    - avoids geo `$near` query that can crash when indexes/location data are missing
    - returns pending reports in a predictable JSON shape
    """
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"reports": []}), 200

    try:
        reports = list(db.problem_reports.find({"status": "pending"}).limit(100))

        safe_reports = []
        for r in reports:
            safe_reports.append({
                "id": str(r.get("_id")),
                "title": r.get("problem_type", "Community Issue"),
                "description": r.get("description", ""),
                "status": r.get("status", "pending"),
                "lat": r.get("lat"),
                "lng": r.get("lng"),
                "address": r.get("address", ""),
                "created_at": r.get("created_at"),
            })

        return jsonify({"reports": safe_reports}), 200

    except Exception as e:
        print("REPORTS ERROR:", e)
        return jsonify({"error": "Server error"}), 500


@ngo_bp.route("/reports/<report_id>/review", methods=["POST"])
@ngo_required
def review_report(report_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}

    action = data.get("action")
    note = data.get("note", "")

    report = db.problem_reports.find_one({"_id": to_oid(report_id)})
    if not report:
        return jsonify({"error": "Report not found"}), 404

    update = {
        "reviewed_by_ngo_id": nid,
        "ngo_review_note": note,
        "reviewed_at": utcnow(),
    }

    if action == "approve":
        update["status"] = "approved"

    elif action == "reject":
        update["status"] = "rejected"

    elif action == "convert_to_task":
        task_doc = task_schema(
            ngo_id=nid,
            title=f"[Community Report] {report.get('problem_type', 'Issue')}",
            description=report.get("description", ""),
            task_type=report.get("problem_type", "community"),
            lat=float(report.get("lat", ngo.get("lat") if ngo else 0)),
            lng=float(report.get("lng", ngo.get("lng") if ngo else 0)),
            address=report.get("address", ""),
            deadline=data.get("deadline", ""),
            urgency=report.get("urgency_self_reported", "low"),
            volunteers_needed=int(data.get("volunteers_needed", 1)),
            required_skills=[],
            resources_needed=[],
        )
        task_doc["pincode"] = report.get("pincode", "")

        result = db.tasks.insert_one(task_doc)
        update["status"] = "converted_to_task"
        update["converted_task_id"] = str(result.inserted_id)

    else:
        return jsonify({"error": "Invalid action"}), 400

    db.problem_reports.update_one({"_id": to_oid(report_id)}, {"$set": update})
    return jsonify({"message": f"Report {action}d", "update": update}), 200


# ── AI Suggestions ────────────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/ai-suggestions", methods=["GET"])
@ngo_required
def ai_suggestions(task_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"suggestions": []}), 200

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from services.geo_matching import get_best_volunteers_for_task
    suggestions = get_best_volunteers_for_task(db, task, current_app.config, top_n=10)
    return jsonify({"suggestions": suggestions}), 200


# ── Analytics ─────────────────────────────────────────────────────────────────

@ngo_bp.route("/analytics", methods=["GET"])
@ngo_required
def analytics():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({}), 200

    from services.analytics import build_ngo_analytics
    data = build_ngo_analytics(db, nid)
    return jsonify(data), 200


# ── Resources ─────────────────────────────────────────────────────────────────

@ngo_bp.route("/resources", methods=["GET"])
@ngo_required
def list_resources():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"resources": []}), 200

    resources = list(db.resources.find({"ngo_id": nid}))
    return jsonify({"resources": serialize_list(resources)}), 200


@ngo_bp.route("/resources", methods=["POST"])
@ngo_required
def add_resource():
    db = current_app.db
    ngo, nid = _current_ngo()
    if not ngo or not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}

    required = ["name", "category", "quantity", "unit"]
    missing = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    doc = resource_schema(
        ngo_id=nid,
        name=data["name"],
        category=data["category"],
        quantity=float(data["quantity"]),
        unit=data["unit"],
        lat=float(ngo["lat"]),
        lng=float(ngo["lng"]),
        available_from=data.get("available_from"),
        available_until=data.get("available_until"),
        notes=data.get("notes", ""),
    )
    result = db.resources.insert_one(doc)
    return jsonify({"message": "Resource added", "resource_id": str(result.inserted_id)}), 201


@ngo_bp.route("/resources/<resource_id>", methods=["PUT"])
@ngo_required
def update_resource(resource_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    resource = db.resources.find_one({"_id": to_oid(resource_id), "ngo_id": nid})
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = ["name", "category", "quantity", "unit", "notes", "status"]
    update = {k: data[k] for k in allowed if k in data}
    update["updated_at"] = utcnow()

    db.resources.update_one({"_id": to_oid(resource_id)}, {"$set": update})
    return jsonify({"message": "Resource updated"}), 200


@ngo_bp.route("/resources/<resource_id>/allocate", methods=["POST"])
@ngo_required
def allocate_resource(resource_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    data = request.get_json(silent=True) or {}

    resource = db.resources.find_one({"_id": to_oid(resource_id), "ngo_id": nid})
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    task_id = data.get("task_id")
    amount = float(data.get("amount", 0))

    if amount > resource["quantity"]:
        return jsonify({"error": "Insufficient quantity"}), 400

    new_qty = resource["quantity"] - amount
    status = "depleted" if new_qty == 0 else "partially_used"

    db.resources.update_one(
        {"_id": to_oid(resource_id)},
        {
            "$set": {"quantity": new_qty, "status": status, "updated_at": utcnow()},
            "$push": {"allocated_to": {"task_id": task_id, "amount": amount}},
        }
    )
    return jsonify({"message": "Resource allocated", "remaining": new_qty}), 200


# ── Task Predictor ────────────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/predict", methods=["GET"])
@ngo_required
def predict_task(task_id):
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"error": "NGO not found"}), 404

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from services.task_predictor import predict_task_risk
    prediction = predict_task_risk(db, task, current_app.config)
    return jsonify(prediction), 200


# ── Inefficiency Reports ──────────────────────────────────────────────────────

@ngo_bp.route("/inefficiency-reports", methods=["GET"])
@ngo_required
def inefficiency_reports():
    db = current_app.db
    _, nid = _current_ngo()
    if not nid:
        return jsonify({"inefficiency_reports": []}), 200

    task_ids = [str(t["_id"]) for t in db.tasks.find({"ngo_id": nid}, {"_id": 1})]
    logs = list(db.travel_logs.find(
        {"task_id": {"$in": task_ids}, "flagged": True}
    ).sort("excess_km", -1))
    return jsonify({"inefficiency_reports": serialize_list(logs)}), 200


# ── Internal helper ───────────────────────────────────────────────────────────

def _notify(db, recipient_id, recipient_type, title, message, notif_type, ref_id=None):
    from models.schemas import notification_schema
    doc = notification_schema(recipient_id, recipient_type, title, message, notif_type, ref_id)
    db.notifications.insert_one(doc)
