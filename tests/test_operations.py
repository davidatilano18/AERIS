"""Fixtures solo para pruebas de protocolo; nunca se incorporan a datos reales."""
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from data_ingestion import operations as ops
from data_ingestion.openaq_protocol import parse_verified_hour,comparable,verify_sensor

SID=1352676
LOC=235225
PARAM={'id':2,'name':'pm25','units':'µg/m³'}
START=datetime(2020,1,1,tzinfo=timezone.utc)
END=START+timedelta(days=1)


def metadata():return {'results':[{'id':SID,'parameter':PARAM}]}


def location_metadata():return {'results':[{'id':LOC,'sensors':metadata()['results']}]}


def hour(stamp='2020-01-01T00:00:00Z',value=10):
    point=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    return {'sensor_id':SID,'location_id':LOC,'parameter':dict(PARAM),'value':value,
            'period':{'label':'hour','interval':'01:00:00','datetimeFrom':{'utc':stamp},
                      'datetimeTo':{'utc':ops.iso(point+timedelta(hours=1))}}}


class FakeClient:
    def __init__(self,rows=None,fail=False):self.rows=rows or [];self.fail=fail;self.calls=[]
    def get(self,path,params):
        self.calls.append((path,params))
        if self.fail:raise RuntimeError('offline_test_failure')
        if '/locations/' in path:return location_metadata()
        offset=(params['page']-1)*params['limit']
        return {'results':self.rows[offset:offset+params['limit']]}


