"""
routes/auth_routes.py
---------------------
Handles signup / login for Volunteers and NGOs.
Returns JWT access + refresh tokens.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

from models.schemas import volunteer_schema, ngo_schema, utcnow
from utils.helpers import serialize, is_valid_email, is_valid_phone, to_oid

auth_bp = Blueprint("auth", __name__)


# ── Volunteer Signup ───────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/signup", methods=["POST"])
def volunteer_signup():
    db   = current_app.db
    data = request.get_json()

    # --- Validate required fields ---
    required = ["name", "email", "password", "phone", "lat", "lng"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "Invalid email format"}), 400

    if db.volunteers.find_one({"email": data["email"].lower()}):
        return jsonify({"error": "Email already registered"}), 409

    # --- Build & insert ---
    doc = volunteer_schema(
        name        = data["name"],
        email       = data["email"],
        password_hash = generate_password_hash(data["password"]),
        phone       = data.get("phone", ""),
        lat         = float(data["lat"]),
        lng         = float(data["lng"]),
        skills      = data.get("skills", []),
        availability= data.get("availability", []),
    )
    result = db.volunteers.insert_one(doc)
    vid    = str(result.inserted_id)

    access_token  = create_access_token(identity={"id": vid, "type": "volunteer"})
    refresh_token = create_refresh_token(identity={"id": vid, "type": "volunteer"})

    return jsonify({
        "message":       "Volunteer registered successfully",
        "id":            vid,
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 201


# ── Volunteer Login ────────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/login", methods=["POST"])
def volunteer_login():
    db   = current_app.db
    data = request.get_json()

    email    = data.get("email", "").lower()
    password = data.get("password", "")

    volunteer = db.volunteers.find_one({"email": email})
    if not volunteer or not check_password_hash(volunteer["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    if volunteer.get("status") == "banned":
        return jsonify({"error": "Account banned. Contact support."}), 403

    vid = str(volunteer["_id"])
    access_token  = create_access_token(identity={"id": vid, "type": "volunteer"})
    refresh_token = create_refresh_token(identity={"id": vid, "type": "volunteer"})

    return jsonify({
        "message":       "Login successful",
        "id":            vid,
        "name":          volunteer["name"],
        "trust_score":   volunteer.get("trust_score", 50),
        "is_verified":   volunteer.get("is_verified", False),
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 200


# ── NGO Signup ────────────────────────────────────────────────────────────────

@auth_bp.route("/ngo/signup", methods=["POST"])
def ngo_signup():
    db   = current_app.db
    data = request.get_json()

    required = ["name", "email", "password", "phone", "registration_number", "lat", "lng"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "Invalid email format"}), 400

    if db.ngos.find_one({"email": data["email"].lower()}):
        return jsonify({"error": "Email already registered"}), 409

    doc = ngo_schema(
        name                = data["name"],
        email               = data["email"],
        password_hash       = generate_password_hash(data["password"]),
        phone               = data["phone"],
        registration_number = data["registration_number"],
        lat                 = float(data["lat"]),
        lng                 = float(data["lng"]),
        focus_areas         = data.get("focus_areas", []),
    )
    result = db.ngos.insert_one(doc)
    nid    = str(result.inserted_id)

    access_token  = create_access_token(identity={"id": nid, "type": "ngo"})
    refresh_token = create_refresh_token(identity={"id": nid, "type": "ngo"})

    return jsonify({
        "message":       "NGO registered successfully",
        "id":            nid,
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 201


# ── NGO Login ─────────────────────────────────────────────────────────────────

@auth_bp.route("/ngo/login", methods=["POST"])
def ngo_login():
    db   = current_app.db
    data = request.get_json()

    email    = data.get("email", "").lower()
    password = data.get("password", "")

    ngo = db.ngos.find_one({"email": email})
    if not ngo or not check_password_hash(ngo["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    if ngo.get("status") != "active":
        return jsonify({"error": "NGO account is not active"}), 403

    nid = str(ngo["_id"])
    access_token  = create_access_token(identity={"id": nid, "type": "ngo"})
    refresh_token = create_refresh_token(identity={"id": nid, "type": "ngo"})

    return jsonify({
        "message":        "Login successful",
        "id":             nid,
        "name":           ngo["name"],
        "is_verified":    ngo.get("is_verified", False),
        "access_token":   access_token,
        "refresh_token":  refresh_token,
    }), 200


# ── Refresh Token ─────────────────────────────────────────────────────────────

@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity      = get_jwt_identity()
    access_token  = create_access_token(identity=identity)
    return jsonify({"access_token": access_token}), 200


# ── Community Problem Report (no login required) ───────────────────────────────

@auth_bp.route("/report-problem", methods=["POST"])
def report_problem():
    """
    Any community member can submit a problem.
    It lands in problem_reports with status='pending'.
    NGOs review and approve/reject from their dashboard.
    """
    db   = current_app.db
    data = request.get_json()

    required = ["reporter_name", "reporter_contact", "problem_type", "description", "lat", "lng"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    from models.schemas import problem_report_schema
    doc = problem_report_schema(
        reporter_name         = data["reporter_name"],
        reporter_contact      = data["reporter_contact"],
        problem_type          = data["problem_type"],
        description           = data["description"],
        lat                   = float(data["lat"]),
        lng                   = float(data["lng"]),
        address               = data.get("address", ""),
        urgency_self_reported = data.get("urgency", "low"),
        media_urls            = data.get("media_urls", []),
    )
    result = db.problem_reports.insert_one(doc)
    return jsonify({
        "message":    "Problem reported. It will be reviewed by a local NGO.",
        "report_id":  str(result.inserted_id),
    }), 201
