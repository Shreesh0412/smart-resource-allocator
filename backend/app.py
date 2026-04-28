"""
Smart Resource Allocation - Volunteer Coordination Platform
Main Flask Application Entry Point
"""
from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

import certifi
from flask import Flask, jsonify, render_template, redirect, url_for, send_from_directory, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import MongoClient, GEOSPHERE

from config import Config

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_TEMPLATES = (BASE_DIR / ".." / "frontend" / "templates").resolve()
FRONTEND_STATIC = (BASE_DIR / ".." / "frontend" / "static").resolve()

app = Flask(
    __name__,
    template_folder=str(FRONTEND_TEMPLATES),
    static_folder=str(FRONTEND_STATIC),
    static_url_path="/static",
)
app.config.from_object(Config)

# ✅ FIX FOR RENDER: Create the upload folder immediately so Gunicorn sees it
os.makedirs(app.config.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)

CORS(app, resources={r"/api/*": {"origins": "*"}})
jwt = JWTManager(app)

client = MongoClient(app.config["MONGO_URI"], tlsCAFile=certifi.where())
db = client[app.config["DB_NAME"]]
app.db = db

def _is_api_call():
    # Frontend fetches send this header; direct browser navigation does not.
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def create_indexes():
    db.tasks.create_index([("location", GEOSPHERE)])
    db.volunteers.create_index([("location", GEOSPHERE)])
    db.ngos.create_index([("location", GEOSPHERE)])
    db.tasks.create_index([("title", "text"), ("description", "text")])
    db.tasks.create_index("deadline")
    db.tasks.create_index("status")
    db.tasks.create_index("urgency")
    db.volunteers.create_index("trust_score")
    db.notifications.create_index("created_at")
    db.problem_reports.create_index("status")
    print("✅ MongoDB indexes created")

# Ensure indexes exist on startup (works for both dev server and gunicorn)
try:
    with app.app_context():
        create_indexes()
except Exception as _index_exc:
    print(f"⚠️ MongoDB index creation skipped: {_index_exc}")

from routes.auth_routes import auth_bp
from routes.volunteer_routes import volunteer_bp
from routes.ngo_routes import ngo_bp
from routes.task_routes import task_bp
from routes.map_routes import map_bp
from routes.admin_routes import admin_bp

app.register_blueprint(auth_bp,      url_prefix="/api/auth")
app.register_blueprint(volunteer_bp, url_prefix="/api/volunteer")
app.register_blueprint(ngo_bp,       url_prefix="/api/ngo")
app.register_blueprint(task_bp,      url_prefix="/api/tasks")
app.register_blueprint(map_bp,       url_prefix="/api/map")
app.register_blueprint(admin_bp,     url_prefix="/api/admin")


@jwt.unauthorized_loader
def missing_token(reason):
    if _is_api_call():
        return jsonify({"error": "Missing or invalid token", "reason": reason}), 401
    return redirect(url_for("login_page")), 302


@jwt.expired_token_loader
def expired_token(jwt_header, jwt_payload):
    if _is_api_call():
        return jsonify({"error": "Token has expired"}), 401
    return redirect(url_for("login_page")), 302


@jwt.invalid_token_loader
def invalid_token(reason):
    if _is_api_call():
        return jsonify({"error": "Invalid token", "reason": reason}), 422
    return redirect(url_for("login_page")), 302


# ── Frontend Pages ────────────────────────────────────────────────────────
@app.route("/")
@app.route("/index.html", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/login.html", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.route("/signup.html", methods=["GET"])
def signup_page():
    return render_template("signup.html")


@app.route("/volunteer-dashboard.html", methods=["GET"])
def volunteer_dashboard_page():
    return render_template("volunteer-dashboard.html")


@app.route("/ngo-dashboard.html", methods=["GET"])
def ngo_dashboard_page():
    return render_template("ngo-dashboard.html")


@app.route("/map.html", methods=["GET"])
def map_page():
    return render_template("map.html")


@app.route("/report-problem.html", methods=["GET"])
def report_problem_page():
    return render_template("report-problem.html")

@app.route("/uploads/proof_of_work/<path:filename>", methods=["GET"])
def uploaded_proof(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# Backward compatibility for old URLs that still include /templates/
@app.route("/templates/<path:page>", methods=["GET"])
def legacy_templates(page):
    if page.endswith(".html"):
        return redirect("/" + page, code=301)
    return redirect("/", code=301)


@app.route("/api/health", methods=["GET"])
def health():
    try:
        db.command("ping")
        return jsonify({"status": "ok", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Route not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False), host="0.0.0.0", port=5000)
