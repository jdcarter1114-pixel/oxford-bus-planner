"""Generate a tiny, SYNTHETIC Oxford-shaped GTFS feed for tests and UI demos.

Stops are placed near Oxford landmarks, but all routes/timetables are invented.
Do not use synthetic data for actual passenger journey advice.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]


def sample_tables():
    stops = [
        ("A", "Railway Station", "51.7533", "-1.2694", "0"),
        ("B", "Westgate", "51.7507", "-1.2629", "0"),
        ("C", "High Street", "51.7529", "-1.2530", "0"),
        ("D", "Headington Shops", "51.7598", "-1.2157", "0"),
        ("E", "Cowley Road", "51.7448", "-1.2352", "0"),
    ]
    routes = [("R1", "X1", "Station to High Street", "19875D"),
              ("R2", "X2", "High Street to Headington", "19875D"),
              ("R3", "X3", "Station Express to Headington", "19875D")]
    trips = [("T1","R1","WEEKDAY","High Street","0"),
             ("T2","R2","WEEKDAY","Headington Shops","0"),
             ("T3","R3","WEEKDAY","Headington Shops","0")]
    times = [
        ("T1","09:05:00","09:05:00","A","1"),
        ("T1","09:09:00","09:09:00","B","2"),
        ("T1","09:15:00","09:15:00","C","3"),
        ("T2","09:17:00","09:17:00","C","1"),
        ("T2","09:30:00","09:30:00","D","2"),
        ("T3","09:08:00","09:08:00","A","1"),
        ("T3","09:45:00","09:45:00","D","2"),
    ]
    return {
        "stops.txt": (["stop_id","stop_name","stop_lat","stop_lon","location_type"], stops),
        "routes.txt": (["route_id","route_short_name","route_long_name","route_color"], routes),
        "trips.txt": (["trip_id","route_id","service_id","trip_headsign","direction_id"], trips),
        "stop_times.txt": (["trip_id","arrival_time","departure_time","stop_id","stop_sequence"], times),
        "calendar.txt": (["service_id","monday","tuesday","wednesday","thursday","friday","saturday","sunday","start_date","end_date"],
                         [("WEEKDAY",1,1,1,1,1,0,0,"20260101","20281231")]),
        "calendar_dates.txt": (["service_id","date","exception_type"],
                               [("WEEKDAY","20261107",1),("WEEKDAY","20261106",2)]),
    }


def generate(path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zipfile_out:
        for filename, (columns, data) in sample_tables().items():
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(data)
            zipfile_out.writestr(filename, stream.getvalue())
    return path


if __name__ == "__main__":
    print("SYNTHETIC GTFS:", generate(BASE / "examples" / "demo_oxford_gtfs.zip"))