class ProtocolTests(unittest.TestCase):
    def test_requires_matching_utc_local_instants(self):
        row=hour();row['period']['datetimeFrom']['local']='2019-12-31T18:00:00-06:00'
        self.assertEqual(parse_verified_hour(row,SID,LOC)['from_utc'],ops.iso(START))
        row['period']['datetimeFrom']['local']='2019-12-31T19:00:00-06:00'
        with self.assertRaises(ValueError):parse_verified_hour(row,SID,LOC)

    def test_rejects_missing_period_wrong_id_unit_parameter_and_nonfinite(self):
        variants=[]
        for key,value in [('sensor_id',1),('location_id',1),('value',float('nan')),('value',True),('period',{})]:
            row=hour();row[key]=value;variants.append(row)
        for key,value in [('units','mg/m³'),('id',1),('name','pm10')]:
            row=hour();row['parameter'][key]=value;variants.append(row)
        row=hour();row['period']['datetimeTo']['utc']='2020-01-01T02:00:00Z';variants.append(row)
        row=hour();row['period']['datetimeFrom']['utc']='2020-01-01T00:00:00';variants.append(row)
        for row in variants:
            with self.subTest(row=row),self.assertRaises((ValueError,TypeError)):parse_verified_hour(row,SID,LOC)

    def test_metadata_must_identify_sensor_uniquely(self):
        for payload in ({},{'results':[]},{'results':metadata()['results']*2}):
            with self.assertRaises(ValueError):verify_sensor(payload,SID)

    def test_no_cross_source_equivalence_without_both_periods(self):
        verified=parse_verified_hour(hour(),SID,LOC)
        self.assertTrue(comparable(verified,dict(verified))[0])
        equivalent=dict(verified,from_utc='2020-01-01T00:00:00+00:00')
        self.assertTrue(comparable(verified,equivalent)[0])
        archive={'sensor_id':SID,'location_id':LOC,'datetime':ops.iso(START),'value':10}
        self.assertFalse(comparable(verified,archive)[0])
        shifted=dict(verified,from_utc='2020-01-01T01:00:00Z',to_utc='2020-01-01T02:00:00Z')
        self.assertFalse(comparable(verified,shifted)[0])


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'test.db'
        with closing(sqlite3.connect(self.db)) as conn,conn:ops.ensure_operations(conn)
    def tearDown(self):self.temp.cleanup()
    def query(self,sql):
        with closing(sqlite3.connect(self.db)) as conn:return conn.execute(sql).fetchall()
    def run_sync(self,rows=None,**kwargs):
        options=dict(start=START,end=END,key='fixture-key',client=FakeClient(rows))
        options.update(kwargs)
        return ops.run(self.db,[SID],**options)

    def test_insert_idempotence_append_only_conflict_and_backup(self):
        self.assertEqual(self.run_sync([hour()])['results'][0]['new_measurements'],1)
        self.assertEqual(self.run_sync([hour()])['results'][0]['identical'],1)
        result=self.run_sync([hour(value=99)])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['results'][0]['conflicting_candidates'],1)
        self.assertEqual(self.query('SELECT valor FROM mediciones'),[(10.,)])
        self.assertEqual(self.query('SELECT valor_anterior,valor_nuevo FROM revisiones_mediciones'),[(10.,99.)])
        with closing(sqlite3.connect(result['backup'])) as backup:
            self.assertEqual(backup.execute('SELECT valor FROM mediciones').fetchall(),[(10.,)])
        self.assertEqual(len(list((self.root/'backups').glob('*.db'))),3)

    def test_dry_run_keeps_original_bytes_and_no_backup(self):
        before=self.db.read_bytes();result=self.run_sync([hour()],dry_run=True)
        self.assertEqual(before,self.db.read_bytes())
        self.assertIsNone(result['backup'])
        self.assertEqual(result['results'][0]['new_measurements'],1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM mediciones'),[(0,)])

    def test_full_sync_preserves_v1_flags_and_evaluates_new_rows_v2(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',10,'µg/m³')")
            conn.execute("INSERT INTO calidad_mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',0,0,1,1,'aeris_qc_v1')")
        original=self.query('SELECT * FROM calidad_mediciones')[0]
        report=self.run_sync([hour(),hour('2020-01-01T01:00:00Z',11)])
        self.assertEqual(report['status'],'success')
        self.assertIn(original,self.query('SELECT * FROM calidad_mediciones'))
        self.assertEqual(self.query("SELECT version_reglas FROM calidad_mediciones WHERE fecha_utc LIKE '%01:00:00Z'"),[('aeris_qc_v2',)])
        self.assertEqual(self.query("SELECT salto_abrupto FROM evaluaciones_calidad WHERE fecha_utc LIKE '%00:00:00Z' AND version_reglas='aeris_qc_v2'"),[(0,)])

    def test_offline_dry_run_does_not_call_api_or_require_key(self):
        client=FakeClient(fail=True);before=self.db.read_bytes()
        result=self.run_sync(dry_run=True,offline=True,key=None,client=client)
        self.assertEqual(result['status'],'offline_audit');self.assertFalse(client.calls)
        self.assertEqual(before,self.db.read_bytes())
        with self.assertRaises(ValueError):self.run_sync(offline=True)

    def test_missing_key_fails_before_mutation(self):
        before=self.db.read_bytes()
        with self.assertRaises(ValueError):self.run_sync(key=None)
        self.assertEqual(before,self.db.read_bytes())
        self.assertFalse((self.root/'sync_runtime').exists())

    def test_failed_api_run_is_logged_and_does_not_advance_cursor(self):
        report=self.run_sync(client=FakeClient(fail=True))
        self.assertEqual(report['status'],'partial')
        self.assertEqual(self.query('SELECT * FROM sincronizacion_estado'),[])
        self.assertEqual(self.query('SELECT estado FROM ingestas'),[('partial',)])

    def test_pagination_cap_and_rejected_rows_do_not_advance_cursor(self):
        result=self.run_sync([hour()],limit=1,max_pages=1)
        self.assertFalse(result['results'][0]['complete'])
        self.assertEqual(self.query('SELECT * FROM sincronizacion_estado'),[])
        invalid=hour();invalid['parameter']['units']='unknown'
        result=self.run_sync([invalid])
        self.assertEqual(result['results'][0]['rejected'],1)
        self.assertEqual(self.query('SELECT * FROM sincronizacion_estado'),[])

    def test_backfill_does_not_regress_cursor(self):
        self.run_sync([hour()]);self.run_sync(start=START-timedelta(days=2),end=START-timedelta(days=1))
        self.assertEqual(self.query('SELECT consulta_completa_hasta_utc FROM sincronizacion_estado'),[(ops.iso(END),)])

    def test_incremental_cursor_progresses_with_overlap(self):
        self.run_sync([hour()])
        client=FakeClient()
        self.run_sync(start=None,end=None,client=client)
        params=client.calls[1][1]
        self.assertEqual(params['datetime_from'],ops.iso(END-timedelta(hours=48)))
        self.assertEqual(params['datetime_to'],ops.iso(END+timedelta(hours=120)))
        with self.assertRaises(ValueError):self.run_sync(chunk_hours=48)

    def test_same_instant_different_iso_not_duplicated(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00+00:00','pm25',10,'µg/m³')")
        result=self.run_sync([hour()])
        self.assertEqual(result['results'][0]['identical'],1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM mediciones'),[(1,)])

    def test_qc_refresh_records_successor_separately_without_overwriting_first(self):
        self.run_sync([hour(value=0),hour('2020-01-01T02:00:00Z',150)])
        self.run_sync([hour('2020-01-01T01:00:00Z',0)])
        self.assertEqual(self.query("SELECT salto_abrupto FROM calidad_mediciones WHERE fecha_utc LIKE '%02:00:00Z'"),[(0,)])
        self.assertEqual(self.query("SELECT salto_abrupto FROM evaluaciones_calidad WHERE fecha_utc LIKE '%02:00:00Z' ORDER BY id"),[(0,),(1,)])

    def test_conflicting_values_in_one_response_roll_back_whole_sensor(self):
        result=self.run_sync([hour(),hour(value=11)])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(self.query('SELECT COUNT(*) FROM mediciones'),[(0,)])

    def test_empty_response_reports_stale_missing_and_completes_request(self):
        result=self.run_sync()['results'][0]
        self.assertTrue(result['complete'])
        self.assertEqual(result['coverage_pct'],0)
        self.assertEqual(result['freshness_status'],'stale_or_missing')
        self.assertEqual(result['missing_hours'],24)

    def test_response_evidence_has_hash_url_without_key(self):
        self.run_sync([hour()])
        for digest,url,path in self.query('SELECT sha256,url,ruta_local FROM respuestas_api'):
            import hashlib
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),digest)
            self.assertNotIn('fixture-key',url+Path(path).read_text(encoding='utf8'))

    def test_stop_cancels_without_api_and_lock_excludes_other_run(self):
        stop=Path(str(self.db)+'.sync.stop');stop.touch()
        client=FakeClient();result=self.run_sync(client=client)
        self.assertEqual(result['status'],'cancelled');self.assertFalse(client.calls)
        stop.unlink()
        with ops.exclusive_lock(Path(str(self.db)+'.sync.lock')):
            with self.assertRaises(OSError):self.run_sync()

    def test_no_future_or_naive_query_dates(self):
        for end in (datetime.now(timezone.utc)+timedelta(days=2),datetime(2020,1,2)):
            with self.assertRaises(ValueError):self.run_sync(end=end)

    def test_explicit_window_cannot_be_silently_truncated(self):
        with self.assertRaises(ValueError):self.run_sync(end=START+timedelta(days=8))

    def test_backup_failure_prevents_any_mutation(self):
        before=self.db.read_bytes()
        with patch.object(ops,'copy_database',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.run_sync([hour()])
        self.assertEqual(before,self.db.read_bytes())
        self.assertEqual(self.query('SELECT COUNT(*) FROM ingestas'),[(0,)])

    def test_stop_after_fetch_does_not_commit_sensor(self):
        class StopClient(FakeClient):
            def get(inner,path,params):
                result=super(StopClient,inner).get(path,params)
                if '/hours' in path:Path(str(self.db)+'.sync.stop').touch()
                return result
        result=self.run_sync(client=StopClient([hour()]))
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(self.query('SELECT COUNT(*) FROM mediciones'),[(0,)])

    def test_api_retries_rate_limit_without_logging_error_body(self):
        from urllib.error import HTTPError
        from email.message import Message
        import io
        headers=Message();headers['Retry-After']='1'
        failure=HTTPError('https://api.openaq.org',429,'rate',headers,io.BytesIO(b'private-body'))
        client=ops.ApiClient('fixture-key',self.root/'stop')
        response=io.StringIO('{"results": []}')
        with patch.object(ops,'urlopen',side_effect=[failure,response]) as request,patch.object(client,'wait') as wait:
            self.assertEqual(client.get('/sensors/1352676/hours',{}),{'results':[]})
            self.assertEqual(request.call_count,2)
            self.assertTrue(any(call.args==(1.,) for call in wait.call_args_list))

    def test_api_auth_failure_does_not_leak_body(self):
        from urllib.error import HTTPError
        import io
        client=ops.ApiClient('fixture-key',self.root/'stop')
        error=HTTPError('https://api.openaq.org',401,'auth',{},io.BytesIO(b'fixture-key'))
        with patch.object(ops,'urlopen',side_effect=error),patch.object(client,'wait'):
            with self.assertRaisesRegex(RuntimeError,'^OpenAQ HTTP 401$'):client.get('/sensors/1352676/hours',{})

    def test_original_incompatible_unit_never_receives_verified_receipt(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,'2020-01-01T00:00:00Z','pm25',10,'unknown')")
        report=self.run_sync([hour()])
        self.assertEqual(report['status'],'partial')
        self.assertEqual(self.query('SELECT COUNT(*) FROM observaciones_api'),[(0,)])

    def test_existing_utc_duplicates_fail_without_replacement(self):
        with closing(sqlite3.connect(self.db)) as conn,conn:
            for stamp in ('2020-01-01T00:00:00Z','2020-01-01T00:00:00+00:00'):
                conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',1352676,?,'pm25',10,'µg/m³')",(stamp,))
        report=self.run_sync([hour()])
        self.assertEqual(report['status'],'partial')
        self.assertEqual(self.query('SELECT COUNT(*) FROM mediciones'),[(2,)])

    def archive_manifest(self):
        import gzip,hashlib
        target=self.root/'archive.csv.gz'
        with gzip.open(target,'wt',encoding='utf8') as handle:
            handle.write('location_id,sensors_id,datetime,parameter,units,value\n235225,1352676,2019-12-31T18:00:00-06:00,pm25,µg/m³,10\n')
        manifest=self.root/'manifest.json'
        manifest.write_text(json.dumps({'sensor_locations':{str(SID):LOC},'files':[
            {'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'url':'https://example.invalid/local-test'}]}),encoding='utf8')
        return manifest,target

    def test_archive_audit_checks_identity_timezone_and_never_infers_period(self):
        from data_ingestion.audit_compatibility import archive_inventory,audit
        manifest,_=self.archive_manifest();before=self.db.read_bytes()
        result=archive_inventory(manifest)
        self.assertEqual(result['identity_or_unit_mismatches'],0)
        self.assertEqual(result['timestamps_without_timezone'],0)
        self.assertEqual(result['first_reported_utc'],'2020-01-01T00:00:00+00:00')
        self.assertFalse(result['explicit_hourly_period_and_aggregation_available'])
        report=audit(self.db,manifest)
        self.assertEqual(report['verified_comparable_pairs'],0)
        self.assertFalse(report['automatic_source_substitution_allowed'])
        self.assertEqual(before,self.db.read_bytes())

    def test_archive_audit_rejects_changed_original_evidence(self):
        from data_ingestion.audit_compatibility import archive_inventory
        manifest,target=self.archive_manifest()
        with target.open('ab') as handle:handle.write(b'changed')
        with self.assertRaises(ValueError):archive_inventory(manifest)


if __name__=='__main__':unittest.main()
