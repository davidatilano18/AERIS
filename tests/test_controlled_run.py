import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from data_ingestion.controlled_run import CachedClient,CriticalFailure,CriticalConnection,compare_original,replay_on_copy
from data_ingestion.operations import ensure_db,copy_database
from data_ingestion.quality import refresh_quality


class ControlledRunTests(unittest.TestCase):
    def test_frozen_cache_refuses_unprepared_network_request(self):
        class Live:
            def get(self,path,params):return {'results':[]}
        cache=CachedClient(Live());cache.get('/prepared',{})
        cache.frozen=True
        self.assertEqual(cache.get('/prepared',{}),{'results':[]})
        with self.assertRaises(CriticalFailure):cache.get('/unprepared',{})

    def test_old_quality_change_aborts_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.db';backup=Path(folder)/'backup.db'
            with closing(sqlite3.connect(db)) as conn,conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-10-17T10:00:00Z','pm25',10,'µg/m³')")
                refresh_quality(conn,1)
            copy_database(db,backup)
            with closing(sqlite3.connect(db)) as conn:
                with self.assertRaises(CriticalFailure),conn:
                    conn.execute('UPDATE calidad_mediciones SET es_cero=1')
                    compare_original(conn,backup)
                self.assertEqual(conn.execute('SELECT es_cero FROM calidad_mediciones').fetchone()[0],0)

    def test_changed_measurement_is_critical_before_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.db';backup=Path(folder)/'backup.db'
            with closing(sqlite3.connect(db)) as conn,conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-10-17T10:00:00Z','pm25',10,'µg/m³')")
            copy_database(db,backup)
            with closing(sqlite3.connect(db)) as conn:
                with self.assertRaises(CriticalFailure),conn:
                    conn.execute('UPDATE mediciones SET valor=11')
                    compare_original(conn,backup)

    def test_sqlite_error_bypasses_noncritical_exception_handlers(self):
        with closing(sqlite3.connect(':memory:',factory=CriticalConnection)) as conn:
            with self.assertRaises(CriticalFailure):conn.execute('SELECT * FROM nonexistent_table')

    def test_idempotence_replay_writes_only_disposable_copy(self):
        from datetime import datetime,timezone
        from data_ingestion import operations as ops
        from tests.test_operations import FakeClient,hour
        from data_ingestion.production_preflight import sha
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'source.db';baseline=Path(folder)/'baseline.db'
            with closing(sqlite3.connect(db)) as conn,conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',10,'µg/m³')")
                conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',0,0,1,1,'aeris_qc_v1')")
            copy_database(db,baseline)
            cache=CachedClient(FakeClient([hour(),hour('2020-01-01T01:00:00Z',11)]))
            sync=ops.run(db,[1352676],start=datetime(2020,1,1,tzinfo=timezone.utc),
                         end=datetime(2020,1,2,tzinfo=timezone.utc),key='fixture-key',client=cache)
            before=sha(db)
            result=replay_on_copy(db,baseline,sync,cache,'fixture-key')
            self.assertEqual(sha(db),before)
            self.assertTrue(result['original_unchanged_during_replay'])
            self.assertEqual(result['results'][0]['new_measurements'],0)
            self.assertEqual(result['evaluations_before'],result['evaluations_after'])


if __name__=='__main__':unittest.main()
