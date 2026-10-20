import csv
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import app as dashboard
from data_ingestion.catalog import load_catalog, persist_catalog
from data_ingestion.sync_pm25_queretaro import ensure_db


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'dashboard.db'
        self.stamp = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat().replace('+00:00','Z')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            ensure_db(conn)
            persist_catalog(conn, load_catalog())
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,?,'pm25',10,'µg/m³')", (self.stamp,))
        self.patcher = patch.object(dashboard, 'DB', self.db)
        self.patcher.start()
        self.client = dashboard.app.test_client()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_pending_is_not_clean_and_export_is_explicit(self):
        data = self.client.get('/api/measurements?period=all').get_json()
        self.assertEqual(data['stats']['quality_pending'], 1)
        self.assertIsNone(data['recent_measurements'][0]['requiere_revision'])
        self.assertEqual(self.client.get('/api/measurements?period=all&quality=exclude').get_json()['stats']['count'], 0)
        self.assertEqual(self.client.get('/api/measurements?period=all&quality=pending').get_json()['stats']['count'], 1)
        exported = self.client.get('/api/export.csv?period=all').data.decode('utf-8-sig')
        record = next(csv.DictReader(io.StringIO(exported)))
        self.assertEqual(record['calidad_evaluada'], '0')
        self.assertEqual(record['requiere_revision'], '')

    def test_catalog_coordinates_and_read_only_requests(self):
        before = self.db.read_bytes()
        station = self.client.get('/api/overview').get_json()['stations'][0]
        self.assertEqual(station['name'], 'Corregidora')
        self.assertAlmostEqual(station['lat'], 20.552563888889)
        self.assertEqual(before, self.db.read_bytes())

    def test_health_quality_and_staleness(self):
        self.assertEqual(self.client.get('/health').status_code, 503)
        from data_ingestion.quality import refresh_quality
        with closing(sqlite3.connect(self.db)) as conn, conn:
            refresh_quality(conn, 1352676)
        self.assertEqual(self.client.get('/health').status_code, 200)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM calidad_mediciones')
            conn.execute('UPDATE mediciones SET fecha_utc=?', ((datetime.now(timezone.utc)-timedelta(days=40)).isoformat(),))
        self.assertEqual(self.client.get('/api/measurements?period=7').get_json()['stats']['count'], 0)
        self.assertEqual(self.client.get('/health').status_code, 503)

    def test_missing_database_is_503(self):
        with patch.object(dashboard, 'DB', self.db.parent / 'missing.db'):
            self.assertEqual(self.client.get('/health').status_code, 503)

    def test_legacy_database_without_catalog_or_quality(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DROP TABLE sensores')
            conn.execute('DROP TABLE calidad_mediciones')
        response = self.client.get('/api/overview')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['quality_available'])
        self.assertEqual(response.get_json()['total']['quality_pending'], 1)


if __name__ == '__main__':
    unittest.main()
