"""
services/notification_service.py
---------------------------------
★ Link to WhatsApp / Real-time Notifications  (from your notes)

Handles:
  - WhatsApp messages via Twilio API
  - In-app notifications (stored in MongoDB, polled or WebSocket-ready)
  - Bulk notify matched volunteers when a new task is posted
  - Urgency escalation alerts

Twilio WhatsApp Sandbox:
  1. Sign up at twilio.com
  2. Join sandbox: send "join <code>" to +1 415 523 8886
  3. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── WhatsApp via Twilio ────────────────────────────────────────────────────────

def send_whatsapp(to: str, message: str, config: dict) -> bool:
    """
    Sends a WhatsApp message using Twilio.
    `to` should be a phone number like "+919876543210".
    Returns True on success, False on failure.
    Gracefully degrades if Twilio credentials are missing (dev mode).
    """
    sid   = config.get("TWILIO_ACCOUNT_SID",   "")
    token = config.get("TWILIO_AUTH_TOKEN",     "")
    from_ = config.get("TWILIO_WHATSAPP_FROM",  "whatsapp:+14155238886")

    if not sid or not token:
        logger.warning(f"[WhatsApp DEV] → {to}: {message}")
        return False          # Dev mode — just log, don't fail

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msg = client.messages.create(
            from_= from_,
            to   = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
            body = message,
        )
        logger.info(f"WhatsApp sent to {to}: SID={msg.sid}")
        return True
    except Exception as e:
        logger.error(f"WhatsApp send failed to {to}: {e}")
        return False


# ── Bulk notify matched volunteers (new task alert) ────────────────────────────

def notify_matched_volunteers(db, volunteer_ids: List[str], task: dict, config: dict):
    """
    Sends in-app + WhatsApp notification to all auto-matched volunteers
    when a new task is posted by an NGO.
    """
    from models.schemas import notification_schema, utcnow
    from bson import ObjectId

    task_title   = task.get("title", "A new task")
    task_address = task.get("address", "See app for location")
    urgency      = task.get("urgency", "low")
    deadline     = task.get("deadline", "")

    urgency_emoji = {"low": "🟢", "med": "🟡", "urgent": "🔴"}.get(urgency, "")

    for vol_id in volunteer_ids:
        vol = db.volunteers.find_one({"_id": ObjectId(vol_id)})
        if not vol:
            continue

        # ── In-app notification ─────────────────────────────────────────────
        notif = notification_schema(
            recipient_id   = vol_id,
            recipient_type = "volunteer",
            title          = f"{urgency_emoji} New Task Match: {task_title}",
            message        = (f"A task matching your skills is available near you.\n"
                              f"📍 {task_address}\n"
                              f"⏰ Deadline: {deadline}\n"
                              f"Urgency: {urgency.upper()}"),
            notif_type     = "task_match",
            reference_id   = str(task.get("_id", "")),
            channel        = "both" if vol.get("whatsapp_opt_in") else "in_app",
        )
        db.notifications.insert_one(notif)

        # ── WhatsApp ────────────────────────────────────────────────────────
        if vol.get("whatsapp_opt_in") and vol.get("phone"):
            wa_message = (
                f"Hi {vol['name']}! 👋\n\n"
                f"{urgency_emoji} *New Task Near You*\n"
                f"📌 {task_title}\n"
                f"📍 {task_address}\n"
                f"⏰ Deadline: {deadline}\n"
                f"🚨 Urgency: {urgency.upper()}\n\n"
                f"Open the app to apply. Reply STOP to opt out."
            )
            sent = send_whatsapp(vol["phone"], wa_message, config)
            if sent:
                db.notifications.update_one(
                    {"recipient_id": vol_id, "type": "task_match"},
                    {"$set": {"whatsapp_sent": True}}
                )


# ── Urgency escalation blast ──────────────────────────────────────────────────

def send_urgency_alert(db, task: dict, config: dict):
    """
    Sends an urgent WhatsApp blast to all assigned volunteers
    when task urgency is escalated to URGENT by the NGO.
    """
    from bson import ObjectId

    assigned = task.get("assigned_volunteers", [])
    message = (
        f"🔴 *URGENT TASK ALERT*\n"
        f"Task: {task.get('title', '')}\n"
        f"📍 {task.get('address', '')}\n"
        f"This task has been marked URGENT by the NGO.\n"
        f"Please act immediately. Open the app for details."
    )

    for vol_id in assigned:
        vol = db.volunteers.find_one({"_id": ObjectId(vol_id)}, {"phone": 1, "whatsapp_opt_in": 1, "name": 1})
        if vol and vol.get("whatsapp_opt_in") and vol.get("phone"):
            send_whatsapp(vol["phone"], message, config)


# ── Deadline reminder (call via cron/scheduler) ───────────────────────────────

def send_deadline_reminders(db, config: dict):
    """
    Scans for tasks with deadlines within 24 hours and sends reminders.
    Intended to be called by a cron job / APScheduler every hour.
    """
    from datetime import datetime, timedelta
    from bson import ObjectId

    now         = datetime.utcnow()
    in_24h      = now + timedelta(hours=24)

    # Tasks still open/in-progress with deadline in next 24h
    urgent_tasks = list(db.tasks.find({
        "status":   {"$in": ["open", "assigned", "in_progress"]},
        "deadline": {
            "$gte": now.isoformat(),
            "$lte": in_24h.isoformat(),
        }
    }))

    for task in urgent_tasks:
        assigned = task.get("assigned_volunteers", [])

        # Remind volunteers
        for vol_id in assigned:
            vol = db.volunteers.find_one(
                {"_id": ObjectId(vol_id)},
                {"name": 1, "phone": 1, "whatsapp_opt_in": 1}
            )
            if vol and vol.get("whatsapp_opt_in") and vol.get("phone"):
                send_whatsapp(
                    vol["phone"],
                    f"⏰ Reminder: Task '{task.get('title', '')}' deadline is within 24 hours! "
                    f"Please submit proof of work if done.",
                    config
                )

        # Remind NGO if volunteers not assigned
        if len(assigned) < task.get("volunteers_needed", 1):
            ngo = db.ngos.find_one({"_id": ObjectId(task["ngo_id"])}, {"phone": 1, "name": 1})
            if ngo and ngo.get("phone"):
                send_whatsapp(
                    ngo["phone"],
                    f"⚠️ Task '{task.get('title', '')}' has unfilled volunteer slots and deadline is in <24h!",
                    config
                )

    return len(urgent_tasks)
