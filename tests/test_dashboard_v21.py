"""Public presentation regression fixtures: isolated, never used in the live UI."""
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch
import test_dashboard_v2 as legacy
SID=legacy.SID


class PublicExperienceTests(unittest.TestCase):
    setUp=legacy.DashboardV2Tests.setUp
    tearDown=legacy.DashboardV2Tests.tearDown

    def public(self,query=''):
        return self.client.get('/api/v2/public'+query)

    def history(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            for hour,value in [(7,0),(8,12),(10,9.37)]:
                t=f'2021-09-23T{hour:02d}:00:00Z'
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,?,'pm25',?,'µg/m³')",(t,value))
                conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',1352686,?,'pm25',0,0,0,0,'aeris_qc_v1')",(t,))

    def test_public_and_explorer_routes_preserve_original(self):
        for route in ['/','/v2','/v2/','/v2/datos','/v2/datos/']:
            self.assertEqual(self.client.get(route).status_code,200)
        page=self.client.get('/v2').text
        self.assertIn('no representa necesariamente todo el municipio',page)
        self.assertIn('Huimilpan',page)
        self.assertIn('DESHABILITADO',page)
        self.assertNotIn('https://',page)
        self.assertIn('source',self.client.get('/v2/datos').text)

    def test_public_requires_station_before_describing_concentration(self):
        data=self.public().json
        self.assertEqual(data['public']['state'],'unselected')
        self.assertIsNone(data['station_latest'])
        self.assertIsNone(data['public']['descriptive_mean'])
        self.assertIsNone(data['public']['coverage']['expected_hours'])

    def test_marques_recent_filter_is_empty_but_latest_and_history_remain(self):
        self.history()
        data=self.public('?station=1352686').json
        self.assertEqual(data['stats']['count'],0)
        self.assertEqual(data['public']['state'],'historical')
        self.assertEqual(data['station_latest']['value'],9.37)
        self.assertEqual(data['station_latest']['timestamp_utc'],'2021-09-23T10:00:00Z')
        entry=next(r for r in data['inventory'] if r['sensor_id']==1352686)
        self.assertEqual((entry['source'],entry['year'],entry['count']),('OpenAQ','2021',3))

    def test_marques_all_uses_observed_span_with_gap_and_keeps_zero(self):
        self.history()
        data=self.public('?station=1352686&period=all').json
        c=data['public']['coverage']
        self.assertEqual((c['observed_hours'],c['expected_hours'],c['missing_hours']),(3,4,1))
        self.assertEqual(c['basis'],'observed_span')
        self.assertEqual(data['series'][0]['points'][0]['value'],0)
        self.assertEqual(data['public']['gaps'][0]['hours'],1)
        self.assertIsNone(data['public']['descriptive_mean'])

    def test_sources_are_never_substituted_for_marques(self):
        self.history()
        data=self.public('?station=1352686&source=OpenAQ-Archive&period=all').json
        self.assertEqual(data['public']['state'],'no_observations')
        self.assertIsNone(data['station_latest'])
        self.assertEqual(data['series'],[])
        self.assertTrue(any(r['sensor_id']==1352686 and r['source']=='OpenAQ' for r in data['inventory']))

    def test_year_and_source_inventory_counts_are_independent(self):
        data=self.public('?station=1352676&period=all').json
        rows=[r for r in data['inventory'] if r['sensor_id']==SID]
        api=next(r for r in rows if r['source']=='OpenAQ')
        archive=next(r for r in rows if r['source']=='OpenAQ-Archive' and r['year']=='2025')
        self.assertEqual(api['count'],3)  # excludes incomplete current hour
        self.assertEqual(archive['count'],1)

    def test_complete_window_counts_missing_edges_not_only_internal_gaps(self):
        data=self.public('?station=1352676&period=24h').json
        c=data['public']['coverage']
        self.assertEqual(c['expected_hours'],24)
        self.assertEqual(c['missing_hours'],21)
        self.assertEqual(sum(g['hours'] for g in data['public']['gaps']),21)
        self.assertEqual(data['public']['gaps'][0]['hours'],20)

    def test_no_observations_is_distinct_from_stale(self):
        empty=self.public('?station=1352719').json
        self.assertEqual(empty['public']['state'],'no_observations')
        self.assertIsNone(empty['station_latest'])
        data=self.public('?station=1352676').json
        self.assertEqual(data['public']['state'],'recent')
        from datetime import datetime,timezone
        with patch('aeris_web.data.utc_now',return_value=datetime(2026,10,18,7,tzinfo=timezone.utc)):
            data=self.public('?station=1352676').json
        self.assertEqual(data['public']['state'],'stale')

    def test_archive_is_historical_even_with_a_recent_timestamp(self):
        data=self.public('?station=1352676&source=OpenAQ-Archive&period=all').json
        self.assertEqual(data['public']['state'],'historical')
        self.assertEqual(data['station_latest']['value'],9)

    def test_invalid_public_filters_and_write_methods_fail(self):
        for q in ['?station=99999','?period=2021','?source=all','?year=2021','?station=all&download=1']:
            self.assertEqual(self.public(q).status_code,400)
        self.assertEqual(self.client.post('/api/v2/public').status_code,405)

    def test_quality_and_coverage_gate_descriptive_mean(self):
        from datetime import datetime,timedelta,timezone
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('DELETE FROM mediciones');conn.execute('DELETE FROM calidad_mediciones')
            for i in range(18):
                t=(datetime(2026,10,17,4,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat()
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',?,?, 'pm25',0,'µg/m³')",(SID,t))
                conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',?,?,'pm25',1,0,0,0,'aeris_qc_v1')",(SID,t))
        data=self.public('?station=1352676&period=24h').json
        self.assertEqual(data['public']['descriptive_mean'],0)
        self.assertEqual(data['public']['coverage']['missing_hours'],6)
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('UPDATE calidad_mediciones SET requiere_revision=1 WHERE fecha_utc=(SELECT min(fecha_utc) FROM calidad_mediciones)')
        self.assertIsNone(self.public('?station=1352676&period=24h').json['public']['descriptive_mean'])

    def test_bad_latest_outside_filter_fails_instead_of_presenting_invalid_value(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("UPDATE mediciones SET unidad='ppm' WHERE sensor_id=1352686")
        self.assertEqual(self.public('?station=1352686').status_code,503)

    def test_missing_database_is_not_created(self):
        import app
        missing=self.db.parent/'not-there.db'
        with patch.object(app,'DB',missing):self.assertEqual(self.public().status_code,503)
        self.assertFalse(missing.exists())

    def test_public_requests_preserve_database_and_prediction_contract(self):
        before=self.db.read_bytes()
        for q in ['', '?station=1352686', '?source=OpenAQ-Archive&period=all']:
            data=self.public(q).json
            self.assertFalse(data['predictions']['enabled'])
            self.assertEqual(data['freshness_limit_hours'],2)
        self.assertEqual(before,self.db.read_bytes())
