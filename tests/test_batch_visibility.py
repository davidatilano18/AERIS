"""Visibility integration on isolated protocol fixtures; no production data or training."""
import csv
import ast
import importlib
import io
import json
import sqlite3
import sys
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from pathlib import Path

import app
from aeris_web.data import read_dashboard
from aeris_web.comparisons import read_comparison
from data_ingestion import archive_controlled as archive
from data_ingestion.catalog import load_catalog,persist_catalog
from data_ingestion.visibility import connect_readonly
from forecasting.hourly import load_series


class BatchVisibilityTests(unittest.TestCase):
    def setUp(self):
        fixture_module=importlib.import_module('test_archive_controlled')
        self.fixture=fixture_module.ControlledArchiveTests('test_scoped_quality_and_repeat_are_fully_idempotent')
        self.fixture.setUp();self.db=self.fixture.db
        with closing(sqlite3.connect(self.db)) as conn,conn:persist_catalog(conn,load_catalog())
        self.app_patch=patch.object(app,'DB',self.db);self.app_patch.start()
        self.client=app.app.test_client()

    def tearDown(self):self.app_patch.stop();self.fixture.tearDown()
    def activate(self):archive.import_copy(self.fixture.bundle,self.db)
    def revert(self):archive.set_visibility(self.db,'fixture-batch','inactive','Visibility regression')
    def count(self,table='mediciones',physical=False):
        with closing(sqlite3.connect(self.db) if physical else connect_readonly(self.db)) as conn:
            return conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_legacy_database_without_ledger_has_identical_content_and_bytes(self):
        before=self.db.read_bytes()
        with closing(connect_readonly(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM calidad_mediciones').fetchone()[0],3)
            self.assertTrue(conn.in_transaction)
        self.assertEqual(before,self.db.read_bytes())

    def test_active_reverted_and_reactivated_states(self):
        self.activate();self.assertEqual(self.count(),74)
        before=self.db.read_bytes();self.revert();reverted=self.db.read_bytes()
        self.assertEqual(self.count(),3);self.assertEqual(self.count(physical=True),74)
        self.assertEqual(reverted,self.db.read_bytes())
        archive.set_visibility(self.db,'fixture-batch','active','restore')
        self.assertEqual(self.count(),74)

    def test_quality_evaluations_and_links_exclude_withdrawn_observations(self):
        self.activate();self.revert()
        self.assertEqual(self.count('calidad_mediciones'),3)
        with closing(connect_readonly(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evaluaciones_calidad WHERE fecha_utc LIKE '2025-05-%'").fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM evaluaciones_calidad_ingestas').fetchone()[0],0)
        self.assertGreater(self.count('evaluaciones_calidad',physical=True),self.count('evaluaciones_calidad'))

    def test_original_apis_stats_and_csv_follow_same_policy(self):
        self.activate()
        self.assertEqual(self.client.get('/api/overview').get_json()['total']['count'],74)
        self.assertEqual(self.client.get('/api/measurements?period=all').get_json()['stats']['count'],74)
        self.revert()
        self.assertEqual(self.client.get('/api/overview').get_json()['total']['count'],3)
        stats=self.client.get('/api/measurements?period=all').get_json()['stats']
        self.assertEqual(stats['count'],3);self.assertEqual(stats['mean'],10)
        response=self.client.get('/api/export.csv?period=all')
        rows=list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff'))))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['fecha_utc']=='2025-06-01T00:00:00Z' for r in rows))

    def test_v2_public_inventory_sources_and_latest_are_filtered(self):
        self.activate();self.revert()
        for endpoint in ('/api/v2/observations','/api/v2/public'):
            result=self.client.get(endpoint+'?source=OpenAQ-Archive&period=all').get_json()
            self.assertEqual(result['stats']['count'],3)
            self.assertEqual(result['stats']['pending_quality'],0)
            self.assertEqual(result['stats']['latest']['timestamp_utc'],'2025-06-01T00:00:00Z')
            if 'inventory' in result:self.assertEqual(sum(x['count'] for x in result['inventory']),3)
        data=self.client.get('/api/v2/stations?source=OpenAQ-Archive&period=all').get_json()
        self.assertEqual(sum(s['count'] for s in data['stations']),3)

    def test_later_measurement_and_same_instant_other_source_remain_visible(self):
        self.activate();c=self.fixture.candidates[0]
        with closing(sqlite3.connect(self.db)) as conn,conn:
            # Simulated later insert, retaining its own source and key.
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',('OpenAQ',c['sensor_id'],c['utc'],'pm25',15,'µg/m³'))
            archive.qc.evaluate(conn,c['sensor_id'],'OpenAQ')
        self.revert()
        self.assertEqual(self.count(),4)
        self.assertEqual(read_dashboard(self.db,source='OpenAQ',period='all')['stats']['count'],1)

    def test_research_series_and_fingerprint_restore_without_training(self):
        baseline,meta=load_series(self.db,1352676,source=archive.SOURCE)
        self.activate()
        _,active=load_series(self.db,1352676,source=archive.SOURCE)
        self.assertEqual(active['records'],25)
        self.revert()
        series,restored=load_series(self.db,1352676,source=archive.SOURCE)
        self.assertTrue(series.equals(baseline));self.assertEqual(restored['input_sha256'],meta['input_sha256'])

    def test_partial_or_unknown_ledger_state_fails_closed(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('CREATE TABLE archive_batches(batch_id TEXT)')
        with self.assertRaises(sqlite3.DatabaseError):connect_readonly(self.db)
        self.assertEqual(self.client.get('/api/v2/observations').status_code,503)

    def test_missing_effective_batch_event_is_not_silently_visible(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            archive.ledger(conn)
            conn.execute("INSERT INTO archive_batches VALUES ('empty','hash','run','2025-01-01','{}')")
        with self.assertRaises(sqlite3.DatabaseError):connect_readonly(self.db)

    def test_read_connection_cannot_modify_original_or_temporary_policy(self):
        self.activate();self.revert()
        with closing(connect_readonly(self.db)) as conn:
            for statement in ('DELETE FROM main.mediciones','DELETE FROM temp._aeris_excluded_keys'):
                with self.assertRaises(sqlite3.OperationalError):conn.execute(statement)

    def test_snapshot_keeps_consistent_state_during_reversal(self):
        self.activate()
        # WAL permits a concurrent state change while the earlier reader keeps its snapshot.
        with closing(sqlite3.connect(self.db)) as conn:conn.execute('PRAGMA journal_mode=WAL')
        with closing(connect_readonly(self.db)) as old:
            self.assertEqual(old.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],74)
            self.revert()
            self.assertEqual(old.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0],74)
        self.assertEqual(self.count(),3)

    def test_pages_remain_accessible_in_both_states(self):
        self.activate()
        for _ in range(2):
            for route in ('/','/v2','/v2/datos','/api/comparison'):
                self.assertEqual(self.client.get(route).status_code,200)
            self.revert()

    def test_adjacent_successor_quality_becomes_pending_without_mutation(self):
        self.activate()
        # An unowned visible observation whose original v2 jump depends on a withdrawn predecessor.
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ-Archive',1352676,'2025-05-02T07:00:00Z','pm25',150,'µg/m³')")
            archive.qc.evaluate(conn,1352676,archive.SOURCE)
        self.revert()
        with closing(connect_readonly(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT valor FROM mediciones WHERE fecha_utc='2025-05-02T07:00:00Z'").fetchone()[0],150)
            self.assertIsNone(conn.execute("SELECT 1 FROM calidad_mediciones WHERE fecha_utc='2025-05-02T07:00:00Z'").fetchone())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc='2025-05-02T07:00:00Z'").fetchone()[0],1)

    def test_comparisons_abstain_when_reversion_removes_coverage(self):
        self.activate()
        start=datetime(2025,5,1,tzinfo=timezone.utc)
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO archive_batches VALUES ('comparison','hash','run','2025-01-01','{}')")
            conn.execute("INSERT INTO archive_batch_events(batch_id,action,registered_utc,reason) VALUES ('comparison','active','2025-01-01','fixture')")
            for i in range(72):
                t=(start+timedelta(hours=i)).isoformat().replace('+00:00','Z')
                conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',(archive.SOURCE,8956473,t,'pm25',10+i/100,'µg/m³'))
                if i>=48:conn.execute('INSERT INTO archive_batch_keys VALUES (?,?,?,?,?)',('comparison',archive.SOURCE,8956473,t,'pm25'))
            archive.qc.evaluate(conn,8956473,archive.SOURCE)
        clock=start+timedelta(hours=72)
        with patch('aeris_web.comparisons.utc_now',return_value=clock):
            before=read_comparison(self.db,source=archive.SOURCE,station='8956473')
            self.assertEqual(before['status'],'compared');self.assertEqual(before['matched_hours'],24)
            archive.set_visibility(self.db,'comparison','inactive','Coverage fixture')
            after=read_comparison(self.db,source=archive.SOURCE,station='8956473')
            self.assertEqual(after['status'],'abstained');self.assertEqual(after['matched_hours'],0)
            self.assertIn('insufficient_coverage',after['reasons'])

    def test_distinct_batches_do_not_hide_each_others_observations(self):
        self.activate()
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO archive_batches VALUES ('other','hash','run','2025-01-01','{}')")
            conn.execute("INSERT INTO archive_batch_events(batch_id,action,registered_utc,reason) VALUES ('other','active','2025-01-01','fixture')")
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ-Archive',8956473,'2025-05-01T07:00:00Z','pm25',17,'µg/m³')")
            conn.execute("INSERT INTO archive_batch_keys VALUES ('other','OpenAQ-Archive',8956473,'2025-05-01T07:00:00Z','pm25')")
        self.revert();self.assertEqual(self.count(),4)
        archive.set_visibility(self.db,'other','inactive','Independent batch')
        self.assertEqual(self.count(),3)
        archive.set_visibility(self.db,'fixture-batch','active','Restore first only')
        self.assertEqual(self.count(),74)

    def test_coverage_audit_defaults_to_visible_and_forensic_mode_is_explicit(self):
        self.activate();self.revert()
        from scripts import audit_data_coverage as audit
        from data_ingestion.operations import ensure_operations
        with closing(sqlite3.connect(self.db)) as conn,conn:ensure_operations(conn)
        root=self.fixture.root;(root/'data').mkdir();(root/'reports').mkdir()
        with closing(sqlite3.connect(self.db)) as source:
            with closing(sqlite3.connect(root/'data/aeris_air_quality.db')) as target:source.backup(target)
        for flag,expected in (([],3),(['--physical-audit'],74)):
            with patch.object(audit,'ROOT',root),patch.object(sys,'argv',['audit']+flag):audit.main()
            result=json.loads((root/'reports/aeris_data_coverage.json').read_text(encoding='utf-8'))
            self.assertEqual(result['records'],expected)
            self.assertTrue(result['byte_identical_during_audit'])

    def test_active_sqlite_readers_use_central_factory(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('app.py','aeris_web/data.py','aeris_web/comparisons.py',
                     'forecasting/hourly.py','forecasting/temporal.py','data_ingestion/plan_recovery.py'):
            tree=ast.parse((root/name).read_text(encoding='utf-8'))
            calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
            self.assertIn('connect_readonly',calls,name)
            self.assertNotIn('sqlite3.connect',calls,name)


if __name__=='__main__':unittest.main()
