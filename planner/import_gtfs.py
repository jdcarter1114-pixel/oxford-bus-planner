"""Import GTFS schedules into SQLite (standard-library CSV + ZIP).

Usage:
    python -m planner.import_gtfs data/oxford-gtfs.zip
    python -m planner.import_gtfs --download

The imported database is replaced only after the whole import succeeds.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import requests

from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "oxford_buses.sqlite"
SOURCE_URL = "https://www.oxfordbus.co.uk/open-data/network/current?format=gtfs"

SCHEMA = """
CREATE TABLE stops (stop_id TEXT PRIMARY KEY, stop_name TEXT NOT NULL,
                    stop_lat REAL NOT NULL, stop_lon REAL NOT NULL);
CREATE TABLE routes (route_id TEXT PRIMARY KEY, route_short_name TEXT,
                     route_long_name TEXT, route_color TEXT);
CREATE TABLE trips (trip_id TEXT PRIMARY KEY, route_id TEXT NOT NULL,
                    service_id TEXT NOT NULL, trip_headsign TEXT,
                    direction_id TEXT);
CREATE TABLE stop_times (trip_id TEXT NOT NULL, stop_sequence INTEGER NOT NULL,
                         stop_id TEXT NOT NULL, arrival_sec INTEGER,
                         departure_sec INTEGER, PRIMARY KEY(trip_id,stop_sequence));
CREATE TABLE connections (trip_id TEXT NOT NULL, from_stop TEXT NOT NULL, to_stop TEXT NOT NULL,
                          departure_sec INTEGER NOT NULL, arrival_sec INTEGER NOT NULL);
CREATE TABLE calendar (service_id TEXT PRIMARY KEY,
 monday INTEGER, tuesday INTEGER, wednesday INTEGER, thursday INTEGER,
 friday INTEGER, saturday INTEGER, sunday INTEGER,
 start_date TEXT, end_date TEXT);
CREATE TABLE calendar_dates (service_id TEXT NOT NULL, date TEXT NOT NULL,
 exception_type INTEGER NOT NULL, PRIMARY KEY(service_id,date));
CREATE TABLE geocode_cache (query TEXT PRIMARY KEY, latitude REAL, longitude REAL,
 label TEXT NOT NULL);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_stops_coords ON stops(stop_lat,stop_lon);
