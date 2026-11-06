from pathlib import Path
import sqlite3
import zipfile

import pytest
from planner.import_gtfs import import_feed
from examples.make_demo_feed import generate


def test_rejects_incomplete_archive(tmp_path):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('stops.txt', 'stop_id,stop_name,stop_lat,stop_lon\n')
    with pytest.raises(ValueError, match='routes.txt'):
        import_feed(path, tmp_path / 'bus.sqlite')
    assert not (tmp_path / 'bus.sqlite').exists()


def test_reimport_replaces_data_safely(tmp_path):
    archive = generate(tmp_path/'sample.zip')
    db = tmp_path/'bus.sqlite'
    import_feed(archive, db)
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM stops').fetchone()[0] == 5
        assert con.execute('SELECT COUNT(*) FROM connections').fetchone()[0] == 4
    import_feed(archive, db)
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM connections').fetchone()[0] == 4
