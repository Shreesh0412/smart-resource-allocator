"""
app.py — Main Flask Application Entry Point
FIXES:
  S8 — CORS locked to Config.CORS_ORIGINS env var instead of hardcoded "*".
  S4 — Flask-Limiter created here and wired to auth_routes limiter.
  S5 — credentials: 'include' on the frontend sends cookies; backend just needs
       JWT_TOKEN_LOCATION = ["cookies"] in config (already set in config.py).
       Added a 429 error handler for rate-limit responses.
"""

from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

import certifi
from flask import Flask, jsonify, render_template, send_from_directory, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient, GEOSPHERE

from config import Config

BASE_DIR           = Path(__file__).resolve().parent
FRONTEND_TEMPLATES = (BASE_DIR / ".." / "frontend" / "templates").resolve()
FRONTEND_STATIC    = (BASE_DIR / ".." / "frontend" / "static").resolve()

app = Flask(
    __name__,
    template_folder=str(FRONTEND_TEMPLATES),
    static_folder=str(FRONTEND_STATIC),
    static_url_path="/static",
)
app.config.from_object(Config)

os.makedirs(app.config.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)

# S8 FIX: Restrict CORS to Config.CORS_ORIGINS instead of hardcoded "*".
# Also allow credentials so the browser sends HttpOnly cookies cross-origin
# (only relevant when frontend and backend are on different subdomains).
CORS(app, resources={r"/api/*": {
    "origins":     app.config["CORS_ORIGINS"],
    "supports_credentials": True,
}})

jwt = JWTManager(app)

# FIX #14: Only ONE Limiter instance attached to the app.
# Previously app.py created a Limiter with app=app, then auth_routes.py
# created a SECOND separate Limiter and called init_app(app) on it too.
# This meant every auth request hit both limiters causing unexpected 429s.
# Solution: create one limiter here, import and reuse it in auth_routes.py.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://",
)
app.limiter = limiter

client = MongoClient(app.config["MONGO_URI"], tlsCAFile=certifi.where())
db     = client[app.config["DB_NAME"]]
app.db = db


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

# FIX #14: Pass the single app-level limiter to auth_routes so it uses
# the same instance instead of creating its own second one.
import routes.auth_routes as _auth_mod
_auth_mod.limiter = limiter

app.register_blueprint(auth_bp,      url_prefix="/api/auth")
app.register_blueprint(volunteer_bp, url_prefix="/api/volunteer")
app.register_blueprint(ngo_bp,       url_prefix="/api/ngo")
app.register_blueprint(task_bp,      url_prefix="/api/tasks")
app.register_blueprint(map_bp,       url_prefix="/api/map")
app.register_blueprint(admin_bp,     url_prefix="/api/admin")


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/index.html")
def home():
    return render_template("index.html")

@app.route("/login.html")
def login_page():
    return render_template("login.html")

@app.route("/signup.html")
def signup_page():
    return render_template("signup.html")

@app.route("/volunteer-dashboard.html")
def volunteer_dashboard_page():
    return render_template("volunteer-dashboard.html")

@app.route("/ngo-dashboard.html")
def ngo_dashboard_page():
    return render_template("ngo-dashboard.html")

@app.route("/map.html")
def map_page():
    return render_template("map.html")

@app.route("/report-problem.html")
def report_problem_page():
    return render_template("report-problem.html")

@app.route("/uploads/proof_of_work/<path:filename>")
def uploaded_proof(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Route not found"}), 404

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Too many requests. Please slow down."}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False), host="0.0.0.0", port=5000)
