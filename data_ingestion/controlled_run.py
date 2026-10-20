"""Una corrida autorizada, con respaldo verificado y guardas antes de cada commit."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing, nullcontext, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from . import operations as ops
from .production_preflight import sha, snapshot, credential_scan
from .quality_versioned import verify_current
from .openaq_protocol import verify_sensor
from .verify_live import ObservedClient

PLAN='production_preflight_20261018T001614Z_bc3e6b8a.json'


class CriticalFailure(BaseException):
    """No la captura el bucle de sensores: cancela sin intentar otra escritura."""


class CriticalConnection(sqlite3.Connection):
    """Errores SQLite y de commit abortan la corrida en vez de seguir otro sensor."""
    def execute(self,*args,**kwargs):
        try:return super().execute(*args,**kwargs)
        except sqlite3.Error as exc:raise CriticalFailure('SQLite execute: '+str(exc)) from None
    def executemany(self,*args,**kwargs):
        try:return super().executemany(*args,**kwargs)
        except sqlite3.Error as exc:raise CriticalFailure('SQLite executemany: '+str(exc)) from None
    def commit(self):
        try:return super().commit()
        except sqlite3.Error as exc:raise CriticalFailure('SQLite commit: '+str(exc)) from None
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        except sqlite3.Error as exc:raise CriticalFailure('SQLite transaction: '+str(exc)) from None


def require(condition,message):
    if not condition:raise CriticalFailure(message)


class CachedClient:
    def __init__(self,live):self.live=live;self.payloads={};self.frozen=False
    def get(self,path,params):
        key=(path,json.dumps(params,sort_keys=True))
        if self.frozen:
            require(key in self.payloads,'Consulta no preparada: no se consultara la red durante la escritura')
            return self.payloads[key]
        result=self.live.get(path,params);self.payloads[key]=result
        return result


def compare_original(conn,backup):
    result={}
    with closing(sqlite3.connect(Path(backup).resolve().as_uri()+'?mode=ro',uri=True)) as baseline:
        for table in ('mediciones','calidad_mediciones'):
            originals=set(baseline.execute('SELECT * FROM '+table))
            current=set(conn.execute('SELECT * FROM '+table))
            missing=len(originals-current)
            result[table+'_original_rows_changed_or_missing']=missing
            result[table+'_original_rows_preserved']=len(originals)-missing
            require(missing==0,'Se intentaron cambiar/eliminar filas originales de '+table)
    return result


def replay_on_copy(db,backup,sync,client,key):
    """Comprueba idempotencia con las respuestas verificadas; nunca sobre original."""
    source_sha=sha(db)
    client.frozen=True
    result={'mode':'temporary_copy_only','network_requests':0,'results':[]}
    with tempfile.TemporaryDirectory(prefix='aeris-controlled-replay-') as temp:
        target=Path(temp)/'replay.db';raw=Path(temp)/'raw';raw.mkdir()
        ops.copy_database(db,target)
        require(target.resolve()!=Path(db).resolve(),'Replay debe usar copia distinta')
        with closing(sqlite3.connect(target)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            before=conn.execute('SELECT COUNT(*) FROM evaluaciones_calidad').fetchone()[0]
            run_id=uuid.uuid4().hex
            with conn:
                conn.execute('INSERT INTO ingestas VALUES (?,?,NULL,?,NULL)',(run_id,ops.iso(ops.utcnow()),'running'))
                catalog=ops.load_catalog()
                for original in sync['results']:
                    sid=original['sensor_id']
                    records,receipts,stats=ops.collect(client,sid,catalog[sid]['location_id'],
                        ops.parse_utc(original['window_from_utc']),ops.parse_utc(original['window_to_utc_exclusive']),
                        100,50,raw,key)
                    change=ops.store_sensor(conn,run_id,sid,records,receipts)
                    require(change['new_measurements']==0 and change['conflicting_candidates']==0,'Replay no idempotente')
                    require(change['versioned_quality']['new_versioned_assessments']==0,'Replay duplico evaluaciones')
                    compare_original(conn,backup);verify_current(conn,sid)
                    result['results'].append({'sensor_id':sid,**change})
                conn.execute('UPDATE ingestas SET fin_utc=?,estado=? WHERE id=?',(ops.iso(ops.utcnow()),'success',run_id))
            after=conn.execute('SELECT COUNT(*) FROM evaluaciones_calidad').fetchone()[0]
            require(before==after,'Cambio el numero de evaluaciones en replay')
            require(conn.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Integridad incorrecta en replay')
            require(not conn.execute('PRAGMA foreign_key_check').fetchall(),'Claves foraneas incorrectas en replay')
            result.update(evaluations_before=before,evaluations_after=after)
    require(sha(db)==source_sha,'Replay altero la base original')
    result['original_unchanged_during_replay']=True
    return result


def main(plan_name=None):
    root=ops.ROOT;db=root/'data/aeris_air_quality.db'
    chosen_plan=plan_name or PLAN
    plan=json.loads((root/'reports'/chosen_plan).read_text(encoding='utf8'))
    backup=root/plan['backup']['path']
    holdout=root/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json'
    key=os.environ.get('OPENAQ_API_KEY','').strip()
    require(bool(key),'Falta credencial local')
    report={'schema':'aeris-controlled-sync-audit-v2','preflight':chosen_plan,'status':'checking_before_write',
            'started_at_utc':ops.iso(ops.utcnow()),'user_authorization':'one controlled incremental run only',
            'production_run_calls':0,'scheduled_tasks_installed':False,'predictions_enabled':False,
            'max_data_age_hours_unchanged':2,'critical_failure_stops_further_database_writes':True}
    audit_path=root/'reports'/('controlled_sync_audit_'+ops.utcnow().strftime('%Y%m%dT%H%M%SZ')+'.json')
    marker=root/'reports'/('controlled_sync_'+Path(chosen_plan).stem+'_authorization_consumed.json')
    frozen_time=ops.utcnow()
    real_copy,real_store,real_lock=ops.copy_database,ops.store_sensor,ops.exclusive_lock
    real_connect=sqlite3.connect
    app_before=sha(root/'app.py')
    release=root/'models/releases/aeris-pm25-20261017-v1'
    models_before={str(p.relative_to(release)):sha(p) for p in release.rglob('*') if p.is_file()}
    live=client=None
    try:
        with real_lock(Path(str(db)+'.sync.lock')):
            require(not marker.exists(),'Esta autorizacion ya fue consumida; no se repetira la sincronizacion')
            require(sha(db)==plan['original_sha256_before'],'La base cambio desde la preparacion')
            require(sha(backup)==plan['backup']['sha256'],'El respaldo preparado cambio')
            require(snapshot(db)==plan['baseline'] and snapshot(backup)==plan['baseline'],
                    'No coinciden integridad/contenidos de original y respaldo con la preparacion')
            require(sha(holdout)==plan['reserved_holdout_sha256_before'],'Cambio la reserva independiente')
            for file,expected in plan['tested_code_sha256'].items():
                require(sha(root/file)==expected,'Cambio codigo aprobado: '+file)
            report['tested_flow_confirmed']={'rehearsal':plan.get('source_rehearsal'),
                'matching_core_code_sha256':plan['tested_code_sha256'],
                'core_flow':'operations.run -> store_sensor -> quality_versioned.evaluate',
                'production_parameters':'incremental; overlap 48h; chunk 168h; limit 100; max_pages 50'}
            report['git_status_before']=plan.get('git_status_before')
            from .rehearse_versioned_quality import dashboard_probe
            old_dashboard,_=dashboard_probe(db)
            report['before']=snapshot(db)
            report['prepared_backup']={'path':str(backup),'sha256':sha(backup),'verified':True}
            report['credential_security_before']=credential_scan(root,key)
            require(not report['credential_security_before']['exact_credential_matches'],'Credencial encontrada en contenido revisado')
            require(report['credential_security_before']['secret_file_git_ignored'] and
                    not report['credential_security_before']['tracked_secret_paths'],'Proteccion Git de credencial incompatible')
            def verified_copy(source,destination):
                real_copy(source,destination)
                require(snapshot(source)==plan['baseline'] and snapshot(destination)==plan['baseline'],
                        'Fallo la verificacion del respaldo inmediatamente anterior a escritura')
                if 'backups' in destination.parts:
                    report['immediate_backup']={'path':str(destination),'sha256':sha(destination),'verified_before_sqlite_write':True}
            def guarded_store(conn,*args,**kwargs):
                try:result=real_store(conn,*args,**kwargs)
                except Exception as exc:raise CriticalFailure('Fallo al incorporar sensor: '+str(exc)) from None
                compare_original(conn,backup)
                require(conn.execute('PRAGMA foreign_key_check').fetchone() is None,'Fallo de claves foraneas antes de commit')
                return result
            def held_lock(path):
                require(Path(path)==Path(str(db)+'.sync.lock'),'Se solicito un bloqueo diferente al retenido')
                return nullcontext()
            def strict_connect(database,*args,**kwargs):
                if str(database)==str(db):kwargs['factory']=CriticalConnection
                return real_connect(database,*args,**kwargs)
            live=ObservedClient(key,Path(str(db)+'.sync.stop'));client=CachedClient(live)
            verify_sensor(client.get('/sensors/2694071',{}),2694071)
            report['authentication']='accepted'
            # El bloqueo exterior sigue retenido durante el ensayo y la corrida real.
            with patch.object(ops,'exclusive_lock',held_lock),patch.object(ops,'copy_database',verified_copy),\
                 patch.object(ops,'store_sensor',guarded_store),patch.object(ops,'utcnow',lambda:frozen_time):
                report['final_rehearsal']=ops.run(db,list(ops.ACTIVE),dry_run=True,key=key,client=client)
                require(report['final_rehearsal']['status']=='success','Ensayo final incompleto; no se escribira en original')
                require(sha(db)==plan['original_sha256_before'],'Cambio concurrente antes de escritura')
                require(ops.utcnow()<ops.parse_utc('2026-10-19T00:00:00Z'),'No se ejecutara esta autorizacion dentro del periodo reservado')
                client.frozen=True
                with marker.open('x',encoding='utf8') as out:
                    json.dump({'authorization_consumed_at_utc':ops.iso(frozen_time),'audit':audit_path.name,
                               'max_production_runs':1},out,indent=2)
                print('Respaldo, originales y calidad comprobados. Ejecutando UNA corrida real con respuestas ya verificadas.',flush=True)
                report['production_run_calls']=1
                with patch.object(sqlite3,'connect',strict_connect):
                    report['synchronization']=ops.run(db,list(ops.ACTIVE),dry_run=False,key=key,client=client)
            sync=report['synchronization']
            require(sync['status']=='success','Corrida parcial: no se ejecutaran nuevas escrituras ni reintentos')
            with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
                report['original_rows']=compare_original(conn,backup)
                report['duplicate_utc_groups']=conn.execute('''SELECT COUNT(*) FROM
                    (SELECT fuente,sensor_id,julianday(fecha_utc),contaminante,COUNT(*) n FROM mediciones
                     GROUP BY 1,2,3,4 HAVING n>1)''').fetchone()[0]
                require(report['duplicate_utc_groups']==0,'Hay duplicados UTC')
                report['new_quality_pending']=conn.execute('''SELECT COUNT(*) FROM mediciones m LEFT JOIN calidad_mediciones q
                    USING(fuente,sensor_id,fecha_utc,contaminante) WHERE q.sensor_id IS NULL''').fetchone()[0]
                require(report['new_quality_pending']==0,'Existen mediciones sin calidad')
                report['ingesta_state']=conn.execute('SELECT estado FROM ingestas WHERE id=?',(sync['run_id'],)).fetchone()[0]
                require(report['ingesta_state']=='success','Ingesta no cerrada correctamente')
                report['response_evidence_checked']=0
                for digest,path in conn.execute('SELECT sha256,ruta_local FROM respuestas_api'):
                    require(sha(path)==digest,'Evidencia de respuesta alterada')
                    report['response_evidence_checked']+=1
                for sid in ops.ACTIVE:verify_current(conn,sid)
                report['quality_reproducible']=True
                report['original_snapshots_registered']=conn.execute("SELECT COUNT(*) FROM evaluaciones_calidad WHERE origen='original_snapshot'").fetchone()[0]
                require(report['original_snapshots_registered']==12444,'Faltan evaluaciones historicas separadas')
                report['quality_versions']=[list(r) for r in conn.execute('SELECT fuente,version_reglas,COUNT(*) FROM calidad_mediciones GROUP BY 1,2')]
                report['latest_observations']=[]
                now=ops.utcnow()
                for sid in ops.ACTIVE:
                    stamp=conn.execute("SELECT MAX(fecha_utc) FROM mediciones WHERE fuente='OpenAQ' AND sensor_id=?",(sid,)).fetchone()[0]
                    age=(now-ops.parse_utc(stamp)).total_seconds()/3600
                    report['latest_observations'].append({'sensor_id':sid,'latest_period_start_utc':stamp,
                        'age_hours_at_audit':age,'meets_two_hour_age_limit':0<=age<=2})
            after=snapshot(db);report['after']=after
            require(after['integrity_check']==['ok'] and after['foreign_key_violations']==0,'Integridad final incorrecta')
            inserted=sum(r.get('new_measurements',0) for r in sync['results'])
            require(after['tables']['mediciones']['rows']==12444+inserted,'No coincide el total final de mediciones')
            require(after['tables']['calidad_mediciones']['rows']==12444+inserted,'No coincide el total de calidad')
            for table in ('archivos_origen','estaciones','observaciones_archivo'):
                require(after['tables'][table]==plan['baseline']['tables'][table],'Cambio una tabla protegida: '+table)
            after_dashboard,report['dashboard']=dashboard_probe(db)
            require(all(after_dashboard.get(k)==v for k,v in old_dashboard.items()),'Cambio la calidad original visible en dashboard')
            require(len(after_dashboard)==12444+inserted,'Dashboard multiplico filas')
            require(all(report['dashboard']['http_statuses'][p]==200 for p in
                ('/api/overview','/api/measurements?period=all','/api/export.csv?period=all')),'Fallo un endpoint de datos')
            report['dashboard']['original_serialized_flags_preserved']=True
            report['idempotence_on_copy']=replay_on_copy(db,backup,sync,client,key)
            report['status']='verified_success'
        print('Corrida unica completada; ejecutando pruebas sin red...',flush=True)
        stream=io.StringIO()
        with redirect_stdout(stream),redirect_stderr(stream):
            result=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover(str(root/'tests')))
        report['tests']={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                         'successful':result.wasSuccessful(),'network_used':False}
        require(result.wasSuccessful(),'Fallo una prueba posterior; no se realizaran mas escrituras SQLite')
        report['credential_security_after']=credential_scan(root,key)
        require(not report['credential_security_after']['exact_credential_matches'],'Credencial en reportes posteriores')
    except (CriticalFailure,Exception) as exc:
        report['status']='stopped_critical_failure'
        report['error']={'type':type(exc).__name__,'detail':str(exc).replace(key,'[redacted]')}
    finally:
        report['retained_api_responses']=[]
        if client is not None:
            evidence_dir=root/'data/sync_runtime/controlled'/audit_path.stem
            evidence_dir.mkdir(parents=True,exist_ok=True)
            for (path,params),payload in client.payloads.items():
                raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')
                if key.encode() in raw:continue
                import hashlib
                digest=hashlib.sha256(raw).hexdigest();dest=evidence_dir/(digest+'.json')
                if not dest.exists():dest.write_bytes(raw)
                report['retained_api_responses'].append({'path':path,'params':json.loads(params),
                    'sha256':digest,'local_path':str(dest)})
        report['original_sha256_after']=sha(db)
        report['reserved_holdout_unchanged']=sha(holdout)==plan['reserved_holdout_sha256_before']
        report['dashboard_unchanged']=sha(root/'app.py')==app_before
        report['release_files_unchanged']=models_before=={str(p.relative_to(release)):sha(p) for p in release.rglob('*') if p.is_file()}
        if not all(report[k] for k in ('reserved_holdout_unchanged','dashboard_unchanged','release_files_unchanged')):
            report['status']='stopped_critical_failure'
        report['finished_at_utc']=ops.iso(ops.utcnow())
        serialized=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).replace(key,'[redacted]')
        with audit_path.open('x',encoding='utf8') as out:out.write(serialized)
    print('AUDIT:',audit_path,'STATUS:',report['status'])
    if 'synchronization' in report:
        print('COUNTS:',json.dumps([{k:r.get(k) for k in ('sensor_id','new_measurements','identical','conflicting_candidates')} for r in report['synchronization']['results']]))
    return int(report['status']!='verified_success')


if __name__=='__main__':raise SystemExit(main())
