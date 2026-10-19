"""Deployment contracts, using isolated fixtures, not production writes."""
import hashlib
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import Flask
import app
from aeris_web.config import configure
from data_ingestion.visibility import connect_readonly
from scripts.prepare_web_snapshot import prepare


class WebDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.db'
        with closing(sqlite3.connect(self.source)) as con, con:
            con.execute('CREATE TABLE mediciones(fuente TEXT,sensor_id INTEGER,fecha_utc TEXT,contaminante TEXT,valor REAL,unidad TEXT)')
            con.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2020-01-01T00:00:00Z','pm25',0,'µg/m³')")
            con.execute('CREATE TABLE archivos_origen(sha256 TEXT,url TEXT,ruta_local TEXT)')
            con.execute("INSERT INTO archivos_origen VALUES ('hash','https://example.org/data?api_key=fixture','C:/private/fixture')")
            con.execute('CREATE TABLE ingestas(id TEXT,reporte_json TEXT)')
            con.execute('INSERT INTO ingestas VALUES (?,?)', ('fixture', '{"path":"private"}'))

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        return dict(AERIS_ENV='beta', AERIS_DB_PATH=str(self.source), AERIS_TRUSTED_HOSTS='localhost')

    def configured(self):
        web = Flask('isolated')
        configure(web, self.root, self.env())
        web.extensions['aeris_v2_database'] = lambda: self.source
        return web

    def test_beta_requires_snapshot(self):
        for updates in ({'AERIS_DB_PATH': ''}, {'AERIS_DB_PATH': 'relative.db'},
                        {'AERIS_TRUSTED_HOSTS': '*'}, {'OPENAQ_API_KEY': 'fixture'},
                        {'AERIS_PROXY_HOPS': '2'}, {'AERIS_LOG_LEVEL': 'DEBUG'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                configure(Flask('invalid'), self.root, self.env() | updates)

    def test_local_defaults_preserved(self):
        self.assertEqual(configure(Flask('local'), self.root, {}), self.root / 'data' / 'aeris_air_quality.db')

    def test_health_old_data_is_ready(self):
        client = self.configured().test_client()
        self.assertEqual(client.get('/health/live').status_code, 200)
        self.assertEqual(client.get('/health/ready').status_code, 200)
        self.source.unlink()
        self.assertEqual(client.get('/health/ready').status_code, 503)
        self.assertEqual(client.get('/health/live').status_code, 200)

    def test_host_errors_and_headers(self):
        web = self.configured()
        @web.get('/failure')
        def fail():
            raise RuntimeError('secret /private/path')
        client = web.test_client()
        self.assertEqual(client.get('/', headers={'Host': 'evil.example'}).status_code, 400)
        response = client.get('/failure')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b'private', response.data)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_read_only_and_restart_persistence(self):
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for _ in range(2):
            with closing(connect_readonly(self.source)) as con:
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute('DELETE FROM mediciones')
            self.assertEqual(self.configured().test_client().get('/health/ready').status_code, 200)
        self.assertEqual(digest, hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_sanitized_backup_retains_science(self):
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        output = self.root / 'snapshot'
        result = prepare(self.source, output)
        self.assertEqual(digest, hashlib.sha256(self.source.read_bytes()).hexdigest())
        with closing(sqlite3.connect(output / 'aeris.db')) as con:
            self.assertEqual(con.execute('SELECT valor FROM mediciones').fetchone(), (0,))
            row = con.execute('SELECT url,ruta_local FROM archivos_origen').fetchone()
            self.assertTrue(row[0].startswith('https://example.org/data#withheld-'))
            self.assertNotIn('api_key', row[0])
            self.assertEqual(row[1], '[withheld]')
        self.assertEqual(result['rows']['mediciones'], 1)
        with self.assertRaises(FileExistsError):
            prepare(self.source, output)

    def test_http_file_boundaries(self):
        client = app.app.test_client()
        for route in ('/data/aeris_air_quality.db', '/.secrets/openaq_api_key.clixml',
                      '/.env', '/static/../data/aeris_air_quality.db'):
            self.assertEqual(client.get(route).status_code, 404)

    def test_redaction_preserves_distinct_response_keys(self):
        with closing(sqlite3.connect(self.source)) as con, con:
            con.execute('CREATE UNIQUE INDEX response_key ON archivos_origen(sha256,url)')
            con.execute("INSERT INTO archivos_origen VALUES ('hash','https://example.org/data?page=2','private')")
        prepare(self.source, self.root / 'distinct')
        with closing(sqlite3.connect(self.root / 'distinct' / 'aeris.db')) as con:
            self.assertEqual(con.execute('SELECT count(DISTINCT url) FROM archivos_origen').fetchone()[0], 2)

    def test_manifest_mismatch_rejected(self):
        output = self.root / 'manifest-test'
        prepare(self.source, output)
        with self.assertRaises(ValueError):
            configure(Flask('manifest'), self.root,
                      self.env() | {'AERIS_DATASET_MANIFEST': str(output / 'manifest.json')})

    def test_entry_has_no_ingestion_imports(self):
        code = 'import wsgi,sys; forbidden=["data_ingestion.operations","data_ingestion.scheduled_sync","data_ingestion.windows_credentials","sklearn"]; assert not any(x in sys.modules for x in forbidden)'
        run = subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, env=os.environ | {'AERIS_ENV': 'local'})
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_gunicorn_resource_limits(self):
        spec = importlib.util.spec_from_file_location('gunicorn_settings', app.ROOT / 'gunicorn.conf.py')
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        self.assertEqual(config.workers, 1)
        self.assertFalse(config.preload_app)
        self.assertGreater(config.timeout, 0)
        self.assertNotIn('%(q)', config.access_log_format)
