"""
routes/auth_routes.py  — FIXED
Key change: identity is now a plain string (the MongoDB _id),
and user_type is stored as an additional JWT claim.
This is the recommended approach for flask-jwt-extended 4.x
and fixes the dict-identity "Invalid token" (422) bug.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash

from models.schemas import volunteer_schema, ngo_schema, problem_report_schema
from utils.helpers import is_valid_email, resolve_location_payload

auth_bp = Blueprint("auth", __name__)


def _make_tokens(user_id: str, user_type: str):
    """
    Create access + refresh tokens.
    identity  = plain string MongoDB _id  (reliable in flask-jwt-extended 4.x)
    user_type = stored as additional claim (avoids dict-identity 422 bug)
    """
    claims  = {"user_type": user_type}
    access  = create_access_token(identity=str(user_id), additional_claims=claims)
    refresh = create_refresh_token(identity=str(user_id), additional_claims=claims)
    return access, refresh


# ── Volunteer Signup ──────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/signup", methods=["POST"])
def volunteer_signup():
    db   = current_app.db
    data = request.get_json(silent=True) or {}

    required = ["name", "email", "password", "phone", "pincode"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "Invalid email format"}), 400

    if db.volunteers.find_one({"email": data["email"].lower()}):
        return jsonify({"error": "Email already registered"}), 409

    loc = resolve_location_payload(data, require_pincode=True)
    if loc.get("error"):
        return jsonify({"error": loc["error"]}), 400

    doc = volunteer_schema(
        name          = data["name"],
        email         = data["email"],
        password_hash = generate_password_hash(data["password"]),
        phone         = data.get("phone", ""),
        lat           = float(loc["lat"]),
        lng           = float(loc["lng"]),
        skills        = data.get("skills", []),
        availability  = data.get("availability", []),
        pincode       = loc.get("pincode", data.get("pincode", "")),
    )
    result = db.volunteers.insert_one(doc)
    vid    = str(result.inserted_id)

    access_token, refresh_token = _make_tokens(vid, "volunteer")

    return jsonify({
        "message":       "Volunteer registered successfully",
        "id":            vid,
        "type":          "volunteer",
        "name":          data["name"],
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 201


# ── Volunteer Login ───────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/login", methods=["POST"])
def volunteer_login():
    db   = current_app.db
    data = request.get_json(silent=True) or {}

    email    = data.get("email", "").lower()
    password = data.get("password", "")

    volunteer = db.volunteers.find_one({"email": email})
    if not volunteer or not check_password_hash(volunteer["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    if volunteer.get("status") == "banned":
        return jsonify({"error": "Account banned. Contact support."}), 403

    vid = str(volunteer["_id"])
    access_token, refresh_token = _make_tokens(vid, "volunteer")

    return jsonify({
        "message":       "Login successful",
        "id":            vid,
        "type":          "volunteer",
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
    data = request.get_json(silent=True) or {}

    required = ["name", "email", "password", "phone", "registration_number", "pincode"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "Invalid email format"}), 400

    if db.ngos.find_one({"email": data["email"].lower()}):
        return jsonify({"error": "Email already registered"}), 409

    loc = resolve_location_payload(data, require_pincode=True)
    if loc.get("error"):
        return jsonify({"error": loc["error"]}), 400

    doc = ngo_schema(
        name                = data["name"],
        email               = data["email"],
        password_hash       = generate_password_hash(data["password"]),
        phone               = data["phone"],
        registration_number = data["registration_number"],
        lat                 = float(loc["lat"]),
        lng                 = float(loc["lng"]),
        focus_areas         = data.get("focus_areas", []),
        pincode             = loc.get("pincode", data.get("pincode", "")),
    )
    result = db.ngos.insert_one(doc)
    nid    = str(result.inserted_id)

    access_token, refresh_token = _make_tokens(nid, "ngo")

    return jsonify({
        "message":       "NGO registered successfully",
        "id":            nid,
        "type":          "ngo",
        "name":          data["name"],
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 201


# ── NGO Login ─────────────────────────────────────────────────────────────────

@auth_bp.route("/ngo/login", methods=["POST"])
def ngo_login():
    db   = current_app.db
    data = request.get_json(silent=True) or {}

    email    = data.get("email", "").lower()
    password = data.get("password", "")

    ngo = db.ngos.find_one({"email": email})
    if not ngo or not check_password_hash(ngo["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    if ngo.get("status") != "active":
        return jsonify({"error": "NGO account is not active"}), 403

    nid = str(ngo["_id"])
    access_token, refresh_token = _make_tokens(nid, "ngo")

    return jsonify({
        "message":       "Login successful",
        "id":            nid,
        "type":          "ngo",
        "name":          ngo["name"],
        "is_verified":   ngo.get("is_verified", False),
        "access_token":  access_token,
        "refresh_token": refresh_token,
    }), 200


# ── Refresh Token ─────────────────────────────────────────────────────────────

@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id    = get_jwt_identity()           # plain string id
    old_claims = get_jwt()                    # read user_type from existing claim
    user_type  = old_claims.get("user_type", "volunteer")

    access_token, _ = _make_tokens(user_id, user_type)
    return jsonify({"access_token": access_token}), 200


# ── Community Problem Report (no login required) ──────────────────────────────

@auth_bp.route("/report-problem", methods=["POST"])
def report_problem():
    db   = current_app.db
    data = request.get_json(silent=True) or {}

    required = ["reporter_name", "reporter_contact", "problem_type", "description", "pincode"]
    missing  = [f for f in required if f not in data or not data[f]]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    loc = resolve_location_payload(data, require_pincode=True)
    if loc.get("error"):
        return jsonify({"error": loc["error"]}), 400

    doc = problem_report_schema(
        reporter_name         = data["reporter_name"],
        reporter_contact      = data["reporter_contact"],
        problem_type          = data["problem_type"],
        description           = data["description"],
        lat                   = float(loc["lat"]),
        lng                   = float(loc["lng"]),
        address               = data.get("address", ""),
        urgency_self_reported = data.get("urgency", "low"),
        media_urls            = data.get("media_urls", []),
        pincode               = loc.get("pincode", data.get("pincode", "")),
    )
    result = db.problem_reports.insert_one(doc)
    return jsonify({
        "message":   "Problem reported. It will be reviewed by a local NGO.",
        "report_id": str(result.inserted_id),
    }), 201
