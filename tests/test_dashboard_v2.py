"""Isolated protocol fixtures only; never used as dashboard observations."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

import app
from data_ingestion.catalog import persist_catalog,load_catalog
from data_ingestion.sync_pm25_queretaro import ensure_db

SID=1352676
NOW=datetime(2026,10,18,4,30,tzinfo=timezone.utc)


class DashboardV2Tests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.db=Path(self.directory.name)/'test.db'
        with closing(sqlite3.connect(self.db)) as conn,conn:
            ensure_db(conn); persist_catalog(conn,load_catalog())
            for source,sid,stamp,value in [
                ('OpenAQ',SID,'2026-10-18T00:00:00Z',0),
                ('OpenAQ',SID,'2026-10-18T02:00:00Z',20),
                ('OpenAQ',SID,'2026-10-18T03:00:00+00:00',30),
                ('OpenAQ',SID,'2026-10-18T04:00:00Z',999),
                ('OpenAQ',2694071,'2026-10-18T02:00:00Z',50),
                ('OpenAQ-Archive',SID,'2025-06-01T00:00:00Z',7),
                ('OpenAQ-Archive',SID,'2026-10-18T00:00:00Z',9),
            ]:
                conn.execute("INSERT INTO mediciones VALUES (?,?,?,'pm25',?,'µg/m³')",(source,sid,stamp,value))
            conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',?,'2026-10-18T00:00:00Z','pm25',1,0,0,0,'aeris_qc_v2')",(SID,))
            conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',?,'2026-10-18T02:00:00Z','pm25',0,0,0,1,'aeris_qc_v1')",(SID,))
        self.db_patch=patch.object(app,'DB',self.db); self.db_patch.start()
        self.clock=patch('aeris_web.data.utc_now',return_value=NOW); self.clock.start()
        self.client=app.app.test_client()

    def tearDown(self):
        self.clock.stop(); self.db_patch.stop(); self.directory.cleanup()

    def get(self,query=''):
        return self.client.get('/api/v2/observations'+query)

    def test_v2_is_separate_jinja_page_with_local_assets(self):
        page=self.client.get('/v2')
        self.assertEqual(page.status_code,200)
        public=page.get_data(as_text=True)
        self.assertIn('El aire que compartimos',public)
        self.assertIn('/v2/datos',public)
        text=self.client.get('/v2/datos').get_data(as_text=True)
        self.assertIn('Predicción, con evidencia primero',text)
        self.assertIn('DESHABILITADO',text)
        self.assertNotIn('https://',text)
        self.assertIn('/api/v2/observations',text)
        for asset in ('css/dashboard.css','js/main.js','vendor/leaflet/leaflet.js','vendor/chartjs/chart.umd.js'):
            with self.client.get('/static/v2/'+asset) as response:
                self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/v2/').status_code,200)

    def test_existing_routes_still_respond(self):
        for url in ('/','/api/overview','/api/measurements?period=all','/api/comparison','/api/export.csv?period=all'):
            self.assertEqual(self.client.get(url).status_code,200)

    def test_source_isolation_even_when_same_sensor_and_hour_overlap(self):
        api=self.get('?source=OpenAQ&period=all').get_json()
        archive=self.get('?source=OpenAQ-Archive&period=all').get_json()
        self.assertEqual(api['stats']['count'],4)
        self.assertEqual(archive['stats']['count'],2)
        self.assertEqual(archive['stats']['mean'],8)
        self.assertTrue(all(point['source']=='OpenAQ' for series in api['series'] for point in series['points'] if not point.get('gap')))

    def test_observed_zero_and_true_mean_are_preserved(self):
        data=self.get().get_json()
        self.assertEqual(data['stats']['mean'],25)
        point=data['series'][0]['points'][0]
        self.assertEqual(point['value'],0)
        self.assertEqual(point['quality']['zero'],1)
        self.assertEqual(data['unit'],'µg/m³')

    def test_discontinuous_hours_have_null_separator_not_new_observations(self):
        data=self.get('?station=1352676').get_json()
        series=data['series'][0]
        self.assertEqual(series['missing_hours_between_observations'],1)
        self.assertEqual([p['value'] for p in series['points']],[0,None,20,30])
        self.assertTrue(series['points'][1]['gap'])
        self.assertEqual(data['stats']['count'],3)
        self.assertEqual(len(data['recent_observations']),3)

    def test_utc_normalized_and_end_exclusive_no_unfinished_hour(self):
        data=self.get().get_json()
        self.assertEqual(data['window']['to_exclusive_utc'],'2026-10-18T04:00:00Z')
        self.assertEqual(data['stats']['latest']['timestamp_utc'],'2026-10-18T03:00:00Z')
        self.assertAlmostEqual(data['stats']['age_hours'],1.5)
        self.assertNotIn(999,[r['value'] for r in data['recent_observations']])

    def test_missing_station_data_keeps_catalog_coordinates_without_fake_value(self):
        response=self.get('?station=1352719').get_json()
        self.assertEqual(response['stats']['count'],0)
        self.assertIsNone(response['stats']['mean']); self.assertIsNone(response['stats']['latest'])
        self.assertEqual(response['series'],[])
        station=next(s for s in response['stations'] if s['sensor_id']==1352719)
        self.assertEqual(station['count'],0); self.assertIsNone(station['latest_utc'])
        self.assertAlmostEqual(station['lat'],20.565863888889)

    def test_catalog_complete_and_metadata_not_fabricated(self):
        data=self.client.get('/api/v2/stations?source=OpenAQ-Archive').get_json()
        self.assertEqual(len(data['stations']),8)
        station=next(s for s in data['stations'] if s['sensor_id']==SID)
        self.assertEqual(station['location_id'],235225)
        self.assertEqual(station['provider'],'Sinaica Mexico')
        self.assertFalse(station['fresh'])  # Even a recent Archive point is not operational API.

    def test_bad_filters_fail_without_silent_fallback(self):
        for query in ('?source=all','?source=synthetic','?station=9999','?station=abc','?period=2025','?unexpected=yes'):
            self.assertEqual(self.get(query).status_code,400)

    def test_quality_is_initial_version_and_pending_not_clean(self):
        data=self.get().get_json()
        self.assertEqual(data['stats']['pending_quality'],2)
        self.assertEqual(data['stats']['review'],1)
        self.assertTrue(any(r['quality']['version']=='aeris_qc_v1' for r in data['recent_observations']))

    def test_unavailable_database_safe_error_no_creation(self):
        missing=self.db.parent/'missing.db'
        with patch.object(app,'DB',missing): self.assertEqual(self.get().status_code,503)
        self.assertFalse(missing.exists())

    def test_incompatible_units_fail_not_convert_or_mix(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("UPDATE mediciones SET unidad='mg/m³' WHERE sensor_id=?",(SID,))
        self.assertEqual(self.get().status_code,503)

    def test_naive_or_duplicate_utc_data_fails_closed(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',?,'2026-10-18T02:00:00+00:00','pm25',20,'µg/m³')",(SID,))
        self.assertEqual(self.get().status_code,503)

    def test_large_payload_requires_explicit_narrower_selection(self):
        with patch('aeris_web.data.MAX_ROWS',2): self.assertEqual(self.get().status_code,413)

    def test_requests_do_not_write_sqlite_or_enable_predictions(self):
        before=self.db.read_bytes()
        data=self.get('?source=OpenAQ-Archive&period=all').get_json()
        self.client.get('/api/v2/stations'); self.client.get('/v2')
        self.assertEqual(before,self.db.read_bytes())
        self.assertEqual(data['freshness_limit_hours'],2)
        self.assertFalse(data['predictions']['enabled'])
        self.assertEqual(self.client.post('/api/v2/observations').status_code,405)

    def test_local_vendor_files_match_verified_manifest(self):
        root=Path(app.ROOT)
        manifest=json.loads((root/'static/v2/vendor/manifest.json').read_text())
        for package in manifest:
            for item in package['files']:
                self.assertEqual(hashlib.sha256((root/item['path']).read_bytes()).hexdigest(),item['sha256'])
