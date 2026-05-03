"""
routes/map_routes.py
ADDITION for S1 fix:
  A new /api/map/maps-key endpoint returns the Google Maps API key only to
  authenticated users. This replaces embedding the key directly in the Jinja2
  template (map.html), where it was visible in the page source to anyone.

  The key is injected dynamically via JavaScript in map.html after the user's
  session is validated, so it never appears in the initial HTML payload.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity

from utils.decorators import any_authenticated
from utils.helpers import serialize_list, to_oid

map_bp = Blueprint("map", __name__)


# ── S1 Fix: Serve Maps API key only to authenticated users ────────────────────

@map_bp.route("/maps-key", methods=["GET"])
@any_authenticated
def maps_key():
    """
    Returns the Google Maps API key to authenticated clients only.
    map.html fetches this and injects the Maps script dynamically,
    keeping the key out of the HTML source.
    """
    key = current_app.config.get("GOOGLE_MAPS_API_KEY", "")
    return jsonify({"key": key}), 200


# ── Heatmap — Task / Problem Density ──────────────────────────────────────────

@map_bp.route("/heatmap/tasks", methods=["GET"])
@any_authenticated
def task_heatmap():
    db      = current_app.db
    status  = request.args.get("status")
    urgency = request.args.get("urgency")
    ttype   = request.args.get("task_type")
    ngo_id  = request.args.get("ngo_id")

    query = {}
    if status:  query["status"]    = status
    if urgency: query["urgency"]   = urgency
    if ttype:   query["task_type"] = ttype
    if ngo_id:  query["ngo_id"]    = ngo_id

    urgency_weight = {"low": 1, "med": 3, "urgent": 5}

    tasks = list(db.tasks.find(query, {"lat": 1, "lng": 1, "urgency": 1, "title": 1}))
    heatmap_points = [
        {
            "lat":    t["lat"],
            "lng":    t["lng"],
            "weight": urgency_weight.get(t.get("urgency", "low"), 1),
            "label":  t.get("title", ""),
        }
        for t in tasks
    ]

    return jsonify({
        "type":   "heatmap",
        "source": "tasks",
        "points": heatmap_points,
        "total":  len(heatmap_points),
    }), 200


# ── Heatmap — Community Problem Reports ───────────────────────────────────────

@map_bp.route("/heatmap/problems", methods=["GET"])
@any_authenticated
def problem_heatmap():
    db     = current_app.db
    status = request.args.get("status", "pending")

    reports = list(db.problem_reports.find(
        {"status": status},
        {"lat": 1, "lng": 1, "urgency_self_reported": 1, "problem_type": 1}
    ))

    urgency_weight = {"low": 1, "med": 3, "urgent": 5}
    points = [
        {
            "lat":    r["lat"],
            "lng":    r["lng"],
            "weight": urgency_weight.get(r.get("urgency_self_reported", "low"), 1),
            "label":  r.get("problem_type", ""),
        }
        for r in reports
    ]
    return jsonify({"type": "heatmap", "source": "problem_reports", "points": points}), 200


# ── GeoJSON Task Pins ─────────────────────────────────────────────────────────

@map_bp.route("/geojson/tasks", methods=["GET"])
@any_authenticated
def task_geojson():
    db        = current_app.db
    status    = request.args.get("status")
    urgency   = request.args.get("urgency")
    task_type = request.args.get("task_type")

    query = {}
    if status:    query["status"]    = status
    if urgency:   query["urgency"]   = urgency
    if task_type: query["task_type"] = task_type

    tasks    = list(db.tasks.find(query))
    features = []
    for t in tasks:
        features.append({
            "type": "Feature",
            "geometry": {
                "type":        "Point",
                "coordinates": [t["lng"], t["lat"]]
            },
            "properties": {
                "id":                str(t["_id"]),
                "title":             t.get("title", ""),
                "task_type":         t.get("task_type", ""),
                "urgency":           t.get("urgency", "low"),
                "status":            t.get("status", "open"),
                "deadline":          t.get("deadline", ""),
                "description":       t.get("description", ""),
                "address":           t.get("address", ""),
                "volunteers_needed": t.get("volunteers_needed", 1),
                "assigned_count":    len(t.get("assigned_volunteers", [])),
            }
        })

    return jsonify({"type": "FeatureCollection", "features": features}), 200


# ── Live Volunteer Positions ──────────────────────────────────────────────────

@map_bp.route("/volunteers/positions", methods=["GET"])
@any_authenticated
def volunteer_positions():
    db      = current_app.db
    task_id = request.args.get("task_id")

    query = {"status": "active"}
    if task_id:
        task = db.tasks.find_one({"_id": to_oid(task_id)})
        if task:
            assigned    = task.get("assigned_volunteers", [])
            query["_id"] = {"$in": [to_oid(v) for v in assigned if to_oid(v)]}

    volunteers = list(db.volunteers.find(
        query,
        {"name": 1, "lat": 1, "lng": 1, "trust_score": 1, "active_task_id": 1, "updated_at": 1}
    ))

    features = []
    for v in volunteers:
        features.append({
            "type": "Feature",
            "geometry": {
                "type":        "Point",
                "coordinates": [v["lng"], v["lat"]]
            },
            "properties": {
                "id":             str(v["_id"]),
                "name":           v.get("name", ""),
                "trust_score":    v.get("trust_score", 50),
                "active_task_id": str(v["active_task_id"]) if v.get("active_task_id") else None,
                "last_seen":      v.get("updated_at", ""),
            }
        })

    return jsonify({"type": "FeatureCollection", "features": features}), 200


# ── Line Map — Volunteer-to-Task routing ──────────────────────────────────────

@map_bp.route("/lines/volunteer-to-task", methods=["GET"])
@any_authenticated
def volunteer_to_task_lines():
    db = current_app.db

    active_tasks = list(db.tasks.find(
        {"status": {"$in": ["assigned", "in_progress"]}},
        {"lat": 1, "lng": 1, "assigned_volunteers": 1, "title": 1}
    ))

    lines = []
    for task in active_tasks:
        for vol_id in task.get("assigned_volunteers", []):
            vol = db.volunteers.find_one(
                {"_id": to_oid(vol_id)},
                {"lat": 1, "lng": 1, "name": 1}
            )
            if not vol:
                continue
            lines.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [vol["lng"], vol["lat"]],
                        [task["lng"], task["lat"]],
                    ]
                },
                "properties": {
                    "volunteer_id":   str(vol["_id"]),
                    "volunteer_name": vol.get("name", ""),
                    "task_id":        str(task["_id"]),
                    "task_title":     task.get("title", ""),
                }
            })

    return jsonify({"type": "FeatureCollection", "features": lines}), 200


# ── Geo Clusters ─────────────────────────────────────────────────────────────

@map_bp.route("/clusters", methods=["GET"])
@any_authenticated
def geo_clusters():
    db        = current_app.db
    precision = int(request.args.get("precision", 2))
    status    = request.args.get("status", "open")

    pipeline = [
        {"$match": {"status": status}},
        {"$project": {
            "urgency":    1,
            "lat_bucket": {"$round": ["$lat", precision]},
            "lng_bucket": {"$round": ["$lng", precision]},
        }},
        {"$group": {
            "_id": {"lat": "$lat_bucket", "lng": "$lng_bucket"},
            "count":        {"$sum": 1},
            "urgent_count": {"$sum": {"$cond": [{"$eq": ["$urgency", "urgent"]}, 1, 0]}},
            "med_count":    {"$sum": {"$cond": [{"$eq": ["$urgency", "med"]},    1, 0]}},
            "low_count":    {"$sum": {"$cond": [{"$eq": ["$urgency", "low"]},    1, 0]}},
        }},
        {"$project": {
            "lat":          "$_id.lat",
            "lng":          "$_id.lng",
            "count":        1,
            "urgent_count": 1,
            "med_count":    1,
            "low_count":    1,
        }}
    ]

    clusters = list(db.tasks.aggregate(pipeline))
    for c in clusters:
        c.pop("_id", None)

    return jsonify({"clusters": clusters, "precision": precision}), 200


# ── NGO Locations ─────────────────────────────────────────────────────────────

@map_bp.route("/ngos", methods=["GET"])
@any_authenticated
def ngo_locations():
    db   = current_app.db
    ngos = list(db.ngos.find(
        {"status": "active"},
        {"name": 1, "lat": 1, "lng": 1, "focus_areas": 1}
    ))
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [n["lng"], n["lat"]]},
            "properties": {
                "id":          str(n["_id"]),
                "name":        n.get("name", ""),
                "focus_areas": n.get("focus_areas", []),
            }
        }
        for n in ngos
    ]
    return jsonify({"type": "FeatureCollection", "features": features}), 200
