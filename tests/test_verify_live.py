"""La verificacion en vivo distingue respuestas API de filas anteriores de SQLite."""
import unittest
from datetime import datetime, timedelta, timezone

from data_ingestion.verify_live import inspect_received
from data_ingestion.openaq_protocol import verify_location_sensor


class LiveVerificationTests(unittest.TestCase):
    def setUp(self):
        self.clock=datetime(2026,10,17,20,30,tzinfo=timezone.utc)
        self.end=self.clock.replace(minute=0)
        self.start=self.end-timedelta(hours=24)

    def hour(self,age=1,value=10):
        point=self.end-timedelta(hours=age)
        return {'value':value,'parameter':{'id':2,'name':'pm25','units':'µg/m³'},
                'period':{'label':'hour','interval':'01:00:00',
                          'datetimeFrom':{'utc':point.isoformat()},
                          'datetimeTo':{'utc':(point+timedelta(hours=1)).isoformat()}}}

    def inspect(self,rows):
        return inspect_received(rows,2694071,480392,self.start,self.end,self.clock)

    def test_empty_api_response_does_not_claim_freshness(self):
        result=self.inspect([])
        self.assertFalse(result['meets_two_hour_age_limit'])
        self.assertIsNone(result['latest_api_period_start_utc'])

    def test_age_uses_explicit_start_and_actual_clock(self):
        result=self.inspect([self.hour()])
        self.assertTrue(result['meets_two_hour_age_limit'])
        self.assertEqual(result['age_from_period_start_hours'],1.5)
        self.assertFalse(self.inspect([self.hour(age=2)])['meets_two_hour_age_limit'])

    def test_bad_unit_is_rejected_and_not_used_as_fresh_observation(self):
        row=self.hour();row['parameter']['units']='mg/m³'
        result=self.inspect([row])
        self.assertEqual(result['rejected'],1)
        self.assertFalse(result['meets_two_hour_age_limit'])

    def test_duplicate_periods_are_counted_once_by_quality(self):
        result=self.inspect([self.hour(),self.hour()])
        self.assertEqual(result['duplicate_periods'],1)
        self.assertEqual(result['incoming_window_quality']['evaluated'],1)

    def test_recent_does_not_imply_quality_passes(self):
        result=self.inspect([self.hour(value=-1)])
        self.assertTrue(result['meets_two_hour_age_limit'])
        self.assertFalse(result['latest_incoming_observation_passes_quality'])
        self.assertEqual(result['incoming_window_quality']['requires_review'],1)

    def test_outside_exclusive_end_is_not_accepted(self):
        result=self.inspect([self.hour(age=0)])
        self.assertEqual(result['outside_window'],1)
        self.assertFalse(result['meets_two_hour_age_limit'])

    def test_location_endpoint_must_explicitly_contain_sensor(self):
        sensor={'id':2694071,'parameter':{'id':2,'name':'pm25','units':'µg/m³'}}
        payload={'results':[{'id':480392,'sensors':[sensor]}]}
        self.assertEqual(verify_location_sensor(payload,2694071,480392),sensor)
        for bad in ({'results':[{'id':1,'sensors':[sensor]}]},
                    {'results':[{'id':480392,'sensors':[]}]},
                    {'results':payload['results']*2}):
            with self.assertRaises(ValueError):verify_location_sensor(bad,2694071,480392)


if __name__=='__main__':unittest.main()
