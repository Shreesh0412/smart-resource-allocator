"""
Configuration — all environment-driven so secrets never live in code.
Copy .env.example → .env and fill in real values before running.
"""

import os
from datetime import timedelta


class Config:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    # ── Core ──────────────────────────────────────────────────────────────────
    SECRET_KEY        = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
    DEBUG             = os.environ.get("DEBUG", "true").lower() == "true"

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME   = os.environ.get("DB_NAME",   "volunteer_platform")

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY            = os.environ.get("JWT_SECRET_KEY", "jwt-dev-secret")
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # ── File Uploads (Proof of Work) ──────────────────────────────────────────
    UPLOAD_FOLDER       = os.environ.get("UPLOAD_FOLDER", "uploads/proof_of_work")
    MAX_CONTENT_LENGTH  = 16 * 1024 * 1024          # 16 MB
    ALLOWED_EXTENSIONS  = {"png", "jpg", "jpeg", "gif", "pdf", "mp4", "mov"}

    # ── Twilio / WhatsApp Notifications ───────────────────────────────────────
    TWILIO_ACCOUNT_SID   = os.environ.get("TWILIO_ACCOUNT_SID",  "")
    TWILIO_AUTH_TOKEN    = os.environ.get("TWILIO_AUTH_TOKEN",   "")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM","whatsapp:+14155238886")

    # ── Task Urgency Thresholds (days remaining → urgency level) ─────────────
    #   LOW  : > 7 days
    #   MED  : 2-7 days
    #   URGENT: ≤ 1 day
    URGENCY_LOW_DAYS    = 7
    URGENCY_MED_DAYS    = 2
    URGENCY_URGENT_DAYS = 1

    # ── Geo Matching ─────────────────────────────────────────────────────────
    DEFAULT_MATCH_RADIUS_KM = 10         # radius for auto-matching volunteers
    MAX_MATCH_RADIUS_KM     = 50

    # ── Trust Score Weights ───────────────────────────────────────────────────
    TRUST_TASK_COMPLETE_WEIGHT  = 10
    TRUST_REVIEW_WEIGHT         = 5
    TRUST_ONTIME_BONUS          = 3
    TRUST_LATE_PENALTY          = -4
    TRUST_REJECTED_PENALTY      = -2
    TRUST_VERIFIED_BADGE_BONUS  = 20

    # ── Inefficiency Detector ─────────────────────────────────────────────────
    INEFFICIENCY_THRESHOLD_KM   = 5     # flag if volunteer traveled > X km beyond optimal

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
