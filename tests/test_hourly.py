"""Pruebas temporales con series artificiales; ningún estimador real se entrena."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from forecasting.hourly import load_series, build_dataset, split_period, evaluate, FEATURES
from forecasting.evaluate_hourly import main
from data_ingestion.sync_pm25_queretaro import ensure_db
from data_ingestion.quality import refresh_quality


class HourlyTests(unittest.TestCase):
    def setUp(self):
        self.series = pd.Series(np.arange(800, dtype=float),
                                index=pd.date_range('2026-01-01', periods=800, freq='h', tz='UTC'))

    def test_targets_and_latency_for_all_horizons(self):
        for horizon in (1, 6, 24):
            with self.subTest(horizon=horizon):
                table = build_dataset(self.series, horizon, latency_hours=2)
                row = table.iloc[300]
                self.assertEqual(row['target'], 300+horizon)
                self.assertEqual(row['lag_0'], 298)
                self.assertEqual(row['lag_24'], 274)
                self.assertEqual(row['target_at'], self.series.index[300+horizon])
                self.assertLessEqual(row['estacional_24h'], 298)

    def test_holes_preserved_and_future_does_not_change_features(self):
        changed = self.series.copy()
        changed.iloc[301:] = 99999
        original = build_dataset(self.series, 24)
        altered = build_dataset(changed, 24)
        pd.testing.assert_series_equal(original.iloc[300][FEATURES], altered.iloc[300][FEATURES])
        self.assertNotEqual(original.iloc[300]['target'], altered.iloc[300]['target'])
        missing = self.series.drop(self.series.index[250])
        table = build_dataset(missing, 6, latency_hours=0)
        self.assertTrue(pd.isna(table.iloc[244]['target']))
        self.assertTrue(pd.isna(table.iloc[251]['lag_1']))

    def test_labels_are_available_before_first_emission(self):
        for horizon in (1, 6, 24):
            table = build_dataset(self.series, horizon, latency_hours=2)
            start, end = self.series.index[500], self.series.index[600]
            train, test = split_period(table, start, end)
            self.assertTrue((train['label_available_at'] < start).all())
            self.assertEqual(len(test), 100)
            self.assertEqual(test.index.min(), start)
            self.assertLess(test.index.max(), end)

    def test_common_samples_and_stub_model(self):
        table = build_dataset(self.series, 6)
        class Stub:
            def fit(stub, x, y):
                self.assertLess(x.index.max()+pd.Timedelta(hours=7), self.series.index[500])
            def predict(stub, x):
                return x['lag_0'].to_numpy()
        result = evaluate(table, self.series.index[500], self.series.index[600], Stub, min_train=100, min_test=50)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['metrics']['persistencia'], result['metrics']['random_forest'])
        self.assertEqual(result['test_samples'], 100)
        self.assertEqual(result['metrics']['persistencia']['mae'], 7)

    def test_outside_data_window_is_counted_as_missing(self):
        table = build_dataset(self.series, 24)
        start = self.series.index[-1]+pd.Timedelta(hours=1)
        result = evaluate(table, start, start+pd.Timedelta(days=1), min_test=1)
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertEqual(result['candidate_emissions'], 24)
        self.assertEqual(result['coverage_pct'], 0)

    def test_sqlite_quality_utc_and_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'input.db'
            with contextlib.closing(sqlite3.connect(db)) as conn, conn:
                ensure_db(conn)
                conn.executemany("INSERT INTO mediciones VALUES ('OpenAQ',1,?,'pm25',?,'µg/m³')",
                                 [(t.isoformat(), float(i % 50)) for i, t in enumerate(self.series.index)])
                refresh_quality(conn, 1)
                conn.execute('DELETE FROM calidad_mediciones WHERE fecha_utc=?', (self.series.index[200].isoformat(),))
            before = db.read_bytes()
            series, metadata = load_series(db, 1)
            self.assertTrue(pd.isna(series.iloc[200]))
            self.assertEqual(metadata['quality_pending'], 1)
            self.assertEqual(metadata['usable_records'], 799)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(['--db', str(db), '--sensor', '1', '--start', '2026-01-20T00:00:00Z', '--folds', '1'])
            report = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report['mode'], 'plan_only')
            self.assertEqual(len(report['results']), 3)
            self.assertEqual(before, db.read_bytes())

    def test_naive_dates_and_duplicate_instants_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'input.db'
            with contextlib.closing(sqlite3.connect(db)) as conn, conn:
                ensure_db(conn)
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1,'2026-01-01T00:00:00','pm25',1,'µg/m³')")
            with self.assertRaisesRegex(ValueError, 'sin zona'):
                load_series(db, 1)
            with contextlib.closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('DELETE FROM mediciones')
                conn.executemany("INSERT INTO mediciones VALUES ('OpenAQ',1,?,'pm25',1,'µg/m³')",
                                 [('2026-01-01T00:00:00Z',), ('2026-01-01T00:00:00+00:00',)])
            with self.assertRaisesRegex(ValueError, 'duplicadas'):
                load_series(db, 1)

    def test_cli_never_overwrites_output(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder)/'report.json'
            report.write_text('preservar', encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_code:
                main(['--sensor', '1', '--start', '2026-01-01T00:00:00Z', '--output', str(report)])
            self.assertEqual(exit_code.exception.code, 2)
            self.assertEqual(report.read_text(encoding='utf-8'), 'preservar')

    def test_units_and_negative_values_rejected_even_without_quality_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder)/'input.db'
            with contextlib.closing(sqlite3.connect(db)) as conn, conn:
                ensure_db(conn)
                conn.executemany("INSERT INTO mediciones VALUES ('OpenAQ',1,?,'pm25',?,?)", [
                    ('2026-01-01T00:00:00Z', 10, 'ppm'),
                    ('2026-01-01T01:00:00Z', -1, 'µg/m³'),
                    ('2026-01-01T02:00:00Z', 0, 'µg/m³')])
            series, metadata = load_series(db, 1, quality='all')
            self.assertEqual(metadata['usable_records'], 1)
            self.assertEqual(series.iloc[2], 0)
            self.assertTrue(series.iloc[:2].isna().all())

    def test_multiple_models_share_training_and_test_samples(self):
        table=build_dataset(self.series,24)
        seen=[]
        class Stub:
            def fit(stub,x,y):
                seen.append(('train',tuple(x.index)))
            def predict(stub,x):
                seen.append(('test',tuple(x.index)))
                return x['lag_0'].to_numpy()
        result=evaluate(table,self.series.index[500],self.series.index[650],
                        min_train=100,min_test=100,model_factories={'rf':Stub,'boosting':Stub})
        self.assertEqual(seen[0],seen[2])
        self.assertEqual(seen[1],seen[3])
        self.assertEqual(result['metrics']['rf'],result['metrics']['boosting'])

    def test_subhour_observation_is_rejected_before_resampling(self):
        bad=pd.Series([1,2],index=pd.DatetimeIndex(['2026-01-01T00:00:00Z','2026-01-01T00:30:00Z']))
        with self.assertRaisesRegex(ValueError,'horas exactas'):
            build_dataset(bad,1)

    def test_rmse_summary_uses_squared_errors(self):
        from forecasting.summarize_evaluations import summarize
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'evaluation.json'
            rows=[]
            for day,rmse in [(1,3),(2,4)]:
                rows.append({'horizon_hours':1,'status':'ok','test_samples':1,'candidate_emissions':2,
                             'issue_start':f'2026-01-{day:02}T00:00:00Z',
                             'issue_end_exclusive':f'2026-01-{day+1:02}T00:00:00Z',
                             'metrics':{'persistencia':{'mae':2,'rmse':rmse}}})
            output.write_text(json.dumps({'input':{'sensor_id':1,'source':'test'},'results':rows}),encoding='utf8')
            result=summarize([output])['summaries'][0]
            self.assertAlmostEqual(result['metrics']['persistencia']['rmse'],np.sqrt(12.5))
            self.assertEqual(result['coverage_pct'],50)


if __name__ == '__main__':
    unittest.main()
