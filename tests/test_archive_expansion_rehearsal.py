"""Artificial protocol fixtures only; never final observations or model inputs."""
import copy
import importlib.util
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('archive_rehearsal',ROOT/'scripts/rehearse_archive_expansion.py')
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


class ArchiveExpansionTests(unittest.TestCase):
    def setUp(self):
        self.row={'location_id':'235225','sensors_id':'1352676','parameter':'pm25','units':'µg/m³',
                  'value':'10','datetime':'2025-05-01T01:00:00-06:00',
                  'lat':'20.552563888889','lon':'-100.44580555556'}
        self.metadata={'id':235225,'timezone':'America/Mexico_City',
                       'coordinates':{'latitude':20.552563888889,'longitude':-100.44580555556},
                       'sensors':[{'id':1352676,'parameter':{'name':'pm25','units':'µg/m³'}}]}
        self.catalog={'location_id':235225,'lat':20.552563888889,'lon':-100.44580555556}

    def validate(self):
        return rehearsal.validate_row(self.row,235225,1352676,self.metadata,self.catalog)

    def test_preserves_original_identity_and_unknown_interval(self):
        result=self.validate()
        self.assertEqual(result['utc'],'2025-05-01T07:00:00Z')
        self.assertEqual(result['original']['datetime'],self.row['datetime'])
        self.assertEqual(result['source'],'OpenAQ-Archive')
        self.assertIsNone(result['interval_end_utc'])
        self.assertEqual(result['aggregation'],'not_declared_in_archive')

    def test_identity_unit_and_coordinate_mismatch_stop(self):
        for field,value in [('sensors_id','999'),('location_id','999'),('parameter','pm10'),
                            ('units','ppm'),('lat','20.7')]:
            with self.subTest(field=field):
                original=self.row.copy();self.row[field]=value
                with self.assertRaises(ValueError):self.validate()
                self.row=original

    def test_unknown_offset_and_non_hourly_dates_rejected(self):
        for time in ('2025-05-01T01:00:00','2025-05-01T01:00:00-05:00',
                     '2025-05-01T01:30:00-06:00','2026-10-19T00:00:00Z'):
            with self.subTest(time=time):
                self.row['datetime']=time
                with self.assertRaises(ValueError):self.validate()

    def test_non_finite_negative_stop_but_observed_zero_and_extreme_retained(self):
        for value in ('nan','inf','-1'):
            self.row['value']=value
            with self.assertRaises(ValueError):self.validate()
        for value in ('0','150'):
            self.row['value']=value
            self.assertEqual(self.validate()['value'],float(value))

    def test_production_destination_and_nonexistent_copy_rejected(self):
        with self.assertRaisesRegex(ValueError,'isolated copy'):
            rehearsal.isolated_import('unused',rehearsal.PRODUCTION,ROOT/'reports')
        with self.assertRaisesRegex(ValueError,'isolated copy'):
            rehearsal.isolated_import('unused',ROOT/'reports/does_not_exist.db',ROOT/'reports')

    def test_comparison_detects_value_changes_not_only_counts(self):
        initial={'tables':{'mediciones':Counter({'old-key-old-value':1})},'integrity':'ok','fk':[],'schema':[]}
        after=copy.deepcopy(initial);after['tables']['mediciones']=Counter({'old-key-new-value':1})
        with self.assertRaisesRegex(ValueError,'preservation'):rehearsal.require_preserved(initial,after)

    def test_additive_rows_allowed_but_integrity_and_schema_changes_fail(self):
        initial={'tables':{'mediciones':Counter({'old':1})},'integrity':'ok','fk':[],'schema':[]}
        after=copy.deepcopy(initial);after['tables']['mediciones']['new']=1
        self.assertEqual(rehearsal.require_preserved(initial,after)['mediciones']['missing_or_changed'],0)
        for field,value in [('integrity','corrupt'),('fk',[['broken']]),('schema',['changed'])]:
            invalid=copy.deepcopy(after);invalid[field]=value
            with self.assertRaises(ValueError):rehearsal.require_preserved(initial,invalid)


if __name__ == '__main__':unittest.main()
