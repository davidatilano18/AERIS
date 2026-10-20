import os
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

    def synchronize(self, db, environ, **patches):
        from tests.test_operations import FakeClient, hour
        from datetime import datetime, timezone
        with patch.object(ops, 'ACTIVE', (1352676,)), patch.dict(os.environ, environ, clear=False):
            if scheduled.RETENTION_ENV not in environ:
                os.environ.pop(scheduled.RETENTION_ENV, None)
            return scheduled.run(db, key='fixture', client=FakeClient([hour()]),
                start=datetime(2020,1,1,tzinfo=timezone.utc), end=datetime(2020,1,2,tzinfo=timezone.utc))

    def old_backups(self, db, count=8):
        backups = db.parent / 'backups'; backups.mkdir()
        for i in range(count):
            path = backups / f'test_before_sync_old{i}.db'; path.write_bytes(b'x')
            os.utime(path, (1_600_000_000 + i, 1_600_000_000 + i))
        return backups

    def test_real_core_on_temporary_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db)
            report = self.synchronize(db, {})
            self.assertEqual(report['status'], 'success')
            self.assertTrue(report['backup']['verified'])
            self.assertTrue((db.parent/'sync_runtime/scheduler/last_success.json').exists())

    def test_retention_disabled_by_default_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db); backups = self.old_backups(db)
            before = sorted(p.name for p in backups.iterdir())
            # wraps: if the guard failed, the real prune would run and delete the old files.
            with patch.object(scheduled.retention, 'prune', wraps=scheduled.retention.prune) as prune:
                report = self.synchronize(db, {})
            prune.assert_not_called()
            self.assertEqual(report['status'], 'success')
            self.assertEqual(report['retention'], {'applied': False, 'reason': 'disabled'})
            after = sorted(p.name for p in backups.iterdir())
            self.assertTrue(set(before) <= set(after))  # only this run's backup is added

    def test_retention_requires_exact_apply_value(self):
        for value in ('', '1', 'true', 'yes', 'APPLY', ' apply'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                db = Path(folder) / 'test.db'; self.database(db); self.old_backups(db)
                with patch.object(scheduled.retention, 'prune') as prune:
                    report = self.synchronize(db, {scheduled.RETENTION_ENV: value})
                prune.assert_not_called()
                self.assertEqual(report['retention']['reason'], 'disabled')

    def test_retention_applies_only_with_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db); self.old_backups(db)
            report = self.synchronize(db, {scheduled.RETENTION_ENV: 'apply'})
            self.assertTrue(report['retention']['applied'])
            self.assertIn(Path(report['backup']['path']).name, report['retention']['kept'])

    def test_retention_failure_keeps_success(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.db'; self.database(db)
            with patch.object(scheduled.retention, 'prune', side_effect=OSError):
                report = self.synchronize(db, {scheduled.RETENTION_ENV: 'apply'})
            self.assertEqual(report['status'], 'success')
            self.assertEqual(report['retention'], {'applied': False, 'error_type': 'OSError'})
