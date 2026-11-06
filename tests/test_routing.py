"""Unit + integration-style tests using invented service data."""
from datetime import date, datetime
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import pytest
from examples.make_demo_feed import generate
from planner.geometry import distance_metres, walking_minutes
from planner.import_gtfs import import_feed, time_seconds
from planner.routing import active_services, plan, read_connections

ZONE = ZoneInfo('Europe/London')
A = {'lat': 51.7533, 'lon': -1.2694}
B = {'lat': 51.7507, 'lon': -1.2629}
D = {'lat': 51.7598, 'lon': -1.2157}


@pytest.fixture()
def demo_db(tmp_path: Path):
    archive = generate(tmp_path / 'demo.zip')
    path = tmp_path / 'demo.sqlite'
    counts = import_feed(archive, path)
    assert counts['connections'] == 4  # 2 on X1, 1 on X2, 1 on X3
    return path


def plan_test(path, when, start=A, end=D):
    with sqlite3.connect(path) as db:
        return plan(db, datetime.fromisoformat(when).replace(tzinfo=ZONE), start, end)


def test_import_and_fastest_transfer(demo_db):
    result = plan_test(demo_db, '2026-11-05T09:00')
    assert result['routes']
    quickest = result['routes'][0]
    assert quickest['duration_minutes'] == 30
    assert quickest['arrival'] == '09:30'
    assert [s['route'] for s in quickest['steps'] if s['mode']=='bus'] == ['X1', 'X2']
    assert quickest['transfers'] == 1
    assert any('X3' == s['route'] for r in result['routes'] for s in r['steps'] if s['mode']=='bus')


def test_direct_bus(demo_db):
    result = plan_test(demo_db, '2026-11-05T09:00', A, B)
    assert result['routes'][0]['arrival'] == '09:09'
    assert result['routes'][0]['buses'] == 1


def test_added_and_removed_calendar_exceptions(demo_db):
    with sqlite3.connect(demo_db) as db:
        assert 'WEEKDAY' in active_services(db, date(2026,11,7))
        assert 'WEEKDAY' not in active_services(db, date(2026,11,6))
        assert 'WEEKDAY' not in active_services(db, date(2026,11,14))
    assert plan_test(demo_db, '2026-11-07T09:00')['routes']
    assert not plan_test(demo_db, '2026-11-06T09:00')['routes']


def test_last_bus_missed(demo_db):
    assert not plan_test(demo_db, '2026-11-05T09:50')['routes']


def test_GTFS_overnight_time_parse():
    assert time_seconds('25:10:00') == 25 * 3600 + 600
    assert time_seconds('23:61:00') is None


def test_geometry():
    assert distance_metres(51.75, -1.26, 51.75, -1.26) == 0
    assert walking_minutes(500) > walking_minutes(100)
