"""Matched comparisons use isolated fixtures, never invented live observations."""
import copy
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import test_dashboard_v2 as legacy
from aeris_web.comparisons import compare_windows,read_comparison,rounded

END=datetime(2026,10,18,4,tzinfo=timezone.utc)


def observations(before=10,after=20):
    return [{'source':'OpenAQ','sensor_id':legacy.SID,'unit':'µg/m³',
             'timestamp_utc':(END-timedelta(hours=48-i)).isoformat(),
             'value':before if i<24 else after,'quality_version':'aeris_qc_v1',
             'review':0,'extreme':0,'jump':0} for i in range(48)]


class MatchedComparisonTests(unittest.TestCase):
    def compare(self,rows,**kwargs):
        return compare_windows(rows,kwargs.get('end',END),kwargs.get('now',END+timedelta(minutes=30)),
                               kwargs.get('source','OpenAQ'),legacy.SID)

    def test_up_with_same_24_hours_and_exact_window_definitions(self):
        result=self.compare(observations())
        self.assertEqual(result['status'],'compared')
        self.assertEqual((result['previous_mean'],result['current_mean'],result['difference']),(10,20,10))
        self.assertEqual(result['direction'],'up')
        self.assertEqual(result['matched_hours'],24)
        self.assertEqual(result['current']['from_utc'],'2026-10-17T04:00:00Z')
        self.assertEqual(result['previous']['to_exclusive_utc'],result['current']['from_utc'])
        self.assertIn('no determina un cambio de riesgo',result['summary'])

    def test_down_is_descriptive_not_health_claim(self):
        r=self.compare(observations(20,10))
        self.assertEqual(r['direction'],'down');self.assertIn('bajó',r['summary'])

    def test_similar_only_when_displayed_means_match(self):
        r=self.compare(observations(10.001,10.004))
        self.assertEqual(r['direction'],'similar')
        self.assertIn('redondear a dos decimales',r['summary'])
        self.assertNotEqual(r['difference'],0)
        self.assertEqual(rounded(10.005),'10.01')

    def test_zero_is_observed_and_no_percentage_division(self):
        r=self.compare(observations(0,0))
        self.assertEqual(r['current_mean'],0)
        self.assertEqual(r['matched_hours'],24)
        self.assertEqual(r['direction'],'similar')
        self.assertNotIn('percentage_change',r)

    def test_rounding_at_half_does_not_drift_after_averaging_repeated_values(self):
        r=self.compare(observations(10.004,10.005))
        self.assertEqual((r['previous_display'],r['current_display']),('10.00','10.01'))
        self.assertEqual(r['direction'],'up')

    def test_means_use_same_pairs_not_each_windows_different_sample(self):
        rows=observations()
        rows[23]['value']=1000;rows[25]['value']=2000
        rows.pop(1);rows.pop(-1)  # both unmatched high values must be discarded
        r=self.compare(rows)
        self.assertEqual(r['matched_hours'],22)
        self.assertEqual((r['previous_mean'],r['current_mean']),(10,20))
        self.assertEqual(r['previous']['received_hours'],23)
        self.assertEqual(r['current']['received_hours'],23)

    def test_18_distributed_pairs_suffice_and_missing_not_imputed(self):
        missing={0,4,8,12,16,20}
        rows=[r for i,r in enumerate(observations()) if i%24 not in missing]
        r=self.compare(rows)
        self.assertEqual(r['status'],'compared')
        self.assertEqual(r['matched_hours'],18)
        self.assertEqual(sum(p['previous_value'] is None for p in r['pairs']),6)

    def test_insufficient_coverage_suppresses_all_means_and_direction(self):
        r=self.compare(observations()[8:])
        self.assertIn('insufficient_coverage',r['reasons'])
        self.assertIsNone(r['difference']);self.assertIsNone(r['direction'])
        self.assertIsNone(r['previous_mean']);self.assertIsNone(r['current_mean'])

    def test_individual_coverage_does_not_guarantee_paired_coverage(self):
        rows=[r for i,r in enumerate(observations()) if not (i<6 or 30<=i<36)]
        r=self.compare(rows)
        self.assertEqual(r['previous']['usable_hours'],18)
        self.assertEqual(r['current']['usable_hours'],18)
        self.assertEqual(r['matched_hours'],12)
        self.assertIn('insufficient_matched_hours',r['reasons'])

    def test_missing_entire_six_hour_block_is_not_representative(self):
        rows=[r for i,r in enumerate(observations()) if i%24>=6]
        r=self.compare(rows)
        self.assertEqual(r['matched_hours'],18)
        self.assertIn('unbalanced_hours',r['reasons'])
        self.assertEqual(r['status'],'abstained')

    def test_extreme_flag_excludes_pair_without_overwriting_original(self):
        rows=observations();rows[0].update(value=9999,extreme=1)
        original=copy.deepcopy(rows)
        r=self.compare(rows)
        self.assertEqual(r['matched_hours'],23)
        self.assertEqual(r['previous_mean'],10)
        self.assertEqual(r['pairs'][0]['previous_value'],9999)
        self.assertFalse(r['pairs'][0]['included'])
        self.assertEqual(rows,original)

    def test_negative_pending_jump_and_review_are_excluded(self):
        for change in [{'value':-1},{'quality_version':None},{'quality_version':'unknown-version'},
                       {'jump':1},{'review':1},{'review':None}]:
            rows=observations();rows[0].update(change)
            self.assertEqual(self.compare(rows)['matched_hours'],23)

    def test_mixed_quality_versions_fail_even_when_pairs_share_versions(self):
        rows=observations();rows[0]['quality_version']=rows[24]['quality_version']='aeris_qc_v2'
        r=self.compare(rows)
        self.assertEqual(r['matched_hours'],24)
        self.assertIn('mixed_quality_versions',r['reasons'])

    def test_no_observations_is_explicit(self):
        r=self.compare([])
        self.assertIn('no_observations',r['reasons'])
        self.assertEqual(r['current']['received_hours'],0)

    def test_future_or_open_endpoints_are_rejected(self):
        for end in [END+timedelta(hours=1),END+timedelta(minutes=15),END.replace(tzinfo=None)]:
            with self.assertRaises(ValueError):self.compare([],end=end)

    def test_wrong_source_unit_sensor_and_nonfinite_values_fail_closed(self):
        for changes in [{'source':'OpenAQ-Archive'},{'unit':'ppm'},{'sensor_id':99999},{'value':float('inf')}]:
            rows=observations();rows[0].update(changes)
            with self.assertRaises(RuntimeError):self.compare(rows)

    def test_duplicate_equivalent_instants_are_rejected(self):
        rows=observations();rows.append({**rows[0],'timestamp_utc':rows[0]['timestamp_utc'].replace('+00:00','Z')})
        with self.assertRaises(RuntimeError):self.compare(rows)

    def test_local_clock_change_abstains_instead_of_mismatching_hours(self):
        end=datetime(2021,10,31,12,tzinfo=timezone.utc)
        rows=observations()
        for i,row in enumerate(rows):row['timestamp_utc']=(end-timedelta(hours=48-i)).isoformat()
        r=self.compare(rows,end=end,now=end+timedelta(hours=1))
        self.assertIn('local_time_change',r['reasons'])


