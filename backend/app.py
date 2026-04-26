"""
Smart Resource Allocation - Volunteer Coordination Platform
Main Flask Application Entry Point
"""
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import MongoClient, GEOSPHERE
from config import Config
import os
print("MONGO_URI =", os.getenv("MONGO_URI"))
import os
print("MONGO_URI =", os.getenv("MONGO_URI"))
print("DB_NAME =", os.getenv("DB_NAME"))
app = Flask(__name__)
app.config.from_object(Config)

CORS(app, resources={r"/api/*": {"origins": "*"}})
jwt = JWTManager(app)

import certifi
client = MongoClient(app.config["MONGO_URI"], tlsCAFile=certifi.where())
db = client[app.config["DB_NAME"]]

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


from routes.auth_routes import auth_bp
from routes.volunteer_routes import volunteer_bp
from routes.ngo_routes import ngo_bp
from routes.task_routes import task_bp
from routes.map_routes import map_bp
from routes.admin_routes import admin_bp
from flask import render_template

# Home
@app.route("/")
def home():
    return render_template("index.html")

# Specific pages
@app.route("/login.html")
def login():
    return render_template("login.html")

@app.route("/signup.html")
def signup():
    return render_template("signup.html")

app.register_blueprint(auth_bp,      url_prefix="/api/auth")
app.register_blueprint(volunteer_bp, url_prefix="/api/volunteer")
app.register_blueprint(ngo_bp,       url_prefix="/api/ngo")
app.register_blueprint(task_bp,      url_prefix="/api/tasks")
app.register_blueprint(map_bp,       url_prefix="/api/map")
app.register_blueprint(admin_bp,     url_prefix="/api/admin")


@jwt.unauthorized_loader
def missing_token(reason):
    return jsonify({"error": "Missing or invalid token", "reason": reason}), 401

@jwt.expired_token_loader
def expired_token(jwt_header, jwt_payload):
    return jsonify({"error": "Token has expired"}), 401

@jwt.invalid_token_loader
def invalid_token(reason):
    return jsonify({"error": "Invalid token", "reason": reason}), 422


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
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    create_indexes()
    app.run(debug=True, host="0.0.0.0", port=5000)
