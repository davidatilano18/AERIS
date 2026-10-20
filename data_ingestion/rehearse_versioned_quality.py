"""Ensayo completo en base temporal; no ofrece modo de escritura original."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from . import operations as ops
from .audit_quality_rules import audit
from .controlled_run import CachedClient, compare_original, CriticalFailure, require
from .production_preflight import snapshot, sha, credential_scan
from .quality_versioned import verify_current, calculate, VERSION
from .openaq_protocol import verify_sensor
from .verify_live import ObservedClient


def dashboard_probe(db):
    import app as dashboard
    with patch.object(dashboard,'DB',db):
        rows,available=dashboard.read_measurements()
        client=dashboard.app.test_client()
        statuses={path:client.get(path).status_code for path in
                  ('/api/overview','/api/measurements?period=all','/api/export.csv?period=all','/health')}
    mapped={(r['fuente'],r['sensor_id'],r['fecha_utc']):tuple(r[k] for k in
            ('es_cero','es_extremo','salto_abrupto','requiere_revision','quality_evaluated')) for r in rows}
    return mapped,{'quality_available':available,'rows':len(rows),'http_statuses':statuses}


def main():
    root=ops.ROOT;source=root/'data/aeris_air_quality.db'
    holdout=root/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json'
    key=os.environ.get('OPENAQ_API_KEY','').strip()
    if not key:raise ValueError('Falta credencial local')
    identifier=ops.utcnow().strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=root/'reports'/('versioned_quality_rehearsal_'+identifier+'.json')
    evidence_dir=root/'data/sync_runtime/rehearsals'/identifier
    evidence_dir.mkdir(parents=True,exist_ok=False)
    before=snapshot(source);original_sha=sha(source);holdout_sha=sha(holdout);dashboard_sha=sha(root/'app.py')
    report={'schema':'aeris-versioned-quality-rehearsal-v1','mode':'temporary_database_only',
            'started_at_utc':ops.iso(ops.utcnow()),'original_database':str(source),
            'original_sha256_before':original_sha,'before':before,'status':'checking',
            'original_production_run_calls':0,'predictions_enabled':False,'scheduled_tasks_installed':False,
            'rule_audit':audit(source),'retained_evidence_directory':str(evidence_dir)}
    live=ObservedClient(key,Path(str(source)+'.sync.stop'));cache=CachedClient(live)
    real_store=ops.store_sensor
    try:
        require(before['integrity_check']==['ok'] and not before['foreign_key_violations'],'Integridad original incorrecta')
        with tempfile.TemporaryDirectory(prefix='aeris-versioned-qc-') as temp:
            target=Path(temp)/'rehearsal.db';baseline=Path(temp)/'baseline.db'
            require(target.resolve()!=source.resolve(),'El destino debe ser una copia distinta del original')
            with ops.exclusive_lock(Path(str(source)+'.sync.lock')):
                ops.copy_database(source,target);ops.copy_database(source,baseline)
                require(snapshot(target)==before and snapshot(baseline)==before,'Copia no coincide con original')
            old_dashboard,_=dashboard_probe(target)
            verify_sensor(cache.get('/sensors/2694071',{}),2694071)
            report['authentication']='accepted'
            def preserve_first(conn,*args,**kwargs):
                result=real_store(conn,*args,**kwargs)
                compare_original(conn,baseline)
                return result
            print('Ensayo con red: escritura exclusivamente en SQLite temporal.',flush=True)
            with patch.object(ops,'store_sensor',preserve_first):
                sync=ops.run(target,list(ops.ACTIVE),key=key,client=cache)
            report['synchronization_on_temporary_copy']=sync
            require(sync['status']=='success','Sincronizacion temporal parcial o fallida')
            report['first_copy_state']=snapshot(target)
            new_count=sum(r['new_measurements'] for r in sync['results'])
            with closing(sqlite3.connect(target)) as conn:
                report['original_rows']=compare_original(conn,baseline)
                with closing(sqlite3.connect(baseline.as_uri()+'?mode=ro',uri=True)) as old:
                    original_quality_rows=set(old.execute('SELECT * FROM calidad_mediciones'))
                seeded=set(conn.execute('''SELECT fuente,sensor_id,fecha_utc,contaminante,
                    es_cero,es_extremo,salto_abrupto,requiere_revision,version_reglas
                    FROM evaluaciones_calidad WHERE origen='original_snapshot' ''').fetchall())
                require(original_quality_rows==seeded,'No se conservaron todas las evaluaciones originales en el registro')
                report['original_assessments_archived_separately']=len(seeded)
                report['verified_current_assessments']={str(sid):verify_current(conn,sid) for sid in ops.ACTIVE}
                report['normalized_utc_duplicate_groups']=conn.execute('''SELECT COUNT(*) FROM
                    (SELECT fuente,sensor_id,julianday(fecha_utc),contaminante,COUNT(*) n
                     FROM mediciones GROUP BY 1,2,3,4 HAVING n>1)''').fetchone()[0]
                require(report['normalized_utc_duplicate_groups']==0,'Duplicados UTC en copia')
                report['pending_quality']=conn.execute('''SELECT COUNT(*) FROM mediciones LEFT JOIN calidad_mediciones
                    USING(fuente,sensor_id,fecha_utc,contaminante) WHERE calidad_mediciones.sensor_id IS NULL''').fetchone()[0]
                require(report['pending_quality']==0,'Mediciones sin evaluacion inicial')
                report['ledger_rows_before_replay']=conn.execute('SELECT COUNT(*) FROM evaluaciones_calidad').fetchone()[0]
                report['quality_version_distribution']=[dict(zip(('source','version','rows'),r)) for r in
                    conn.execute('SELECT fuente,version_reglas,COUNT(*) FROM calidad_mediciones GROUP BY 1,2')]
                report['four_cases_separate_evaluations']=[]
                for case in report['rule_audit']['v2_differences']:
                    rows=conn.execute('''SELECT version_reglas,es_cero,es_extremo,salto_abrupto,requiere_revision,origen
                        FROM evaluaciones_calidad WHERE fuente='OpenAQ' AND sensor_id=? AND fecha_utc=? ORDER BY id''',
                        (case['sensor_id'],case['timestamp_utc'])).fetchall()
                    report['four_cases_separate_evaluations'].append({'sensor_id':case['sensor_id'],
                        'timestamp_utc':case['timestamp_utc'],'assessments':rows})
                # Repetir exactamente las respuestas reales ya recibidas, sin red.
                cache.frozen=True;run_id=uuid.uuid4().hex;replay=[]
                with conn:
                    conn.execute('INSERT INTO ingestas VALUES (?,?,NULL,?,NULL)',(run_id,ops.iso(ops.utcnow()),'running'))
                    for result in sync['results']:
                        sid=result['sensor_id'];location=ops.load_catalog()[sid]['location_id']
                        records,receipts,stats=ops.collect(cache,sid,location,ops.parse_utc(result['window_from_utc']),
                            ops.parse_utc(result['window_to_utc_exclusive']),100,50,Path(temp)/'sync_runtime/raw',key)
                        changes=preserve_first(conn,run_id,sid,records,receipts)
                        require(changes['new_measurements']==0 and changes['conflicting_candidates']==0,'Replay no idempotente')
                        require(changes['versioned_quality']['new_versioned_assessments']==0,'Replay duplico evaluaciones')
                        replay.append({'sensor_id':sid,**changes})
                    conn.execute('UPDATE ingestas SET fin_utc=?,estado=? WHERE id=?',(ops.iso(ops.utcnow()),'success',run_id))
                report['replay_without_network']=replay
                report['ledger_rows_after_replay']=conn.execute('SELECT COUNT(*) FROM evaluaciones_calidad').fetchone()[0]
                require(report['ledger_rows_before_replay']==report['ledger_rows_after_replay'],'Cambio el numero de evaluaciones en replay')
                report['immutable_triggers']=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")]
                report['response_receipts_verified']=0
                for digest,path in conn.execute('SELECT sha256,ruta_local FROM respuestas_api'):
                    require(sha(path)==digest,'Evidencia modificada')
                    report['response_receipts_verified']+=1
            report['after_copy']=snapshot(target)
            require(report['after_copy']['integrity_check']==['ok'] and not report['after_copy']['foreign_key_violations'],'Integridad de copia incorrecta')
            require(report['after_copy']['tables']['mediciones']['rows']==before['tables']['mediciones']['rows']+new_count,'Conteo de mediciones no coincide')
            require(report['after_copy']['tables']['calidad_mediciones']['rows']==before['tables']['calidad_mediciones']['rows']+new_count,'Conteo de calidad no coincide')
            for table in ('archivos_origen','observaciones_archivo','estaciones'):
                require(report['after_copy']['tables'][table]==before['tables'][table],'Cambio tabla protegida '+table)
            after_dashboard,report['dashboard']=dashboard_probe(target)
            require(all(after_dashboard.get(k)==v for k,v in old_dashboard.items()),'Cambio la calidad original visible en dashboard')
            require(all(report['dashboard']['http_statuses'][p]==200 for p in
                ('/api/overview','/api/measurements?period=all','/api/export.csv?period=all')),'Fallo un endpoint de datos')
            report['dashboard']['original_serialized_flags_preserved']=True
            report['dashboard']['join_returns_one_row_per_measurement']=len(after_dashboard)==before['tables']['mediciones']['rows']+new_count
            report['new_on_copy']=new_count
            require(sha(source)==original_sha and snapshot(source)==before,'Cambio la base original')
            report['status']='verified_temporary_rehearsal'
    except (CriticalFailure,Exception) as exc:
        report['status']='stopped_failure'
        report['error']={'type':type(exc).__name__,'detail':str(exc).replace(key,'[redacted]')}
    finally:
        # Evidencia persistente incluso si el ensayo temporal falla.
        report['retained_api_responses']=[]
        for (path,params),payload in cache.payloads.items():
            raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')
            if key.encode() in raw:continue
            digest=hashlib.sha256(raw).hexdigest();destination=evidence_dir/(digest+'.json')
            if not destination.exists():destination.write_bytes(raw)
            report['retained_api_responses'].append({'path':path,'params':json.loads(params),
                'sha256':digest,'local_path':str(destination)})
        report['original_sha256_after']=sha(source)
        report['original_unchanged']=report['original_sha256_after']==original_sha and snapshot(source)==before
        report['reserved_holdout_unchanged']=sha(holdout)==holdout_sha
        report['dashboard_file_unchanged']=sha(root/'app.py')==dashboard_sha
    print('Ejecutando pruebas automatizadas sin red...',flush=True)
    stream=io.StringIO()
    with redirect_stdout(stream),redirect_stderr(stream):
        result=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover(str(root/'tests')))
    report['tests']={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                     'successful':result.wasSuccessful(),'network_used':False}
    if not result.wasSuccessful():report['tests']['details']=stream.getvalue().replace(key,'[redacted]')
    report['credential_scan']=credential_scan(root,key)
    report['finished_at_utc']=ops.iso(ops.utcnow())
    if not all((result.wasSuccessful(),report['original_unchanged'],report['reserved_holdout_unchanged'],
                report['dashboard_file_unchanged'],not report['credential_scan']['exact_credential_matches'])):
        report['status']='stopped_failure'
    serialized=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).replace(key,'[redacted]')
    with output.open('x',encoding='utf8') as out:out.write(serialized)
    print('REPORT:',output,'STATUS:',report['status'],'NEW_ON_COPY:',report.get('new_on_copy'),'TESTS:',report['tests'])
    return int(report['status']!='verified_temporary_rehearsal')


if __name__=='__main__':raise SystemExit(main())
