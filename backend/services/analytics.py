"""
services/analytics.py
----------------------
Builds analytics data for the NGO dashboard.
Called by /api/ngo/analytics endpoint.
"""

from bson import ObjectId
from datetime import datetime, timedelta


def build_ngo_analytics(db, ngo_id: str) -> dict:
    """
    Returns a full analytics snapshot for one NGO.
    """
    # Basic counts
    total_posted    = db.tasks.count_documents({"ngo_id": ngo_id})
    total_completed = db.tasks.count_documents({"ngo_id": ngo_id, "status": "completed"})
    total_cancelled = db.tasks.count_documents({"ngo_id": ngo_id, "status": "cancelled"})
    open_tasks      = db.tasks.count_documents({"ngo_id": ngo_id, "status": {"$in": ["open","assigned","in_progress"]}})

    # Active volunteer count (unique volunteers on this NGO's tasks)
    assigned_pipeline = [
        {"$match": {"ngo_id": ngo_id, "status": {"$in": ["assigned","in_progress"]}}},
        {"$unwind": "$assigned_volunteers"},
        {"$group": {"_id": "$assigned_volunteers"}},
        {"$count": "total"}
    ]
    active_vol_result = list(db.tasks.aggregate(assigned_pipeline))
    active_volunteers = active_vol_result[0]["total"] if active_vol_result else 0

    # Tasks by type
    type_pipeline = [
        {"$match": {"ngo_id": ngo_id}},
        {"$group": {"_id": "$task_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    tasks_by_type = [
        {"task_type": t["_id"], "count": t["count"]}
        for t in db.tasks.aggregate(type_pipeline)
    ]

    # Tasks by urgency
    urgency_pipeline = [
        {"$match": {"ngo_id": ngo_id, "status": {"$in": ["open","assigned","in_progress"]}}},
        {"$group": {"_id": "$urgency", "count": {"$sum": 1}}}
    ]
    urgency_counts = {u["_id"]: u["count"] for u in db.tasks.aggregate(urgency_pipeline)}

    # Completion rate over last 30 days
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    recent_completed = db.tasks.count_documents({
        "ngo_id":       ngo_id,
        "status":       "completed",
        "completed_at": {"$gte": thirty_days_ago}
    })

    # Top volunteers for this NGO (by tasks completed under this NGO's tasks)
    vol_pipeline = [
        {"$match": {"ngo_id": ngo_id, "status": "completed"}},
        {"$unwind": "$assigned_volunteers"},
        {"$group": {"_id": "$assigned_volunteers", "tasks_done": {"$sum": 1}}},
        {"$sort": {"tasks_done": -1}},
        {"$limit": 5}
    ]
    top_vol_ids = list(db.tasks.aggregate(vol_pipeline))
    top_volunteers = []
    for entry in top_vol_ids:
        vol = db.volunteers.find_one(
            {"_id": ObjectId(entry["_id"])},
            {"name": 1, "trust_score": 1, "verified_badge": 1}
        )
        if vol:
            top_volunteers.append({
                "id":            str(vol["_id"]),
                "name":          vol.get("name", "—"),
                "trust_score":   vol.get("trust_score", 50),
                "verified_badge":vol.get("verified_badge", False),
                "total_tasks_done": entry["tasks_done"],
            })

    # Inefficiency summary for this NGO's tasks
    task_ids = [str(t["_id"]) for t in db.tasks.find({"ngo_id": ngo_id}, {"_id": 1})]
    inefficiency_flags = db.travel_logs.count_documents({
        "task_id": {"$in": task_ids},
        "flagged": True
    })

    return {
        "total_tasks_posted":    total_posted,
        "total_tasks_completed": total_completed,
        "total_tasks_cancelled": total_cancelled,
        "open_tasks":            open_tasks,
        "active_volunteers":     active_volunteers,
        "completion_rate":       round(total_completed / total_posted * 100, 1) if total_posted else 0,
        "recent_completed_30d":  recent_completed,
        "tasks_by_type":         tasks_by_type,
        "urgency_counts":        urgency_counts,
        "top_volunteers":        top_volunteers,
        "inefficiency_flags":    inefficiency_flags,
    }
