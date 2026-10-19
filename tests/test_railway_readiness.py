"""Railway contracts: no remote services, only isolated protocol fixtures."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch, MagicMock

from flask import Flask
from aeris_web.config import configure
import railway_start

ROOT = Path(__file__).resolve().parents[1]


class RailwayReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mount = Path(self.temp.name)
        (self.mount / 'release-1').mkdir()
        self.db = self.mount / 'release-1' / 'aeris.db'
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute('CREATE TABLE mediciones(fuente TEXT,sensor_id INTEGER,fecha_utc TEXT,contaminante TEXT,valor REAL,unidad TEXT)')
            con.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2021-01-01T00:00:00Z','pm25',0,'µg/m³')")
        self.digest = hashlib.sha256(self.db.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def env(self):
        return dict(AERIS_ENV='beta', AERIS_DB_PATH=str(self.db),
                    AERIS_DEPLOYMENT_PROFILE='railway', AERIS_SNAPSHOT_SHA256=self.digest,
                    AERIS_SNAPSHOT_CREATED_UTC='2026-01-01T00:00:00Z',
                    AERIS_TRUSTED_HOSTS='localhost,healthcheck.railway.app')

    def test_dynamic_port_and_invalid_port(self):
        spec = importlib.util.spec_from_file_location('railway_gunicorn', ROOT / 'gunicorn.conf.py')
        with patch.dict(os.environ, {'PORT': '12345'}):
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)
            self.assertEqual(config.bind, '0.0.0.0:12345')
            self.assertEqual(config.workers, 1)
        with patch.dict(os.environ, {'PORT': '0'}), self.assertRaises(ValueError):
            spec.loader.exec_module(config)

    def test_snapshot_verification_read_only(self):
        self.assertEqual(railway_start.verify(self.db, self.digest), self.digest)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), self.digest)
        with self.assertRaises(ValueError):
            railway_start.verify(self.db, '0' * 64)

    def test_snapshot_identity_and_sidecars(self):
        self.assertEqual(railway_start.snapshot_path(str(self.db), self.mount), self.db)
        with self.assertRaises(ValueError):
            railway_start.snapshot_path(str(self.mount / 'aeris.db'), self.mount)
        Path(str(self.db) + '-wal').touch()
        with self.assertRaises(ValueError):
            railway_start.verify(self.db, self.digest)

    def test_reject_unexpected_source(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE mediciones SET fuente='synthetic-test-fixture'")
        with self.assertRaises(ValueError):
            railway_start.verify(self.db, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_reject_foreign_key_violation(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
            con.execute('CREATE TABLE child(id INTEGER REFERENCES parent(id))')
            con.execute('INSERT INTO child VALUES (9)')
        with self.assertRaises(ValueError):
            railway_start.verify(self.db, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_railway_metadata_required(self):
        for updates in ({'AERIS_SNAPSHOT_SHA256': ''}, {'AERIS_SNAPSHOT_CREATED_UTC': ''},
                        {'AERIS_SNAPSHOT_SHA256': '0' * 64},
                        {'AERIS_SNAPSHOT_CREATED_UTC': '2026-01-01'},
                        {'AERIS_TRUSTED_HOSTS': 'localhost'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                configure(Flask('bad'), ROOT, self.env() | updates)

    def test_healthcheck_host_and_snapshot_notice(self):
        web = Flask('test', template_folder=str(ROOT / 'templates'))
        configure(web, ROOT, self.env())
        web.extensions['aeris_v2_database'] = lambda: self.db
        from flask import render_template
        @web.get('/')
        def index():
            return render_template('v2/snapshot_notice.html')
        client = web.test_client()
        self.assertEqual(client.get('/health/ready', headers={'Host': 'healthcheck.railway.app'}).status_code, 200)
        text = client.get('/').get_data(as_text=True)
        self.assertIn('No se actualiza en vivo', text)
        self.assertIn('2026-01-01', text)
        self.assertNotIn(str(self.mount), text)

    def test_permission_sequence_contract_only(self):
        # Mocked POSIX calls prove order/arguments, NOT actual Windows/Linux DAC.
        libc = MagicMock()
        libc.prctl.return_value = 0
        with patch.object(railway_start.sys, 'platform', 'linux'), \
             patch.object(os, 'geteuid', side_effect=[0, 10001], create=True), \
             patch.object(os, 'chown', create=True) as chown, \
             patch.object(os, 'chmod') as chmod, \
             patch.object(os, 'setgroups', create=True) as groups, \
             patch.object(os, 'setgid', create=True) as gid, \
             patch.object(os, 'setuid', create=True) as uid, \
             patch.object(os, 'access', return_value=False), \
             patch.object(railway_start.ctypes, 'CDLL', return_value=libc):
            railway_start.restrict_and_drop(self.db, self.mount)
            self.assertEqual(chown.call_count, 3)
            chmod.assert_any_call(self.db, 0o444)
            chmod.assert_any_call(self.db.parent, 0o555)
            groups.assert_called_once_with([])
            gid.assert_called_once_with(10001)
            uid.assert_called_once_with(10001)

    def test_config_has_no_writer_or_predeploy(self):
        config = json.loads((ROOT / 'railway.json').read_text())
        self.assertEqual(config['build']['builder'], 'DOCKERFILE')
        self.assertEqual(config['deploy']['healthcheckPath'], '/health/ready')
        self.assertEqual(config['deploy']['startCommand'], 'python railway_start.py')
        self.assertEqual(config['deploy']['restartPolicyType'], 'NEVER')
        self.assertNotIn('preDeployCommand', config['deploy'])
        self.assertNotIn('cronSchedule', config['deploy'])

    def test_dependency_lock_matches_pins(self):
        def requirements(path):
            return {x.split(' --hash=')[0].lower() for x in path.read_text().splitlines() if x and not x.startswith('#')}
        self.assertEqual(requirements(ROOT / 'requirements-web.txt'), requirements(ROOT / 'requirements-web-linux.lock'))
        self.assertIn('--require-hashes', (ROOT / 'Dockerfile').read_text())
