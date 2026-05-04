"""
routes/auth_routes.py
FIXES:
  S4 — Rate limiting on all login and public report endpoints.
  S5 — Tokens are now set as HttpOnly cookies (not returned in JSON body).
       HttpOnly cookies cannot be read by JavaScript, so XSS attacks cannot
       steal them. Access and refresh tokens are completely invisible to JS.

       New endpoint: POST /auth/logout — clears the HttpOnly cookies.

       config.py must have:
         JWT_TOKEN_LOCATION      = ["cookies"]
         JWT_COOKIE_SECURE       = True   (HTTPS only; False for local dev)
         JWT_COOKIE_SAMESITE     = "Strict"
         JWT_COOKIE_CSRF_PROTECT = False  (XSS fixed in S2; CSRF via SameSite=Strict)
"""

from flask import Blueprint, request, jsonify, make_response, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
    set_access_cookies, set_refresh_cookies, unset_jwt_cookies,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

from models.schemas import volunteer_schema, ngo_schema, problem_report_schema
from utils.helpers import is_valid_email, resolve_location_payload
from services.task_predictor import extract_resources

auth_bp = Blueprint("auth", __name__)

# FIX #14: This is a placeholder replaced by app.py immediately after import:
#   import routes.auth_routes as _auth_mod
#   _auth_mod.limiter = limiter   # the single app-level Limiter
# This avoids creating a second Limiter instance that doubles rate-limit
# counting when both are attached to the same Flask app.
limiter = Limiter(get_remote_address)


def _make_tokens(user_id: str, user_type: str):
    claims  = {"user_type": user_type}
    access  = create_access_token(identity=str(user_id), additional_claims=claims)
    refresh = create_refresh_token(identity=str(user_id), additional_claims=claims)
    return access, refresh


def _auth_response(payload: dict, access_token: str, refresh_token: str, status: int):
    """
    S5 FIX: Sets access and refresh tokens as HttpOnly cookies instead of
    returning them in the JSON body. JSON only contains non-sensitive UI data.
    """
    resp = make_response(jsonify(payload), status)
    set_access_cookies(resp, access_token)
    set_refresh_cookies(resp, refresh_token)
    return resp


# ── Volunteer Signup ──────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/signup", methods=["POST"])
@limiter.limit("10 per minute")
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

    return _auth_response({
        "message": "Volunteer registered successfully",
        "id":      vid,
        "type":    "volunteer",
        "name":    data["name"],
    }, access_token, refresh_token, 201)


# ── Volunteer Login ───────────────────────────────────────────────────────────

@auth_bp.route("/volunteer/login", methods=["POST"])
@limiter.limit("10 per minute")
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

    return _auth_response({
        "message":     "Login successful",
        "id":          vid,
        "type":        "volunteer",
        "name":        volunteer["name"],
        "trust_score": volunteer.get("trust_score", 50),
        "is_verified": volunteer.get("is_verified", False),
    }, access_token, refresh_token, 200)


# ── NGO Signup ────────────────────────────────────────────────────────────────

@auth_bp.route("/ngo/signup", methods=["POST"])
@limiter.limit("10 per minute")
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

    return _auth_response({
        "message": "NGO registered successfully",
        "id":      nid,
        "type":    "ngo",
        "name":    data["name"],
    }, access_token, refresh_token, 201)


# ── NGO Login ─────────────────────────────────────────────────────────────────

@auth_bp.route("/ngo/login", methods=["POST"])
@limiter.limit("10 per minute")
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

    return _auth_response({
        "message":     "Login successful",
        "id":          nid,
        "type":        "ngo",
        "name":        ngo["name"],
        "is_verified": ngo.get("is_verified", False),
    }, access_token, refresh_token, 200)


# ── Refresh Token ─────────────────────────────────────────────────────────────

@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """S5: Browser sends the HttpOnly refresh_token cookie automatically."""
    user_id    = get_jwt_identity()
    old_claims = get_jwt()
    user_type  = old_claims.get("user_type", "volunteer")

    new_access, _ = _make_tokens(user_id, user_type)
    resp = make_response(jsonify({"message": "Token refreshed"}), 200)
    set_access_cookies(resp, new_access)
    return resp


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    S5: Clears HttpOnly cookies server-side. The browser cannot clear HttpOnly
    cookies itself — this endpoint is required. api.js Auth.logout() calls this.
    """
    resp = make_response(jsonify({"message": "Logged out"}), 200)
    unset_jwt_cookies(resp)
    return resp


# ── Community Problem Report ──────────────────────────────────────────────────

@auth_bp.route("/report-problem", methods=["POST"])
@limiter.limit("20 per hour")
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

    extracted = extract_resources(data["description"], current_app.config)

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
        extracted_resources   = extracted,
    )
    result = db.problem_reports.insert_one(doc)
    return jsonify({
        "message":   "Problem reported. It will be reviewed by a local NGO.",
        "report_id": str(result.inserted_id),
        "extracted": extracted,
    }), 201
