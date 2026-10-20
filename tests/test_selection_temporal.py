import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from forecasting.temporal import alignment
from forecasting.selection import select,reserve_holdout,validate_training_cutoff
from forecasting.hourly import FEATURES


class SelectionTemporalTests(unittest.TestCase):
    def report(self,path,coverage=100,gain=0.10):
        rows=[]
        for fold,day in [(1,1),(2,15),(3,29)]:
            start=pd.Timestamp(f'2025-08-{day:02}T00:00:00Z')
            end=start+pd.Timedelta(days=14)
            rows.append({'horizon_hours':1,'fold':fold,'status':'ok','training_samples':700,
                         'candidate_emissions':300,'test_samples':int(coverage*3),
                         'issue_start':start.isoformat(),'issue_end_exclusive':end.isoformat(),
                         'last_target_at':end.isoformat(),
                         'metrics':{name:{'mae':mae,'rmse':mae+1} for name,mae in
                                    [('persistencia',10),('promedio_24h',11),('estacional_24h',12),
                                     ('random_forest',10*(1-gain)),('hist_gradient_boosting',11)]}})
        report={'mode':'train','input':{'sensor_id':2694071,'source':'OpenAQ-Archive',
                'quality_policy':'evaluated','quality_versions':['aeris_qc_v2'],'input_sha256':'fixture'},
                'latency_hours_assumed':1,'features':FEATURES,
                'model_config':{'random_forest':{},'hist_gradient_boosting':{}},'results':rows}
        path.write_text(json.dumps(report),encoding='utf8')

    def test_shift_is_detected_and_never_authorizes_substitution(self):
        index=pd.date_range('2026-01-01',periods=100,freq='h',tz='UTC')
        api=pd.Series(np.arange(100,dtype=float),index=index)
        archive=api.copy();archive.index+=pd.Timedelta(hours=1)
        result=alignment(archive,api)
        self.assertEqual(result['status'],'timestamp_mismatch')
        self.assertEqual(result['best_shift_hours'],-1)
        self.assertFalse(result['automatic_source_substitution_allowed'])

    def test_constant_or_insufficient_overlap_is_unverified(self):
        index=pd.date_range('2026-01-01',periods=100,freq='h',tz='UTC')
        self.assertEqual(alignment(pd.Series(0.,index=index),pd.Series(0.,index=index))['status'],'unverified')
        varying=pd.Series(np.arange(100,dtype=float),index=index)
        self.assertEqual(alignment(varying.iloc[:10],varying)['status'],'unverified')

    def test_convincing_gain_selected_but_small_gain_or_poor_coverage_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            for coverage,gain,expected in [(100,.10,'random_forest'),(60,.10,'persistencia'),(100,.01,'persistencia')]:
                self.report(path,coverage,gain)
                self.assertEqual(select([path])['decisions'][0]['selected_method'],expected)

    def test_holdout_must_be_future_and_after_all_development_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';self.report(path)
            selection=select([path])
            plan=reserve_holdout(selection,'2026-10-19T00:00:00Z','2026-11-19T00:00:00Z','2026-10-17T12:00:00Z')
            self.assertEqual(plan['status'],'reserved_not_evaluated')
            with self.assertRaises(ValueError):
                reserve_holdout(selection,'2025-08-01T00:00:00Z','2025-09-01T00:00:00Z','2026-10-17T12:00:00Z')
            with self.assertRaises(ValueError):
                reserve_holdout(selection,'2025-09-01T00:00:00Z','2025-10-01T00:00:00Z','2025-07-01T00:00:00Z')

    def test_training_cutoff_cannot_hide_future_model_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';self.report(path)
            selection=select([path])
            with self.assertRaises(ValueError):
                validate_training_cutoff(selection,'2025-07-01T00:00:00Z','2026-10-19T00:00:00Z','2026-10-17T12:00:00Z')
            self.assertEqual(validate_training_cutoff(selection,'2025-10-01T00:00:00Z',
                             '2026-10-19T00:00:00Z','2026-10-17T12:00:00Z'),pd.Timestamp('2025-10-01T00:00:00Z'))


if __name__=='__main__':unittest.main()
