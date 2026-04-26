"""
utils/decorators.py  — FIXED
Reads user_type from get_jwt() additional claims (not from identity dict).
This matches the new _make_tokens() approach in auth_routes.py.
"""

from functools import wraps
from flask import current_app, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, get_jwt
from bson import ObjectId


def _get_identity_doc():
    """
    Returns (db_document, user_type) for the currently authenticated user.
    identity  = plain string MongoDB _id
    user_type = read from JWT additional claim "user_type"
    """
    try:
        user_id   = get_jwt_identity()       # plain string id
        claims    = get_jwt()                # additional claims dict
        user_type = claims.get("user_type")
    except Exception:
        return None, None

    if not user_id or not user_type:
        return None, None

    db = current_app.db
    try:
        uid = ObjectId(user_id)
    except Exception:
        return None, None

    if user_type == "volunteer":
        doc = db.volunteers.find_one({"_id": uid})
    elif user_type == "ngo":
        doc = db.ngos.find_one({"_id": uid})
    elif user_type == "admin":
        doc = db.admins.find_one({"_id": uid})
    else:
        doc = None

    return doc, user_type


def volunteer_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        doc, utype = _get_identity_doc()
        if not doc or utype != "volunteer":
            return jsonify({"error": "Volunteer access only"}), 403
        if doc.get("status") == "banned":
            return jsonify({"error": "Account banned"}), 403
        return fn(*args, **kwargs)
    return wrapper


def ngo_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        doc, utype = _get_identity_doc()
        if not doc or utype != "ngo":
            return jsonify({"error": "NGO access only"}), 403
        if doc.get("status") != "active":
            return jsonify({"error": "NGO account inactive"}), 403
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        doc, utype = _get_identity_doc()
        if not doc or utype != "admin":
            return jsonify({"error": "Admin access only"}), 403
        return fn(*args, **kwargs)
    return wrapper


def any_authenticated(fn):
    """Allows volunteer, ngo, or admin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        doc, utype = _get_identity_doc()
        if not doc:
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper
