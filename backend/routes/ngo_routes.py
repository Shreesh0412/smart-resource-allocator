"""
routes/ngo_routes.py
--------------------
All endpoints for the NGO Dashboard:
  - Post a need (task) with Type, Location, Urgency
  - Dashboard: active requests, completed, volunteer assignments
  - Approve/reject community problem reports
  - Review & approve proof of work
  - Manage urgency level of tasks (low/med/urgent)
  - Assign/remove volunteers
  - Leave reviews for volunteers
  - AI suggestions
  - Analytics dashboard
  - Resource management
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from bson import ObjectId
from datetime import datetime

from utils.decorators import ngo_required
from utils.helpers import serialize, serialize_list, to_oid, compute_urgency_from_deadline
from models.schemas import task_schema, resource_schema, utcnow

ngo_bp = Blueprint("ngo", __name__)


def _current_ngo():
    identity = get_jwt_identity()
    db = current_app.db
    return db.ngos.find_one({"_id": ObjectId(identity["id"])}), identity["id"]


# ── NGO Profile ───────────────────────────────────────────────────────────────

@ngo_bp.route("/profile", methods=["GET"])
@ngo_required
def get_profile():
    ngo, _ = _current_ngo()
    doc = serialize(ngo)
    doc.pop("password_hash", None)
    return jsonify(doc), 200


@ngo_bp.route("/profile", methods=["PUT"])
@ngo_required
def update_profile():
    db = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()
    allowed = ["name", "phone", "focus_areas"]
    update = {k: data[k] for k in allowed if k in data}
    update["updated_at"] = utcnow()
    db.ngos.update_one({"_id": ObjectId(nid)}, {"$set": update})
    return jsonify({"message": "Profile updated"}), 200


# ── Post a Need (Create Task) ─────────────────────────────────────────────────

@ngo_bp.route("/tasks", methods=["POST"])
@ngo_required
def post_task():
    db  = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()

    required = ["title", "description", "task_type", "lat", "lng", "deadline", "volunteers_needed"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    # If urgency not provided, auto-compute from deadline
    urgency = data.get("urgency") or compute_urgency_from_deadline(data["deadline"])

    doc = task_schema(
        ngo_id            = nid,
        title             = data["title"],
        description       = data["description"],
        task_type         = data["task_type"],
        lat               = float(data["lat"]),
        lng               = float(data["lng"]),
        address           = data.get("address", ""),
        deadline          = data["deadline"],
        urgency           = urgency,
        volunteers_needed = int(data["volunteers_needed"]),
        required_skills   = data.get("required_skills", []),
        resources_needed  = data.get("resources_needed", []),
    )
    result = db.tasks.insert_one(doc)
    tid = str(result.inserted_id)

    # Update NGO stats
    db.ngos.update_one({"_id": ObjectId(nid)}, {"$inc": {"total_tasks_posted": 1}})

    # Trigger auto geo-matching in background
    from services.geo_matching import auto_match_volunteers
    matches = auto_match_volunteers(db, tid, current_app.config)

    # Send WhatsApp notifications to top matches
    from services.notification_service import notify_matched_volunteers
    notify_matched_volunteers(db, matches, doc, current_app.config)

    return jsonify({
        "message":    "Task posted successfully",
        "task_id":    tid,
        "urgency":    urgency,
        "auto_matched_volunteers": len(matches),
    }), 201


# ── Change Task Urgency (NGO power) ──────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/urgency", methods=["PATCH"])
@ngo_required
def change_urgency(task_id):
    db  = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()

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

    # If escalated to urgent, notify assigned volunteers
    if urgency == "urgent":
        for vol_id in task.get("assigned_volunteers", []):
            _notify(db, str(vol_id), "volunteer",
                    "⚠️ Task Urgency Escalated",
                    f"Task '{task['title']}' has been marked URGENT. Please act immediately.",
                    "urgency_escalated", task_id)

    return jsonify({"message": f"Task urgency updated to {urgency}"}), 200


# ── Dashboard — Active Requests ───────────────────────────────────────────────

@ngo_bp.route("/dashboard/active", methods=["GET"])
@ngo_required
def active_requests():
    db = current_app.db
    _, nid = _current_ngo()

    tasks = list(db.tasks.find(
        {"ngo_id": nid, "status": {"$in": ["open", "assigned", "in_progress"]}}
    ).sort("urgency", -1))

    # Enrich with volunteer info
    for task in tasks:
        assigned = task.get("assigned_volunteers", [])
        task["volunteer_details"] = serialize_list(list(
            db.volunteers.find({"_id": {"$in": [ObjectId(v) for v in assigned]}},
                               {"name": 1, "trust_score": 1, "phone": 1})
        ))
    return jsonify({"tasks": serialize_list(tasks)}), 200


# ── Dashboard — Completed Requests ────────────────────────────────────────────

@ngo_bp.route("/dashboard/completed", methods=["GET"])
@ngo_required
def completed_requests():
    db = current_app.db
    _, nid = _current_ngo()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    tasks = list(db.tasks.find({"ngo_id": nid, "status": "completed"})
                 .sort("completed_at", -1)
                 .skip((page - 1) * per_page)
                 .limit(per_page))
    return jsonify({"tasks": serialize_list(tasks)}), 200


# ── Applicants for a Task ─────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/applicants", methods=["GET"])
@ngo_required
def task_applicants(task_id):
    db = current_app.db
    _, nid = _current_ngo()

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    applicants = task.get("applicants", [])
    enriched   = []
    for app in applicants:
        vol = db.volunteers.find_one(
            {"_id": ObjectId(app["volunteer_id"])},
            {"password_hash": 0}
        )
        enriched.append({
            **app,
            "volunteer": serialize(vol) if vol else None
        })

    return jsonify({"applicants": enriched}), 200


# ── Assign a Volunteer ────────────────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/assign/<volunteer_id>", methods=["POST"])
@ngo_required
def assign_volunteer(task_id, volunteer_id):
    db  = current_app.db
    ngo, nid = _current_ngo()

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    # Update task
    db.tasks.update_one(
        {"_id": to_oid(task_id)},
        {
            "$addToSet": {"assigned_volunteers": volunteer_id},
            "$set":      {"status": "assigned", "updated_at": utcnow()},
            "$set":      {
                "applicants.$[elem].status": "accepted",
                "status": "assigned",
                "updated_at": utcnow()
            }
        },
        array_filters=[{"elem.volunteer_id": volunteer_id}]
    )
    db.ngos.update_one({"_id": ObjectId(nid)}, {"$inc": {"active_volunteers": 1}})

    # Notify volunteer via in-app + WhatsApp
    _notify(db, volunteer_id, "volunteer",
            "🎯 You've been assigned a task!",
            f"NGO {ngo['name']} assigned you to: {task['title']}. Please accept or reject.",
            "task_assigned", task_id)

    from services.notification_service import send_whatsapp
    if vol.get("whatsapp_opt_in"):
        send_whatsapp(
            to=vol["phone"],
            message=f"Hi {vol['name']}! You've been assigned to task: {task['title']} by {ngo['name']}. "
                    f"Location: {task.get('address', 'See app')}. Please open the app to accept.",
            config=current_app.config
        )

    return jsonify({"message": f"Volunteer {vol['name']} assigned"}), 200


# ── Approve / Reject Proof of Work ────────────────────────────────────────────

@ngo_bp.route("/tasks/<task_id>/proof/<volunteer_id>/review", methods=["POST"])
@ngo_required
def review_proof(task_id, volunteer_id):
    db  = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()

    approved = data.get("approved", False)
    notes    = data.get("notes", "")

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
        # Mark task complete, update volunteer stats + trust score
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
        db.ngos.update_one({"_id": ObjectId(nid)},
                            {"$inc": {"total_tasks_completed": 1, "active_volunteers": -1}})

        from services.trust_score import update_trust_score
        update_trust_score(db, volunteer_id, event="completed")

        _notify(db, volunteer_id, "volunteer",
                "✅ Proof Approved!",
                f"Your work on '{task['title']}' has been approved. Great job!",
                "proof_approved", task_id)
    else:
        _notify(db, volunteer_id, "volunteer",
                "❌ Proof Rejected",
                f"Your proof for '{task['title']}' was rejected. Reason: {notes}",
                "proof_rejected", task_id)

    return jsonify({"message": "Proof reviewed", "approved": approved}), 200


# ── Leave Review for a Volunteer ──────────────────────────────────────────────

@ngo_bp.route("/volunteers/<volunteer_id>/review", methods=["POST"])
@ngo_required
def review_volunteer(volunteer_id):
    db  = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()

    rating  = int(data.get("rating", 3))
    comment = data.get("comment", "")
    task_id = data.get("task_id", "")

    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be 1-5"}), 400

    review = {
        "ngo_id":   nid,
        "ngo_name": ngo["name"],
        "rating":   rating,
        "comment":  comment,
        "task_id":  task_id,
        "date":     utcnow(),
    }

    vol = db.volunteers.find_one({"_id": to_oid(volunteer_id)})
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404

    existing_reviews = vol.get("reviews", [])
    existing_reviews.append(review)
    from utils.helpers import compute_avg_rating
    avg = compute_avg_rating(existing_reviews)

    db.volunteers.update_one(
        {"_id": to_oid(volunteer_id)},
        {"$push": {"reviews": review}, "$set": {"avg_rating": avg, "updated_at": utcnow()}}
    )

    from services.trust_score import update_trust_score
    update_trust_score(db, volunteer_id, event="reviewed", rating=rating)

    _notify(db, volunteer_id, "volunteer",
            "⭐ New Review",
            f"{ngo['name']} gave you {rating}/5 stars. {comment}",
            "review", task_id)

    return jsonify({"message": "Review submitted", "new_avg_rating": avg}), 200


# ── Approve / Reject Community Problem Reports ────────────────────────────────

@ngo_bp.route("/reports", methods=["GET"])
@ngo_required
def get_pending_reports():
    db = current_app.db
    _, nid = _current_ngo()
    ngo_doc, _ = _current_ngo()

    # Show reports geographically near this NGO
    lat = ngo_doc["lat"]
    lng = ngo_doc["lng"]

    reports = list(db.problem_reports.find({
        "status": "pending",
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": 50000   # 50km
            }
        }
    }).limit(100))
    return jsonify({"reports": serialize_list(reports)}), 200


@ngo_bp.route("/reports/<report_id>/review", methods=["POST"])
@ngo_required
def review_report(report_id):
    db = current_app.db
    _, nid = _current_ngo()
    data = request.get_json()

    action = data.get("action")     # "approve" | "reject" | "convert_to_task"
    note   = data.get("note", "")

    report = db.problem_reports.find_one({"_id": to_oid(report_id)})
    if not report:
        return jsonify({"error": "Report not found"}), 404

    update = {
        "reviewed_by_ngo_id": nid,
        "ngo_review_note":    note,
        "reviewed_at":        utcnow(),
    }

    if action == "approve":
        update["status"] = "approved"
    elif action == "reject":
        update["status"] = "rejected"
    elif action == "convert_to_task":
        # Auto-create a task from this report
        task_doc = task_schema(
            ngo_id            = nid,
            title             = f"[Community Report] {report['problem_type']}",
            description       = report["description"],
            task_type         = report["problem_type"],
            lat               = report["lat"],
            lng               = report["lng"],
            address           = report.get("address", ""),
            deadline          = data.get("deadline", ""),
            urgency           = report.get("urgency_self_reported", "low"),
            volunteers_needed = int(data.get("volunteers_needed", 1)),
        )
        result = db.tasks.insert_one(task_doc)
        update["status"]            = "converted_to_task"
        update["converted_task_id"] = str(result.inserted_id)
    else:
        return jsonify({"error": "Invalid action"}), 400

    db.problem_reports.update_one({"_id": to_oid(report_id)}, {"$set": update})
    return jsonify({"message": f"Report {action}d", "update": update}), 200


# ── AI Suggestions for NGO (volunteers to assign) ─────────────────────────────

@ngo_bp.route("/tasks/<task_id>/ai-suggestions", methods=["GET"])
@ngo_required
def ai_suggestions(task_id):
    db = current_app.db
    _, nid = _current_ngo()

    task = db.tasks.find_one({"_id": to_oid(task_id), "ngo_id": nid})
    if not task:
        return jsonify({"error": "Task not found"}), 404

    from services.geo_matching import get_best_volunteers_for_task
    suggestions = get_best_volunteers_for_task(db, task, current_app.config, top_n=10)
    return jsonify({"suggestions": suggestions}), 200


# ── Analytics Dashboard ───────────────────────────────────────────────────────

@ngo_bp.route("/analytics", methods=["GET"])
@ngo_required
def analytics():
    db = current_app.db
    _, nid = _current_ngo()

    from services.analytics import build_ngo_analytics
    data = build_ngo_analytics(db, nid)
    return jsonify(data), 200


# ── Resource Manager ──────────────────────────────────────────────────────────

@ngo_bp.route("/resources", methods=["GET"])
@ngo_required
def list_resources():
    db = current_app.db
    _, nid = _current_ngo()
    resources = list(db.resources.find({"ngo_id": nid}))
    return jsonify({"resources": serialize_list(resources)}), 200


@ngo_bp.route("/resources", methods=["POST"])
@ngo_required
def add_resource():
    db  = current_app.db
    ngo, nid = _current_ngo()
    data = request.get_json()

    required = ["name", "category", "quantity", "unit"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    doc = resource_schema(
        ngo_id          = nid,
        name            = data["name"],
        category        = data["category"],
        quantity        = float(data["quantity"]),
        unit            = data["unit"],
        lat             = float(data.get("lat", ngo["lat"])),
        lng             = float(data.get("lng", ngo["lng"])),
        available_from  = data.get("available_from"),
        available_until = data.get("available_until"),
        notes           = data.get("notes", ""),
    )
    result = db.resources.insert_one(doc)
    return jsonify({"message": "Resource added", "resource_id": str(result.inserted_id)}), 201


@ngo_bp.route("/resources/<resource_id>", methods=["PUT"])
@ngo_required
def update_resource(resource_id):
    db = current_app.db
    _, nid = _current_ngo()

    resource = db.resources.find_one({"_id": to_oid(resource_id), "ngo_id": nid})
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    data    = request.get_json()
    allowed = ["name", "category", "quantity", "unit", "notes", "status"]
    update  = {k: data[k] for k in allowed if k in data}
    update["updated_at"] = utcnow()

    db.resources.update_one({"_id": to_oid(resource_id)}, {"$set": update})
    return jsonify({"message": "Resource updated"}), 200


@ngo_bp.route("/resources/<resource_id>/allocate", methods=["POST"])
@ngo_required
def allocate_resource(resource_id):
    """Allocate a resource to a specific task."""
    db   = current_app.db
    _, nid = _current_ngo()
    data = request.get_json()

    resource = db.resources.find_one({"_id": to_oid(resource_id), "ngo_id": nid})
    if not resource:
        return jsonify({"error": "Resource not found"}), 404

    task_id = data.get("task_id")
    amount  = float(data.get("amount", 0))

    if amount > resource["quantity"]:
        return jsonify({"error": "Insufficient quantity"}), 400

    new_qty = resource["quantity"] - amount
    status  = "depleted" if new_qty == 0 else ("partially_used" if new_qty < resource["quantity"] else "available")

    db.resources.update_one(
        {"_id": to_oid(resource_id)},
        {
            "$set":  {"quantity": new_qty, "status": status, "updated_at": utcnow()},
            "$push": {"allocated_to": {"task_id": task_id, "amount": amount}}
        }
    )
    return jsonify({"message": "Resource allocated", "remaining": new_qty}), 200


# ── Task Failure Predictor (for a specific task) ──────────────────────────────

@ngo_bp.route("/tasks/<task_id>/predict", methods=["GET"])
@ngo_required
def predict_task(task_id):
    db = current_app.db
    _, nid = _current_ngo()

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

    # Get tasks belonging to this NGO
    task_ids = [str(t["_id"]) for t in db.tasks.find({"ngo_id": nid}, {"_id": 1})]
    logs = list(db.travel_logs.find({
        "task_id":  {"$in": task_ids},
        "flagged":  True
    }).sort("excess_km", -1))
    return jsonify({"inefficiency_reports": serialize_list(logs)}), 200


# ── Internal helper ───────────────────────────────────────────────────────────

def _notify(db, recipient_id, recipient_type, title, message, notif_type, ref_id=None):
    from models.schemas import notification_schema
    doc = notification_schema(recipient_id, recipient_type, title, message, notif_type, ref_id)
    db.notifications.insert_one(doc)