CREATE INDEX idx_times_trip ON stop_times(trip_id,stop_sequence);
CREATE INDEX idx_times_stop ON stop_times(stop_id);
CREATE INDEX idx_connections_departure ON connections(departure_sec);
CREATE INDEX idx_connections_trip ON connections(trip_id);
CREATE INDEX idx_trips_service ON trips(service_id);
"""


def time_seconds(value: str) -> int | None:
    """GTFS supports hours >= 24 for overnight trips."""
    if not value:
        return None
    try:
        h, m, s = map(int, value.split(":"))
        if not (0 <= h <= 71 and 0 <= m < 60 and 0 <= s < 60):
            return None
        return h * 3600 + m * 60 + s
    except (ValueError, TypeError):
        return None


def rows_from_archive(archive: zipfile.ZipFile, name: str):
    matches = [n for n in archive.namelist() if n.lower().split("/")[-1] == name]
    if not matches:
        return None
    handle = io.TextIOWrapper(archive.open(matches[0]), encoding="utf-8-sig", newline="")
    return csv.DictReader(handle)


def import_feed(zip_path: str | Path, db_path: str | Path = DEFAULT_DB) -> dict:
    zip_path, db_path = Path(zip_path), Path(db_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"GTFS archive not found: {zip_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tempname = tempfile.mkstemp(prefix="gtfs_", suffix=".sqlite", dir=db_path.parent)
    os.close(fd)
    counts = {}
    try:
        with closing(sqlite3.connect(tempname)) as db, zipfile.ZipFile(zip_path) as archive:
            db.executescript(SCHEMA)
            tables = {
                "stops.txt": ("stops", ("stop_id", "stop_name", "stop_lat", "stop_lon")),
                "routes.txt": ("routes", ("route_id", "route_short_name", "route_long_name", "route_color")),
                "trips.txt": ("trips", ("trip_id", "route_id", "service_id", "trip_headsign", "direction_id")),
                "calendar.txt": ("calendar", ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date")),
                "calendar_dates.txt": ("calendar_dates", ("service_id", "date", "exception_type")),
            }
            for filename, (table, fields) in tables.items():
                reader = rows_from_archive(archive, filename)
                if reader is None:
                    if filename in ("calendar.txt", "calendar_dates.txt"):
                        counts[table] = 0
                        continue
                    raise ValueError(f"Missing GTFS file {filename}")
                batch, total = [], 0
                statement = f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' for _ in fields)})"
                for r in reader:
                    if table == "stops":
                        if r.get("location_type", "0") not in ("", "0"):
                            continue
                        try:
                            lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            continue
                    if not r.get(fields[0]):
                        continue
                    batch.append(tuple(r.get(field, "") for field in fields))
                    if len(batch) >= 5000:
                        db.executemany(statement, batch)
                        total += len(batch)
                        batch.clear()
                if batch:
                    db.executemany(statement, batch)
                    total += len(batch)
                counts[table] = total
            reader = rows_from_archive(archive, "stop_times.txt")
            if reader is None:
                raise ValueError("Missing GTFS file stop_times.txt")
            batch, total = [], 0
            for r in reader:
                if not r.get("trip_id") or not r.get("stop_id"):
                    continue
                try:
                    seq = int(r["stop_sequence"])
                except (ValueError, KeyError):
                    continue
                # Timeless intermediate stop_times cannot be safely boarded.
                arrival, departure = time_seconds(r.get("arrival_time", "")), time_seconds(r.get("departure_time", ""))
                if arrival is None and departure is None:
                    continue
                batch.append((r["trip_id"], seq, r["stop_id"],
                              arrival if arrival is not None else departure,
                              departure if departure is not None else arrival))
                if len(batch) >= 10000:
                    db.executemany("INSERT OR REPLACE INTO stop_times VALUES (?,?,?,?,?)", batch)
                    total += len(batch)
                    batch.clear()
            if batch:
                db.executemany("INSERT OR REPLACE INTO stop_times VALUES (?,?,?,?,?)", batch)
                total += len(batch)
            counts["stop_times"] = total
            if counts["stops"] == 0 or counts["trips"] == 0 or total == 0:
                raise ValueError("GTFS feed contains no usable stops, trips or stop times")
            # A GTFS trip is an ordered sequence of stops. Connections are its
            # consecutive, individually timed segments, precomputed for fast routing.
            db.execute("""
                INSERT INTO connections(trip_id,from_stop,to_stop,departure_sec,arrival_sec)
                SELECT trip_id,stop_id,next_stop,departure_sec,next_arrival
                FROM (
                  SELECT trip_id,stop_id,departure_sec,
                         LEAD(stop_id) OVER (PARTITION BY trip_id ORDER BY stop_sequence) AS next_stop,
                         LEAD(arrival_sec) OVER (PARTITION BY trip_id ORDER BY stop_sequence) AS next_arrival
                  FROM stop_times
                )
                WHERE next_stop IS NOT NULL AND next_arrival >= departure_sec
            """)
            counts["connections"] = db.execute("SELECT COUNT(*) FROM connections").fetchone()[0]
            if not counts["connections"]:
                raise ValueError("GTFS has no valid consecutive stop connections")
            db.execute("INSERT INTO metadata VALUES('source', ?)", (zip_path.name,))
            db.execute("INSERT INTO metadata VALUES('imported_utc', strftime('%Y-%m-%dT%H:%M:%SZ','now'))")
            db.execute("INSERT INTO metadata VALUES('source_url', ?)", (SOURCE_URL,))
            db.commit()
        os.replace(tempname, db_path)
        return counts
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)


def download_feed(destination: Path) -> Path:
    """Download published Oxford Bus GTFS, subject to operator availability."""
    headers = {"User-Agent": "OxfordBusPlanner/1.0 (educational personal project)"}
    response = requests.get(SOURCE_URL, headers=headers, timeout=90)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError("The operator did not return a GTFS ZIP; download Current GTFS manually")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def main():
    parser = argparse.ArgumentParser(description="Import Oxford bus schedule GTFS")
    parser.add_argument("zipfile", nargs="?", help="Path to an existing GTFS ZIP")
    parser.add_argument("--download", action="store_true", help="Download the Oxford Bus Company current GTFS ZIP")
    parser.add_argument("--database", default=str(DEFAULT_DB))
    args = parser.parse_args()
    if not args.zipfile and not args.download:
        parser.error("Supply a GTFS ZIP path or --download")
    path = download_feed(ROOT / "data" / "oxford-latest.zip") if args.download else Path(args.zipfile)
    counts = import_feed(path, args.database)
    print("Import complete: " + ", ".join(f"{k}: {v:,}" for k, v in counts.items()))
    print(f"Database: {Path(args.database).resolve()}")


if __name__ == "__main__":
    main()