class ComparisonEndpointTests(unittest.TestCase):
    setUp=legacy.DashboardV2Tests.setUp
    tearDown=legacy.DashboardV2Tests.tearDown

    def get(self,query='?station=1352676'):
        with patch('aeris_web.comparisons.utc_now',return_value=END+timedelta(minutes=30)):
            return self.client.get('/api/v2/comparison'+query)

    def test_endpoint_is_read_only_and_omits_incomplete_hour(self):
        before=self.db.read_bytes();r=self.get()
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(r.json['current']['received_hours'],3)
        self.assertFalse(any(p['current_value']==999 for p in r.json['pairs']))
        self.assertEqual(before,self.db.read_bytes())

    def test_strict_filters_and_no_write_methods(self):
        for q in ['', '?station=all','?station=99999','?station=1352676&anchor=tomorrow',
                  '?station=1352676&source=both','?station=1352676&end=2027-01-01']:
            self.assertEqual(self.get(q).status_code,400)
        self.assertEqual(self.client.post('/api/v2/comparison').status_code,405)

    def test_source_switch_and_latest_anchor_never_substitute_api(self):
        r=self.get('?station=1352676&source=OpenAQ-Archive&anchor=latest').json
        self.assertEqual(r['source'],'OpenAQ-Archive')
        self.assertEqual(r['current']['received_hours'],1)
        self.assertTrue(any(p['current_value']==9 for p in r['pairs']))
        self.assertFalse(any(p['current_value']==20 for p in r['pairs']))

    def test_historical_latest_anchor_is_explicit_and_excludes_today(self):
        r=self.get('?station=1352681&source=OpenAQ-Archive&anchor=latest').json
        self.assertEqual(r['status'],'abstained')
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352686,'2021-09-23T10:00:00Z','pm25',9.37,'µg/m³')")
        r=self.get('?station=1352686&anchor=latest').json
        self.assertEqual(r['current']['to_exclusive_utc'],'2021-09-23T11:00:00Z')
        self.assertIn('historial antiguo',r['anchor_note'])

    def test_routes_and_accessible_markup_are_preserved(self):
        for route in ['/','/v2','/v2/datos']:
            self.assertEqual(self.client.get(route).status_code,200)
        page=self.client.get('/v2').text
        for text in ['for="comparisonAnchor"','aria-describedby="comparisonHelp"','aria-atomic="true"',
                     'id="contenido" tabindex="-1"','id="comparisonRows"','v2/css/accessibility.css']:
            self.assertIn(text,page)

    def test_incompatible_units_outside_public_filter_fail_comparison(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            c.execute("UPDATE mediciones SET unidad='ppm' WHERE sensor_id=1352676")
        self.assertEqual(self.get().status_code,503)
