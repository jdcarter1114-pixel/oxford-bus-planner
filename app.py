"""Oxford Bus Planner: Flask HTTP API and interactive website."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, render_template, request

from planner.geometry import distance_metres, oxford_area, valid_latlon, walking_minutes
from planner.import_gtfs import DEFAULT_DB
from planner.routing import local_stops, plan, read_stops

ZONE = ZoneInfo("Europe/London")
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_USER_AGENT = os.environ.get(
    "GEOCODER_USER_AGENT", "OxfordBusPlanner/1.0 (personal educational local project)"
)
_lock = threading.Lock()
_last_request_time = 0.0


def create_app(database: str | Path | None = None):
    app = Flask(__name__)
    app.config["DATABASE"] = str(database or os.environ.get("OXFORD_BUS_DB", DEFAULT_DB))
    app.json.sort_keys = False

    def connect():
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        return db

    def ready():
        path = Path(app.config["DATABASE"])
        if not path.exists():
            return False
        try:
            with connect() as db:
                return bool(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='connections'"
                ).fetchone())
        except sqlite3.Error:
            return False

    def coords(prefix: str):
        try:
            lat = float(request.args[f"{prefix}_lat"])
            lon = float(request.args[f"{prefix}_lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Provide valid {prefix} latitude and longitude.")
        if not valid_latlon(lat, lon) or not oxford_area(lat, lon):
            raise ValueError(f"{prefix.title()} point must be in the Oxford area.")
        return {"lat": lat, "lon": lon}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        if not ready():
            return jsonify(status="setup_required", message="Import GTFS data; see README.md"), 503
        with connect() as db:
            count = db.execute("SELECT COUNT(*) FROM stops").fetchone()[0]
            imported = db.execute("SELECT value FROM metadata WHERE key='imported_utc'").fetchone()
            source = db.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
        return jsonify(status="ready", stops=count, imported_utc=imported[0] if imported else None,
                       source=source[0] if source else None)

    @app.get("/api/stops")
    def stops():
        if not ready():
            return jsonify(error="Import Oxford bus timetable data first. See README.md."), 503
        try:
            p = coords("point")
            limit = max(1, min(30, int(request.args.get("limit", 12))))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        with connect() as db:
            found = local_stops(read_stops(db), p["lat"], p["lon"], 1500)[:limit]
        return jsonify(stops=[{"id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon,
                               "distance_metres": round(d), "estimated_walk_minutes": walking_minutes(d)}
                              for s, d in found])

    @app.get("/api/geocode")
    def geocode():
        """Explicit searches only, cached and globally throttled for one local process.

        No autocomplete. Nominatim public service is suitable only for small demos;
        see usage policy in README. Configurable contact-identifying user agent.
        """
        global _last_request_time
        query = request.args.get("q", "").strip()
        if not 3 <= len(query) <= 160:
            return jsonify(error="Enter an Oxford address or landmark (3–160 characters)."), 400
        if not ready():
            return jsonify(error="Import a GTFS timetable before searching for addresses."), 503
        with _lock:
            with connect() as db:
                cached = db.execute(
                    "SELECT latitude,longitude,label FROM geocode_cache WHERE query=?",
                    (query.casefold(),)
                ).fetchone()
                if cached:
                    return jsonify(lat=cached[0], lon=cached[1], label=cached[2])
            wait = max(0, 1.1 - (time.monotonic() - _last_request_time))
            if wait:
                time.sleep(wait)
            _last_request_time = time.monotonic()
            try:
                response = requests.get(GEOCODE_URL,
                                        params={"q": query, "format": "jsonv2", "limit": 5,
                                                "viewbox": "-1.59,51.97,-0.94,51.58", "bounded": 1,
                                                "countrycodes": "gb"},
                                        headers={"User-Agent": GEOCODER_USER_AGENT}, timeout=12)
                response.raise_for_status()
                choices = response.json()
            except (requests.RequestException, ValueError):
                return jsonify(error="Address search is unavailable. Try selecting a point on the map."), 502
            choice = next((p for p in choices
                           if oxford_area(float(p["lat"]), float(p["lon"]))), None)
            if choice is None:
                return jsonify(error="No Oxford-area match. Try a postcode or pick a point on the map."), 404
            result = {"lat": float(choice["lat"]), "lon": float(choice["lon"]),
                      "label": str(choice["display_name"])}
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO geocode_cache VALUES(?,?,?,?)",
                           (query.casefold(), result["lat"], result["lon"], result["label"]))
            return jsonify(result)

    @app.get("/api/routes")
    def routes():
        if not ready():
            return jsonify(error="Timetable database missing. Run the GTFS importer first."), 503
        try:
            start = coords("start")
            end = coords("end")
            value = request.args.get("depart", "").strip()
            if not value:
                # Input is a London local clock time, not the server timezone.
                departure = datetime.now(ZONE)
            else:
                parsed = datetime.fromisoformat(value)
                departure = parsed.replace(tzinfo=ZONE) if parsed.tzinfo is None else parsed.astimezone(ZONE)
            if abs((departure - datetime.now(ZONE)).days) > 31:
                raise ValueError("Choose a departure within 31 days of today.")
        except (ValueError, OverflowError) as e:
            return jsonify(error=str(e) or "Invalid date/time."), 400
        try:
            with connect() as db:
                result = plan(db, departure, start, end)
        except sqlite3.Error:
            app.logger.exception("Database routing failed")
            return jsonify(error="Could not query timetable data. Please re-import the GTFS feed."), 500
        return jsonify(departure_query=departure.strftime("%Y-%m-%dT%H:%M"), **result)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
