"""Regressions for the missing-main incident; no production or network access."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import app
import wsgi
import railway_start
from scripts.prepare_railway_release import release_files, inspect

ROOT = Path(__file__).resolve().parents[1]


class RailwayEntryRegressionTests(unittest.TestCase):
    def test_wsgi_alias_is_actual_flask_object(self):
        self.assertIs(wsgi.application, app.app)
        self.assertTrue(callable(wsgi.application))
        self.assertFalse(wsgi.application.debug)

    def test_clean_release_imports_without_workspace_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # An exact release manifest, excluding docs/tests/tools not needed by image.
            for name in release_files():
                path = ROOT / name
                if not path.is_file():
                    continue
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            env = {key: value for key, value in os.environ.items()
                   if key in ('SYSTEMROOT', 'SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP')}
            env['AERIS_ENV'] = 'local'
            code = "import wsgi,app,sys; assert wsgi.application is app.app; assert 'data_ingestion.operations' not in sys.modules; assert 'data_ingestion.scheduled_sync' not in sys.modules; assert 'sklearn' not in sys.modules"
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_snapshot_stops_before_gunicorn(self):
        with patch.dict(os.environ, {'AERIS_ENV': 'beta', 'AERIS_DB_PATH': '/dataset/missing/aeris.db',
                                    'OPENAQ_API_KEY': ''}), patch.object(railway_start.os, 'execvp') as execute:
            with self.assertRaises(ValueError):
                railway_start.main()
            execute.assert_not_called()

    def test_invalid_snapshot_never_drops_or_starts(self):
        with patch.dict(os.environ, {'AERIS_ENV': 'beta', 'OPENAQ_API_KEY': ''}), \
             patch.object(railway_start, 'snapshot_path', return_value=Path('/dataset/cut/aeris.db')), \
             patch.object(railway_start, 'verify', side_effect=ValueError('fixture invalid')), \
             patch.object(railway_start, 'restrict_and_drop') as drop, \
             patch.object(railway_start.os, 'execvp') as execute:
            with self.assertRaises(ValueError):
                railway_start.main()
            drop.assert_not_called()
            execute.assert_not_called()

    def test_launcher_uses_wsgi_after_verification(self):
        manager = Mock()
        with patch.dict(os.environ, {'AERIS_ENV': 'beta', 'OPENAQ_API_KEY': ''}), \
             patch.object(railway_start, 'snapshot_path', return_value=Path('/dataset/cut/aeris.db')), \
             patch.object(railway_start, 'verify', manager.verify), \
             patch.object(railway_start, 'restrict_and_drop', manager.drop), \
             patch.object(railway_start.os, 'execvp', manager.execute):
            railway_start.main()
        self.assertEqual([c[0] for c in manager.mock_calls], ['verify', 'drop', 'verify', 'execute'])
        self.assertEqual(manager.execute.call_args.args,
                         ('gunicorn', ['gunicorn', '--config', 'gunicorn.conf.py', 'wsgi:application']))
