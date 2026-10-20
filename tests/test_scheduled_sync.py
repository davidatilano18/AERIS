import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from data_ingestion import operations as ops
from data_ingestion import scheduled_sync as scheduled
from data_ingestion.controlled_run import CriticalFailure
from data_ingestion.production_preflight import sha


class ScheduledTests(unittest.TestCase):
    def database(self, path):
        with closing(sqlite3.connect(path)) as conn, conn:
            ops.ensure_db(conn)
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',10,'µg/m³')")

    def test_guard_rolls_back_changed_original(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db)
            def unsafe(db, sensors, **kwargs):
                ops.copy_database(db, db.parent / 'backup.db')
                with closing(sqlite3.connect(db)) as conn, conn:
                    conn.execute('UPDATE mediciones SET valor=99')
            with patch.object(ops, 'run', unsafe), self.assertRaises(CriticalFailure):
                scheduled.run(db, key='fixture')
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT valor FROM mediciones').fetchone()[0], 10)

    def test_backup_mismatch_stops_before_sync_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db); before = sha(db)
            with patch.object(scheduled, 'snapshot', side_effect=[{'integrity_check':['ok'], 'foreign_key_violations':0}, {}, {'different':True}]), self.assertRaises(CriticalFailure):
                scheduled.run(db, key='fixture')
            self.assertEqual(sha(db), before)

    def test_real_core_on_temporary_copy(self):
        from tests.test_operations import FakeClient, hour
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db)
            with patch.object(ops, 'ACTIVE', (1352676,)):
                report = scheduled.run(db, key='fixture', client=FakeClient([hour()]),
                    start=datetime(2020,1,1,tzinfo=timezone.utc), end=datetime(2020,1,2,tzinfo=timezone.utc))
            self.assertEqual(report['status'], 'success')
            self.assertTrue(report['backup']['verified'])
            self.assertTrue((db.parent/'sync_runtime/scheduler/last_success.json').exists())
