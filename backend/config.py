"""
config.py
FIXES:
  S3 — SECRET_KEY and JWT_SECRET_KEY have no weak fallback defaults.
       Missing env vars cause a startup crash with a clear message,
       forcing every deployment to set them explicitly.
  S5 — JWT is now configured to use HttpOnly cookies instead of Bearer tokens.
       Tokens are invisible to JavaScript, eliminating the localStorage XSS risk.

  HOW TO GENERATE SECRETS (run once, store in .env / Render env vars):
    python -c "import secrets; print(secrets.token_hex(32))"
    Run twice — one value for SECRET_KEY, another for JWT_SECRET_KEY.
"""

import os
from datetime import timedelta


class Config:
    GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY")
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

    # ── Core ──────────────────────────────────────────────────────────────────
    # S3 FIX: No fallback. Missing key = startup crash, not silent vulnerability.
    SECRET_KEY = os.environ["SECRET_KEY"]
    DEBUG      = os.environ.get("DEBUG", "false").lower() == "true"

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME   = os.environ.get("DB_NAME",   "volunteer_platform")

    # ── JWT ───────────────────────────────────────────────────────────────────
    # S3 FIX: No fallback default.
    JWT_SECRET_KEY            = os.environ["JWT_SECRET_KEY"]
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # S5 FIX: Store tokens in HttpOnly cookies, not in the response body.
    # HttpOnly cookies are invisible to JavaScript — XSS cannot steal them.
    JWT_TOKEN_LOCATION      = ["cookies"]
    # Set to True in production (requires HTTPS). False for local HTTP dev.
    JWT_COOKIE_SECURE       = os.environ.get("JWT_COOKIE_SECURE", "false").lower() == "true"
    JWT_COOKIE_SAMESITE     = "Strict"   # prevents CSRF on same-site requests
    JWT_COOKIE_CSRF_PROTECT = False       # SameSite=Strict + S2 XSS fix covers this

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER      = os.environ.get("UPLOAD_FOLDER", "uploads/proof_of_work")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "mp4", "mov"}

    # ── Twilio / WhatsApp ─────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID   = os.environ.get("TWILIO_ACCOUNT_SID",   "")
    TWILIO_AUTH_TOKEN    = os.environ.get("TWILIO_AUTH_TOKEN",    "")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    # ── Task Urgency Thresholds ───────────────────────────────────────────────
    URGENCY_LOW_DAYS    = 7
    URGENCY_MED_DAYS    = 2
    URGENCY_URGENT_DAYS = 1

    # ── Geo Matching ─────────────────────────────────────────────────────────
    DEFAULT_MATCH_RADIUS_KM = 10
    MAX_MATCH_RADIUS_KM     = 50

    # ── Trust Score Weights ───────────────────────────────────────────────────
    TRUST_TASK_COMPLETE_WEIGHT = 10
    TRUST_REVIEW_WEIGHT        = 5
    TRUST_ONTIME_BONUS         = 3
    TRUST_LATE_PENALTY         = -4
    TRUST_REJECTED_PENALTY     = -2
    TRUST_VERIFIED_BADGE_BONUS = 20

    # ── Inefficiency Detector ─────────────────────────────────────────────────
    INEFFICIENCY_THRESHOLD_KM = 5

    # ── CORS ─────────────────────────────────────────────────────────────────
    # S8 FIX: Set CORS_ORIGINS to your production domain, e.g.
    # "https://saarthi.onrender.com". Defaults to "*" only for local dev.
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
