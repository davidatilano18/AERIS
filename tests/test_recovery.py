import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from data_ingestion.plan_recovery import plan_recovery, contiguous_gaps, query_windows, utc_hour, main
from data_ingestion.sync_pm25_queretaro import ensure_db


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name)/'test.db'
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            ensure_db(conn)
        self.start = utc_hour('2026-01-01T00:00:00Z')

    def tearDown(self):
        self.directory.cleanup()

    def test_gaps_include_edges_and_canonical_offsets(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',2694071,'2025-12-31T20:00:00-06:00','pm25',1,'µg/m³')")
        before = self.db.read_bytes()
        report = plan_recovery(self.db, [2694071], '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
        sensor = report['sensors'][0]
        self.assertEqual(sensor['observed_hours'], 1)
        self.assertEqual(sensor['quality_pending'], 1)
        self.assertEqual([g['hours'] for g in sensor['gaps']], [2, 21])
        self.assertEqual(report['query_count'], 1)
        self.assertEqual(sensor['queries'][0]['expected_missing_hours'], 23)
        self.assertEqual(before, self.db.read_bytes())

    def test_absent_sensor_chunks_without_inventing_availability(self):
        report = plan_recovery(self.db, [2694071], '2026-01-01T00:00:00Z', '2026-01-16T00:00:00Z')
        self.assertEqual(report['missing_hours'], 15*24)
        self.assertEqual(report['query_count'], 3)
        queries = report['sensors'][0]['queries']
        self.assertEqual([q['query_hours'] for q in queries], [168, 168, 24])
        self.assertEqual(queries[0]['to_utc_exclusive'], queries[1]['from_utc'])
        self.assertIn('data_ingestion.sync_pm25_queretaro', queries[0]['python_arguments'])

    def test_full_coverage_has_no_queries_and_review_is_not_gap(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn, conn:
            for hour in range(24):
                stamp = f'2026-01-01T{hour:02}:00:00Z'
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',2694071,?,'pm25',120,'µg/m³')", (stamp,))
                conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',2694071,?,'pm25',0,1,0,1,'test')", (stamp,))
        report = plan_recovery(self.db, [2694071], '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
        self.assertEqual(report['query_count'], 0)
        self.assertEqual(report['missing_hours'], 0)
        self.assertEqual(report['sensors'][0]['quality_review'], 24)

    def test_separated_day_windows_are_not_merged(self):
        gaps = [(self.start, self.start+timedelta(hours=1)),
                (self.start+timedelta(days=3), self.start+timedelta(days=3,hours=1))]
        self.assertEqual(len(query_windows(gaps, 7)), 2)
        self.assertEqual(len(contiguous_gaps(self.start, self.start+timedelta(hours=2),
                                            {self.start, self.start+timedelta(hours=1)})), 0)

    def test_no_quality_table_and_output_not_overwritten(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TABLE calidad_mediciones')
        output = self.db.parent/'plan.json'
        args = ['--db', str(self.db), '--sensor', '2694071', '--from', '2026-01-01',
                '--to', '2026-01-02', '--output', str(output)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['mode'], 'plan_only')
        before = output.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(before, output.read_bytes())

    def test_invalid_inputs_and_normalized_duplicates_fail(self):
        for start, end, sensors in [('2026-01-01T00:00:00', '2026-01-02T00:00:00Z', [2694071]),
                                     ('2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z', [2694071]),
                                     ('2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', [999])]:
            with self.assertRaises(ValueError):
                plan_recovery(self.db, sensors, start, end)
        with contextlib.closing(sqlite3.connect(self.db)) as conn, conn:
            for stamp in ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00+00:00'):
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',2694071,?,'pm25',1,'µg/m³')", (stamp,))
        with self.assertRaisesRegex(ValueError, 'duplicada'):
            plan_recovery(self.db, [2694071], '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')


if __name__ == '__main__':
    unittest.main()
