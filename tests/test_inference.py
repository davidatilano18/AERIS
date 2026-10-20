import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from forecasting.artifacts import ReferenceModel,write_bundle,code_hashes,dependencies,contract
from forecasting.selection import sha
from forecasting.inference import predict
from forecasting.final_test import evaluate_reserved
from data_ingestion.sync_pm25_queretaro import ensure_db
from data_ingestion.quality import refresh_quality


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.db=self.root/'test.db';self.release=self.root/'release';self.release.mkdir()
        index=pd.date_range('2025-07-01',periods=360,freq='h',tz='UTC')
        with closing(sqlite3.connect(self.db)) as conn,conn:
            ensure_db(conn)
            conn.executemany("INSERT INTO mediciones VALUES ('OpenAQ-Archive',2694071,?,'pm25',?,'µg/m³')",
                             [(t.isoformat(),float(i%50)) for i,t in enumerate(index)])
            refresh_quality(conn,2694071,'OpenAQ-Archive')
        holdout={'issue_start':'2026-10-19T00:00:00Z','issue_end_exclusive':'2026-11-19T00:00:00Z',
                 'frozen_at':'2026-10-17T12:00:00Z','latency_hours_assumed':1,'source':'OpenAQ-Archive',
                 'minimum_samples_per_station_horizon':500,'minimum_coverage_pct':70}
        for name,value in [('selection.json',{}),('temporal_audit.json',{}),('holdout_plan.json',holdout)]:
            (self.release/name).write_text(json.dumps(value),encoding='utf8')
        meta={'schema':'aeris-pm25-bundle-v1','release_version':'test','sensor_id':2694071,'horizon_hours':1,
              'selected_method':'promedio_24h','validation_state':'candidate_pending_independent_test',
              'operational_enabled':False,'temporal_contract':contract(),'required_quality_version':'aeris_qc_v2',
              'features_by_method':{'promedio_24h':['promedio_24h']},
              'training':{'cutoff_exclusive':'2025-07-01T00:00:00Z','last_label_available_at':'2025-06-30T23:00:00Z'},
              'max_data_age_hours':2,'max_training_age_days':90,'dependencies':dependencies(),'code_hashes':code_hashes()}
        hashes={key:sha(self.release/name) for name,key in [('selection.json','selection_sha256'),
                ('holdout_plan.json','holdout_plan_sha256'),('temporal_audit.json','temporal_audit_sha256')]}
        entry=write_bundle(self.release/'2694071_1h',{'promedio_24h':ReferenceModel('promedio_24h')},{**meta,**hashes})
        registry={'schema':'aeris-release-v1','version':'test','entries':[{'sensor_id':2694071,'horizon_hours':1,**entry}],**hashes}
        (self.release/'registry.json').write_text(json.dumps(registry),encoding='utf8')

    def tearDown(self):self.directory.cleanup()

    def run_prediction(self,issued='2025-07-10T12:00:00Z',mode='replay',source='OpenAQ-Archive',now='2026-10-17T00:00:00Z'):
        return predict(self.release,self.db,2694071,1,source,issued,mode,now)

    def test_replay_predicts_from_real_shape_fixture_and_does_not_write_sqlite(self):
        before=self.db.read_bytes();result=self.run_prediction()
        self.assertEqual(result['status'],'exploratory_replay')
        self.assertFalse(result['operational'])
        self.assertGreaterEqual(result['pm25_ug_m3'],0)
        self.assertEqual(before,self.db.read_bytes())

    def test_future_values_cannot_change_prediction(self):
        before=self.run_prediction()['pm25_ug_m3']
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("UPDATE mediciones SET valor=999 WHERE fecha_utc>=?",('2025-07-10T12:00:00+00:00',))
        self.assertEqual(before,self.run_prediction()['pm25_ug_m3'])

    def test_missing_required_hour_abstains(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute('DELETE FROM calidad_mediciones WHERE fecha_utc=?',('2025-07-10T10:00:00+00:00',))
        result=self.run_prediction()
        self.assertEqual(result['status'],'abstained')
        self.assertIn('missing_required_observations',result['reasons'])

    def test_stale_data_abstains(self):
        result=self.run_prediction(issued='2025-07-20T00:00:00Z')
        self.assertIn('stale_measurements',result['reasons'])

    def test_source_substitution_is_refused_before_model_load(self):
        with patch('forecasting.inference.joblib.load') as loader:
            result=self.run_prediction(source='OpenAQ')
        loader.assert_not_called()
        self.assertIn('incompatible_temporal_source',result['reasons'])

    def test_unvalidated_release_never_predicts_operationally(self):
        result=self.run_prediction(mode='operational',now='2025-07-10T12:30:00Z')
        self.assertIn('independent_final_validation_pending',result['reasons'])
        self.assertNotIn('pm25_ug_m3',result)

    def test_quality_version_mismatch_abstains(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("UPDATE calidad_mediciones SET version_reglas='other'")
        self.assertIn('incompatible_quality_rules',self.run_prediction()['reasons'])

    def test_tampered_artifact_refused_before_deserialization(self):
        path=self.release/'2694071_1h'/'estimators.joblib'
        with path.open('ab') as target:target.write(b'changed')
        with patch('forecasting.inference.joblib.load') as loader:
            result=self.run_prediction()
        loader.assert_not_called()
        self.assertEqual(result['status'],'abstained')

    def test_emission_before_training_or_in_future_is_refused(self):
        self.assertIn('model_was_not_available_at_requested_emission',self.run_prediction('2025-06-01T00:00:00Z')['reasons'])
        self.assertEqual(self.run_prediction('2027-01-01T00:00:00Z')['status'],'abstained')

    def test_reserved_final_test_cannot_be_claimed_before_observations(self):
        with patch('forecasting.final_test.joblib.load') as loader:
            result=evaluate_reserved(self.release,self.db,now='2026-10-17T00:00:00Z')
        loader.assert_not_called()
        self.assertEqual(result['status'],'pending_observations')
        self.assertEqual(result['results'],[])
        self.assertFalse(result['operational_validation'])

    def test_closed_but_empty_holdout_is_still_pending(self):
        with patch('forecasting.final_test.joblib.load') as loader:
            result=evaluate_reserved(self.release,self.db,now='2027-01-01T00:00:00Z')
        loader.assert_not_called()
        self.assertEqual(result['status'],'pending_observations')
        self.assertEqual(result['results'][0]['test_samples'],0)

    def test_final_test_cannot_be_consumed_twice(self):
        (self.release/'final_test_consumed.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'ya se consumió'):
            evaluate_reserved(self.release,self.db)

    def test_closed_and_complete_holdout_compares_frozen_method(self):
        plan_path=self.release/'holdout_plan.json'
        plan=json.loads(plan_path.read_text(encoding='utf8'))
        plan.update({'issue_start':'2025-07-10T00:00:00Z','issue_end_exclusive':'2025-07-12T00:00:00Z',
                     'frozen_at':'2025-07-02T00:00:00Z','minimum_samples_per_station_horizon':10})
        plan_path.write_text(json.dumps(plan),encoding='utf8')
        metadata_path=self.release/'2694071_1h'/'metadata.json'
        meta=json.loads(metadata_path.read_text(encoding='utf8'))
        meta['holdout_plan_sha256']=sha(plan_path)
        metadata_path.write_text(json.dumps(meta),encoding='utf8')
        registry_path=self.release/'registry.json'
        registry=json.loads(registry_path.read_text(encoding='utf8'))
        registry['holdout_plan_sha256']=sha(plan_path)
        registry['entries'][0]['metadata_sha256']=sha(metadata_path)
        registry_path.write_text(json.dumps(registry),encoding='utf8')
        result=evaluate_reserved(self.release,self.db,now='2025-07-15T00:00:00Z')
        self.assertEqual(result['status'],'independent_retrospective_test_evaluated')
        self.assertEqual(result['results'][0]['test_samples'],48)
        self.assertFalse(result['selection_changed'])
        self.assertFalse(result['operational_validation'])


if __name__=='__main__':unittest.main()
