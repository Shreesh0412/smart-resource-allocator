"""
utils/decorators.py
-------------------
JWT-based role decorators — wrap any route to enforce
volunteer / NGO / admin access.
"""

from functools import wraps
from flask import current_app, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from bson import ObjectId


def _get_identity_doc():
    identity = get_jwt_identity()          # {"id": "...", "type": "volunteer|ngo|admin"}
    if not identity:
        return None, None
    db  = current_app.db
    uid = ObjectId(identity["id"])
    utype = identity.get("type")
    if utype == "volunteer":
        doc = db.volunteers.find_one({"_id": uid})
    elif utype == "ngo":
        doc = db.ngos.find_one({"_id": uid})
    elif utype == "admin":
        doc = db.admins.find_one({"_id": uid})
    else:
        doc = None
    return doc, utype


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
