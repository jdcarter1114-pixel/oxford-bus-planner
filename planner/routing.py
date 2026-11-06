"""Earliest-arrival bus journey planner using a timetable connection scan.

No external routing API calculates the journeys. All transport is scheduled GTFS.
Walking time is a conservative straight-line estimate (not footpath directions).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
import sqlite3
from zoneinfo import ZoneInfo

from .geometry import distance_metres, walking_minutes

ZONE = ZoneInfo("Europe/London")
MAX_HORIZON_SECONDS = 5 * 3600
TRANSFER_SECONDS = 90
MAX_ACCESS_METRES = 1200
TRANSFER_WALK_METRES = 200
WALK_ONLY_MAX_METRES = 3000


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Connection:
    trip_key: str  # includes service date so overnight records stay distinct
    trip_id: str
    from_id: str
    to_id: str
    depart: int
    arrive: int
    route: str
    headsign: str


@dataclass(frozen=True)
class State:
    stop_id: str
    arrive: int
    ready: int
    previous: "State | None"
    kind: str  # walk or bus
    depart: int
    from_id: str
    trip_key: str = ""
    route: str = ""
    headsign: str = ""


def active_services(db: sqlite3.Connection, day: date) -> set[str]:
    """Evaluate GTFS calendar and calendar_dates on this service day."""
    day_str = day.strftime("%Y%m%d")
    weekday = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[day.weekday()]
    # Column name is selected from a trusted hard-coded list, not from a request.
    rows = db.execute(
        f"SELECT service_id FROM calendar WHERE start_date <= ? AND end_date >= ? AND {weekday} = 1",
        (day_str, day_str),
    )
    selected = {r[0] for r in rows}
    for service_id, change in db.execute(
        "SELECT service_id, exception_type FROM calendar_dates WHERE date = ?", (day_str,)
    ):
        if int(change) == 1:
            selected.add(service_id)
        elif int(change) == 2:
            selected.discard(service_id)
    return selected


def read_stops(db: sqlite3.Connection) -> dict[str, Stop]:
    return {row[0]: Stop(row[0], row[1], float(row[2]), float(row[3]))
            for row in db.execute("SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops")}


def local_stops(stops: dict[str, Stop], lat: float, lon: float, radius: int):
    # Cheap bounding box reduces haversine calls on large feeds.
    latitude_delta = radius / 110_500
    longitude_delta = radius / (111_000 * max(0.1, math.cos(math.radians(lat))))
    found = []
    for stop in stops.values():
        if abs(stop.lat - lat) > latitude_delta or abs(stop.lon - lon) > longitude_delta:
            continue
        d = distance_metres(lat, lon, stop.lat, stop.lon)
        if d <= radius:
            found.append((stop, d))
    return sorted(found, key=lambda x: x[1])


def read_connections(db: sqlite3.Connection, depart: datetime) -> list[Connection]:
    """Read service-eligible scheduled adjacent-stop journeys for a 5-hour window."""
    start_ts = int(depart.timestamp())
    end_ts = start_ts + MAX_HORIZON_SECONDS
    found = []
    # Previous service days are needed for GTFS 24:xx+ overnight departures.
    for offset in (-2, -1, 0, 1):
        service_day = depart.date() + timedelta(days=offset)
        active = sorted(active_services(db, service_day))
        if not active:
            continue
        midnight = datetime.combine(service_day, datetime.min.time(), tzinfo=ZONE)
        base_ts = int(midnight.timestamp())
        lo, hi = max(0, start_ts - base_ts), min(72 * 3600, end_ts - base_ts)
        if lo > hi:
            continue
        for i in range(0, len(active), 400):
            block = active[i:i + 400]
            marks = ",".join("?" for _ in block)
            sql = f"""
                SELECT c.trip_id,c.from_stop,c.to_stop,c.departure_sec,c.arrival_sec,
                       COALESCE(r.route_short_name,''),COALESCE(t.trip_headsign,'')
                FROM connections c
                JOIN trips t ON t.trip_id=c.trip_id
                JOIN routes r ON r.route_id=t.route_id
                WHERE t.service_id IN ({marks}) AND c.departure_sec BETWEEN ? AND ?
            """
            for trip_id, source, target, start_sec, arrival_sec, route, headsign in db.execute(
                sql, (*block, lo, hi)
            ):
                dep_time = base_ts + int(start_sec)
                arr_time = base_ts + int(arrival_sec)
                if start_ts <= dep_time <= end_ts and arr_time >= dep_time and arr_time <= end_ts + 3600:
                    found.append(Connection(f"{service_day.isoformat()}:{trip_id}", trip_id,
                                            source, target, dep_time, arr_time, route, headsign))
    found.sort(key=lambda item: (item.depart, item.arrive))
    return found


def time_label(value: int) -> str:
    return datetime.fromtimestamp(value, ZONE).strftime("%H:%M")


def footpath_neighbours(stops: dict[str, Stop], radius: int = TRANSFER_WALK_METRES):
    """Walking links between very close stops; no recursive city-wide walking search."""
    cell = 0.0025
    bins = defaultdict(list)
    for stop in stops.values():
        bins[(int(stop.lat / cell), int(stop.lon / cell))].append(stop)
    neighbours = defaultdict(list)
    for stop in stops.values():
        x, y = int(stop.lat / cell), int(stop.lon / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in bins.get((x + dx, y + dy), []):
                    if other.id == stop.id:
                        continue
                    d = distance_metres(stop.lat, stop.lon, other.lat, other.lon)
                    if d <= radius:
                        neighbours[stop.id].append((other.id, max(60, walking_minutes(d) * 60)))
    return neighbours


def make_walk(from_name: str, to_name: str, depart: int, arrive: int,
              start_point: dict, end_point: dict) -> dict:
    return {"mode": "walk", "from": from_name, "to": to_name,
            "departure": time_label(depart), "arrival": time_label(arrive),
            "minutes": max(0, math.ceil((arrive - depart) / 60)),
            "_depart_ts": depart, "_arrive_ts": arrive,
            "geometry": [start_point, end_point]}


def encode_result(state: State | None, end_ts: int, depart_ts: int, stops: dict[str, Stop],
                  origin: dict, destination: dict, dest_walk_seconds: int, direct: bool = False) -> dict:
    if direct:
        legs = [make_walk("Start", "Destination", depart_ts, end_ts, origin, destination)]
    else:
        chain = []
        while state is not None:
            chain.append(state)
            state = state.previous
        chain.reverse()
        legs = []
        for item in chain:
            start = origin if item.from_id == "@origin" else {
                "lat": stops[item.from_id].lat, "lon": stops[item.from_id].lon}
            stop = stops[item.stop_id]
            end = {"lat": stop.lat, "lon": stop.lon}
            from_name = "Start" if item.from_id == "@origin" else stops[item.from_id].name
            if item.kind == "walk":
                step = make_walk(from_name, stop.name, item.depart, item.arrive, start, end)
            else:
                step = {"mode": "bus", "from": from_name, "to": stop.name,
                        "departure": time_label(item.depart), "arrival": time_label(item.arrive),
                        "minutes": max(0, math.ceil((item.arrive - item.depart) / 60)),
                        "route": item.route or "Bus", "headsign": item.headsign,
                        "trip_key": item.trip_key, "_depart_ts": item.depart,
                        "_arrive_ts": item.arrive, "geometry": [start, end]}
            if (step["mode"] == "bus" and legs and legs[-1]["mode"] == "bus"
                    and legs[-1]["trip_key"] == step["trip_key"]):
                legs[-1]["to"] = step["to"]
                legs[-1]["arrival"] = step["arrival"]
                legs[-1]["minutes"] = max(0, math.ceil((item.arrive - legs[-1]["_start_ts"]) / 60))
                legs[-1]["geometry"].append(end)
                legs[-1]["_arrive_ts"] = item.arrive
            else:
                if step["mode"] == "bus":
                    step["_start_ts"] = item.depart
                legs.append(step)
        if dest_walk_seconds > 0 and chain:
            last = chain[-1]
            stop = stops[last.stop_id]
            legs.append(make_walk(stop.name, "Destination", last.arrive,
                                  last.arrive + dest_walk_seconds,
                                  {"lat": stop.lat, "lon": stop.lon}, destination))
    # Waiting is part of the door-to-door journey even when it is not a vehicle leg.
    enriched = []
    previous_time = depart_ts
    for step in legs:
        if step["_depart_ts"] > previous_time:
            wait_sec = step["_depart_ts"] - previous_time
            enriched.append({"mode": "wait", "from": step["from"], "to": step["from"],
                             "departure": time_label(previous_time),
                             "arrival": time_label(step["_depart_ts"]),
                             "minutes": math.ceil(wait_sec / 60), "geometry": []})
        enriched.append(step)
        previous_time = step["_arrive_ts"]
    legs = enriched
    for step in legs:
        for key in ("_start_ts", "_depart_ts", "_arrive_ts", "trip_key"):
            step.pop(key, None)
    bus_legs = sum(1 for step in legs if step["mode"] == "bus")
    walking = sum(step["minutes"] for step in legs if step["mode"] == "walk")
    departure_time = time_label(depart_ts)
    return {"departure": departure_time, "arrival": time_label(end_ts),
            "duration_minutes": math.ceil((end_ts - depart_ts) / 60),
            "walking_minutes": walking, "buses": bus_legs,
            "transfers": max(0, bus_legs - 1), "steps": legs}


def scan(depart: datetime, origin: dict, destination: dict, stops: dict[str, Stop],
         connections: list[Connection], neighbours: dict, blocked: set[str] | None = None,
         require_bus: bool = False) -> dict | None:
    start = int(depart.timestamp())
    blocked = blocked or set()
    best: dict[str, State] = {}
    on_trip: dict[str, State] = {}
    best_goal: tuple[int, State | None, int] | None = None
    finish_near = {s.id: walking_minutes(d) * 60 for s, d in local_stops(
        stops, destination["lat"], destination["lon"], MAX_ACCESS_METRES)}
    origin_near = local_stops(stops, origin["lat"], origin["lon"], MAX_ACCESS_METRES)

    if not require_bus:
        d = distance_metres(origin["lat"], origin["lon"], destination["lat"], destination["lon"])
        if d <= WALK_ONLY_MAX_METRES:
            best_goal = (start + walking_minutes(d) * 60, None, 0)

    def consider_dest(state: State):
        nonlocal best_goal
        if state.stop_id not in finish_near:
            return
        walk = finish_near[state.stop_id]
        finish_at = state.arrive + walk
        if best_goal is None or finish_at < best_goal[0]:
            best_goal = (finish_at, state, walk)

    def update(state: State):
        previous = best.get(state.stop_id)
        if previous is not None and (previous.ready, previous.arrive) <= (state.ready, state.arrive):
            consider_dest(state)
            return False
        best[state.stop_id] = state
        consider_dest(state)
        return True

    for stop, distance in origin_near:
        arrival = start + walking_minutes(distance) * 60
        update(State(stop.id, arrival, arrival, None, "walk", start, "@origin"))

    # At boarding points we allow a short single walking change to nearby stops.
    # This is triggered on arrival from a bus, not recursively from another walk.
    for c in connections:
        if c.trip_key in blocked:
            continue
        prior_on_trip = on_trip.get(c.trip_key)
        continuing = (prior_on_trip is not None and prior_on_trip.stop_id == c.from_id
                      and prior_on_trip.arrive <= c.depart)
        boarding = best.get(c.from_id)
        if continuing:
            prior = prior_on_trip
        elif boarding is not None and boarding.ready <= c.depart:
            prior = boarding
        else:
            continue
        item = State(c.to_id, c.arrive, c.arrive + TRANSFER_SECONDS,
                     prior, "bus", c.depart, c.from_id, c.trip_key,
                     c.route, c.headsign)
        on_trip[c.trip_key] = item
        changed = update(item)
        if changed:
            for other_id, walk_sec in neighbours.get(c.to_id, []):
                other_arrival = c.arrive + walk_sec
                foot = State(other_id, other_arrival,
                             max(other_arrival, c.arrive + TRANSFER_SECONDS),
                             item, "walk", c.arrive, c.to_id)
                update(foot)

    if best_goal is None:
        return None
    arrival, last, last_walk = best_goal
    return encode_result(last, arrival, start, stops, origin, destination,
                         last_walk, direct=last is None)


def plan(db: sqlite3.Connection, depart: datetime, origin: dict, destination: dict) -> dict:
    """Return fastest scheduled route plus meaningful alternatives."""
    stops = read_stops(db)
    if not stops:
        return {"routes": [], "note": "There are no stops in the imported feed."}
    neighbours = footpath_neighbours(stops)
    connections = read_connections(db, depart)
    first = scan(depart, origin, destination, stops, connections, neighbours)
    routes = []
    if first:
        routes.append(first)
    primary_bus = scan(depart, origin, destination, stops, connections,
                       neighbours, require_bus=True)
    if primary_bus and signature(primary_bus) not in {signature(x) for x in routes}:
        routes.append(primary_bus)
    # Avoid the first boarding service to find another practical choice, if one exists.
    if primary_bus:
        # The API omits internal trip IDs, so find the boarding trip in an internal scan.
        # A departure-and-route match identifies a single candidate in most GTFS feeds.
        first_bus_step = next((s for s in primary_bus["steps"] if s["mode"] == "bus"), None)
        if first_bus_step:
            banned = {c.trip_key for c in connections
                      if c.route == first_bus_step["route"]
                      and time_label(c.depart) == first_bus_step["departure"]
                      and stops.get(c.from_id) is not None
                      and stops[c.from_id].name == first_bus_step["from"]}
            if banned:
                alternative = scan(depart, origin, destination, stops, connections,
                                   neighbours, blocked=banned, require_bus=True)
                if alternative and signature(alternative) not in {signature(x) for x in routes}:
                    routes.append(alternative)
    routes.sort(key=lambda r: (r["duration_minutes"], r["transfers"], r["walking_minutes"]))
    return {"routes": routes[:3], "scheduled": True, "connections_examined": len(connections),
            "note": "Scheduled services only; no live delays. Walking and map paths are estimates, not turn-by-turn directions."}


def signature(route: dict) -> tuple:
    return tuple((s["mode"], s["from"], s["to"], s.get("route"), s["departure"])
               for s in route["steps"])
