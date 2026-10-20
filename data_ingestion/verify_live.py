"""Verificacion autenticada acotada; sincroniza exclusivamente una copia temporal."""
import hashlib
import io
import json
import os
import sqlite3
import unittest
from collections import Counter
from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import timedelta
from pathlib import Path

from . import operations as ops
from .openaq_protocol import parse_verified_hour, parse_utc, verify_sensor
from .quality import refresh_quality


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ObservedClient(ops.ApiClient):
    def __init__(self,key,stop_path):
        super().__init__(key,stop_path)
        self.requests=[]
        self.rows={}

    def get(self,path,params):
        payload=super().get(path,params)
        rows=payload.get('results') if isinstance(payload,dict) else None
        self.requests.append({'path':path,'params':params,'result_count':len(rows) if isinstance(rows,list) else None})
        if path.endswith('/hours') and isinstance(rows,list):
            self.rows.setdefault(int(path.split('/')[2]),[]).extend(rows)
        print('OpenAQ:',path,'page='+str(params.get('page',1)), 'rows='+str(len(rows) if isinstance(rows,list) else 'invalid'),flush=True)
        return payload


def inspect_received(rows,sid,location,start,end,clock):
    valid=[];errors=Counter();outside=0
    for row in rows:
        try:
            parsed=parse_verified_hour(row,sid,location)
            if not start<=parse_utc(parsed['from_utc'])<end:outside+=1;continue
            valid.append(parsed)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            errors[type(exc).__name__]+=1
    counts=Counter(r['from_utc'] for r in valid)
    latest=max((parse_utc(r['from_utc']) for r in valid),default=None)
    age=(clock-latest).total_seconds()/3600 if latest else None
    with closing(sqlite3.connect(':memory:')) as conn:
        ops.ensure_db(conn)
        conn.executemany("INSERT OR IGNORE INTO mediciones VALUES ('OpenAQ',?,?,'pm25',?,'µg/m³')",
                         [(sid,r['from_utc'],r['value']) for r in valid])
        refresh_quality(conn,sid)
        quality=conn.execute('SELECT COUNT(*),COALESCE(SUM(requiere_revision),0),COALESCE(SUM(es_cero),0),COALESCE(SUM(es_extremo),0),COALESCE(SUM(salto_abrupto),0) FROM calidad_mediciones').fetchone()
        latest_review=conn.execute('SELECT requiere_revision FROM calidad_mediciones WHERE fecha_utc=?',
                                  (ops.iso(latest),)).fetchone() if latest else None
    return {'sensor_id':sid,'location_id':location,'received':len(rows),'verified_in_window':len(valid),
        'rejected':sum(errors.values()),'rejection_types':dict(errors),'outside_window':outside,
        'duplicate_periods':sum(n-1 for n in counts.values()),
        'units_verified':'µg/m³' if valid else None,'utc_and_one_hour_periods_verified':bool(valid),
        'latest_api_period_start_utc':ops.iso(latest) if latest else None,
        'latest_api_period_end_utc':ops.iso(latest+timedelta(hours=1)) if latest else None,
        'age_from_period_start_hours':age,'meets_two_hour_age_limit':age is not None and 0<=age<=2,
        'latest_incoming_observation_passes_quality':latest_review is not None and latest_review[0]==0,
        'incoming_window_quality':dict(zip(('evaluated','requires_review','zeros','extreme','abrupt_jump'),quality)),
        'freshness_scope':'verified API response only; never substituted with pre-existing SQLite rows',
        'quality_scope':'incoming window only; synchronization also evaluates original plus incoming on temporary copy'}


def main():
    root=ops.ROOT;db=root/'data/aeris_air_quality.db'
    holdout=root/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json'
    before=sha(db);holdout_before=sha(holdout)
    clock=ops.utcnow();end=clock.replace(minute=0,second=0,microsecond=0);start=end-timedelta(hours=24)
    key=os.environ.get('OPENAQ_API_KEY','').strip()
    if not key:raise ValueError('Falta credencial local')
    client=ObservedClient(key,Path(str(db)+'.sync.stop'))
    report={'schema':'aeris-live-api-verification-v2','started_at_utc':ops.iso(clock),
            'sqlite_sha256_before':before,'holdout_sha256_before':holdout_before,
            'query_from_utc':ops.iso(start),'query_to_utc_exclusive':ops.iso(end),
            'authentication':{'status':'not_checked'},'synchronization':None,
            'api_observations':[],'scheduled_tasks_installed':False,'predictions_enabled':False}
    try:
        verify_sensor(client.get('/sensors/2694071',{}),2694071)
        report['authentication']={'status':'accepted','endpoint':'https://api.openaq.org/v3/sensors/2694071',
                                  'sensor_metadata_verified':True}
        report['synchronization']=ops.run(db,list(ops.ACTIVE),dry_run=True,start=start,end=end,
                                          limit=10,max_pages=6,key=key,client=client)
        inspected_at=ops.utcnow();catalog=ops.load_catalog()
        report['api_observations']=[inspect_received(client.rows.get(sid,[]),sid,catalog[sid]['location_id'],
                                                   start,end,inspected_at) for sid in ops.ACTIVE]
    except (OSError,RuntimeError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
        detail=str(exc).replace(key,'[redacted]')
        report['error']={'type':type(exc).__name__,'detail':detail}
        if report['authentication']['status']=='not_checked':
            report['authentication']={'status':'failed','detail':detail}
    finally:
        report['requests_completed']=client.requests
        report['sqlite_sha256_after']=sha(db)
        report['holdout_sha256_after']=sha(holdout)
        report['original_database_unchanged']=before==report['sqlite_sha256_after']
        report['reserved_holdout_unchanged']=holdout_before==report['holdout_sha256_after']
    print('Ejecutando pruebas automatizadas sin red...',flush=True)
    stream=io.StringIO()
    with redirect_stdout(stream),redirect_stderr(stream):
        tests=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover(str(root/'tests')))
    report['tests']={'tests_run':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors),
                     'successful':tests.wasSuccessful(),'network_used':False}
    if not tests.wasSuccessful():
        report['tests']['failure_details']=[{'test':str(t),'traceback':detail.replace(key,'[redacted]')}
                                            for t,detail in tests.failures+tests.errors]
    report['finished_at_utc']=ops.iso(ops.utcnow())
    report['original_database_unchanged'] &= before==sha(db)
    report['reserved_holdout_unchanged'] &= holdout_before==sha(holdout)
    output=root/'reports'/('live_api_verification_'+ops.utcnow().strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x',encoding='utf8') as handle:json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
    print('REPORTE:',output)
    print('AUTH:',report['authentication']['status'],'TESTS:',report['tests'],
          'ORIGINAL_UNCHANGED:',report['original_database_unchanged'])
    for item in report['api_observations']:
        print(json.dumps(item,ensure_ascii=False))
    return int('error' in report or not tests.wasSuccessful() or not report['original_database_unchanged']
               or not report['reserved_holdout_unchanged']
               or report['synchronization'] is None or report['synchronization']['status']!='success')


if __name__=='__main__':raise SystemExit(main())
