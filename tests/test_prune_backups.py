import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from data_ingestion.retention import plan
from scripts.prune_backups import main

NOW = datetime(2026, 10, 20, 12, 0)


def make(folder, name, when):
    path = Path(folder) / name
    path.write_bytes(b'x')
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


class PruneBackupsTests(unittest.TestCase):
    def test_keeps_recent_daily_and_milestones(self):
        with tempfile.TemporaryDirectory() as folder:
            hourly = [make(folder, f'aeris_before_sync_{i:02d}.db', NOW - timedelta(hours=i)) for i in range(30)]
            old = make(folder, 'aeris_before_sync_old.db', NOW - timedelta(days=20))
            milestone = make(folder, 'aeris_before_first_scheduler_x.db', NOW - timedelta(days=30))
            kept, removed = plan(folder, keep_recent=5, keep_days=14, now=NOW)
            self.assertEqual(set(hourly[:5]) | {hourly[13]}, set(kept))
            self.assertIn(old, removed)
            self.assertNotIn(milestone, kept + removed)

    def test_protected_backup_is_never_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make(folder, 'aeris_before_sync_old.db', NOW - timedelta(days=20))
            kept, removed = plan(folder, keep_recent=1, now=NOW, protect=[old])
            self.assertEqual([old], kept)
            self.assertEqual([], removed)

    def test_dry_run_deletes_nothing_and_apply_deletes(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(8):
                make(folder, f'aeris_before_sync_{i}.db', datetime.now() - timedelta(minutes=i))
            main(['--folder', folder, '--keep-recent', '2'])
            self.assertEqual(8, len(list(Path(folder).iterdir())))
            main(['--folder', folder, '--keep-recent', '2', '--apply'])
            self.assertLessEqual(len(list(Path(folder).iterdir())), 3)
