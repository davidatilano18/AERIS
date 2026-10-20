"""Prepare durable evidence and exercise controlled batches exclusively on temporary copies."""
import argparse
import csv
import gzip
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from data_ingestion import archive_controlled as controlled
from data_ingestion.catalog import load_catalog
from scripts.rehearse_archive_expansion import validate_row,read_snapshot,compare,SELECTED,protected_files


def prepare_bundle():
    probe=json.loads((ROOT/'reports/aeris_source_probe_manifest.json').read_text(encoding='utf-8'))
    entries={r['label']:r for r in probe['requests'] if r.get('status')==200 and r.get('path') and not r.get('truncated')}
    payload={};requests=[];archives=[];candidates=[];catalog=load_catalog()
    def capture(label,target):
        entry=entries[label];p=Path(entry['path']).resolve()
        if not p.is_relative_to(Path(probe['temporary_directory']).resolve()) or controlled.sha(p)!=entry['captured_sha256']:
            raise ValueError('Source evidence altered')
        payload[target]=p.read_bytes()
        requests.append({k:entry.get(k) for k in ('label','url','method','requested_at_utc','status','etag','last_modified','captured_sha256')})
        return payload[target],entry
    for loc,(sid,count) in SELECTED.items():
        b,e=capture(f'archive_day_{loc}_20250501',f'raw/{loc}.csv.gz')
        md,_=capture('api_location_'+str(loc),f'metadata/{loc}.json')
        metadata=json.loads(md)['results'][0]
        rows=list(csv.DictReader(io.StringIO(gzip.decompress(b).decode('utf-8-sig'))))
        selected=0
        for number,row in enumerate(rows,2):
            if row['parameter']!='pm25':continue
            c=validate_row(row,loc,sid,metadata,catalog[sid])
            c.update(file_sha256=e['captured_sha256'],row_number=number)
            candidates.append(c);selected+=1
        if selected!=count:raise ValueError('Sample count mismatch')
        archives.append({'location_id':loc,'path':f'raw/{loc}.csv.gz','sha256':e['captured_sha256'],
                         'url':e['url'],'downloaded_at_utc':e['requested_at_utc']})
    capture('api_sinaica_license','metadata/license36.json')
    capture('archive_day_235220_20250701','later_control_sample.csv.gz')
    payload['candidates.json']=controlled.canonical(candidates).encode()
    payload['requests.json']=controlled.canonical(requests).encode()
    payload['catalog.json']=controlled.canonical(catalog).encode()
    payload['quality_definition.json']=controlled.canonical(controlled.qc.V2_DEFINITION).encode()
    for name in ('quality.py','quality_versioned.py','archive_controlled.py','visibility.py'):
        payload['code/'+name]=(ROOT/'data_ingestion'/name).read_bytes()
    descriptor={'format':'aeris-controlled-archive-preparation-v1','source':controlled.SOURCE,
                'timestamp_semantics':'reported archive timestamp; interval boundaries and aggregation unknown',
                'archive_files':archives,'evidence':[{'path':p,'sha256':controlled.hashlib.sha256(b).hexdigest()}
                                                   for p,b in sorted(payload.items())]}
    batch=controlled.hashlib.sha256(controlled.canonical(descriptor).encode()).hexdigest()
    folder=ROOT/'data/source_research/archive_batches'/batch
    if folder.exists():controlled.verify_bundle(folder);return folder
    folder.mkdir(parents=True)
    for name,b in payload.items():
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as out:out.write(b)
    manifest={'batch_id':batch,'created_utc':controlled.now(),'preparation_run_id':controlled.uuid.uuid4().hex,'descriptor':descriptor}
    with (folder/'manifest.json').open('x',encoding='utf-8') as out:json.dump(manifest,out,indent=2,ensure_ascii=False)
    controlled.verify_bundle(folder)
    return folder


def backup(source,target):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)) as src:
        src.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(target)) as dst:src.backup(dst)


def run():
    folder=Path(tempfile.mkdtemp(prefix='tmp_aeris_archive_readiness_',dir=ROOT/'reports'))
    output=ROOT/'reports/aeris_archive_production_readiness.json'
    report={'started_utc':controlled.now(),'temporary_directory':str(folder),'status':'preparing',
            'production_sha256_before':controlled.sha(controlled.PRODUCTION),
            'preparation_run_id':controlled.uuid.uuid4().hex}
    def save():output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    save();protected=protected_files()
    try:
        bundle=prepare_bundle();manifest,candidates=controlled.verify_bundle(bundle)
        report.update(bundle=str(bundle),batch_id=manifest['batch_id'],manifest_sha256=controlled.sha(bundle/'manifest.json'))
        baseline=folder/'baseline.db';backup(controlled.PRODUCTION,baseline)
        initial=read_snapshot(baseline)
        if initial['integrity']!='ok' or initial['fk']:raise ValueError('Initial snapshot integrity')
        report['initial_records']=sum(initial['tables']['mediciones'].values())
        def clone(name):
            db=folder/(name+'.db');backup(baseline,db);return db
        db=clone('controlled')
        first=controlled.import_copy(bundle,db);after=read_snapshot(db)
        preservation=compare(initial,after)
        if any(v['missing_or_changed'] for v in preservation.values()):raise ValueError('Historical preservation failure')
        second=controlled.import_copy(bundle,db)
        if read_snapshot(db)!=after:raise ValueError('Repeated import changed database contents')
        if first['new_measurements']!=71 or first['quality']!={'initial':71,'assessments':74,'historical_reevaluations':3}:
            raise ValueError('Unexpected scoped QC volume')
        report.update(first=first,second=second,preservation=preservation,
                      repeated_import_all_tables_identical=True,final_copy_records=sum(after['tables']['mediciones'].values()))
        cases={}
        def checked_failure(name,fault):
            target=clone(name)
            try:controlled.import_copy(bundle,target,fault)
            except (RuntimeError,ValueError,sqlite3.Error):pass
            else:raise AssertionError('Failure injection not detected')
            if read_snapshot(target)!=initial:raise ValueError('Failed operation left changes: '+name)
            cases[name]='rolled_back_all_tables_and_schema'
        def interrupted(stage,conn,i):
            if stage=='after_insert' and i==5:raise RuntimeError('Simulated interruption')
        checked_failure('interruption',interrupted)
        def bad_integrity(stage,conn,i):
            if stage=='before_commit':
                conn.execute('PRAGMA defer_foreign_keys=ON')
                conn.execute("INSERT INTO archive_batch_keys VALUES (?,'OpenAQ-Archive',999,'2025-05-01T07:00:00Z','pm25')",(manifest['batch_id'],))
        checked_failure('foreign_key_error',bad_integrity)
        def changed_history(stage,conn,i):
            if stage=='before_commit':conn.execute("UPDATE mediciones SET valor=valor+1 WHERE fuente='OpenAQ' AND sensor_id=1352676")
        checked_failure('historical_integrity_error',changed_history)
        locked=clone('locked')
        with controlled.exclusive_lock(Path(str(locked)+'.sync.lock')):
            try:controlled.import_copy(bundle,locked)
            except OSError:cases['lock_conflict']='refused_before_backup_or_write'
            else:raise AssertionError('Shared scheduler lock not respected')
        if read_snapshot(locked)!=initial:raise ValueError('Lock conflict altered copy')
        crash=clone('crash')
        process=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--crash-copy',str(crash),'--bundle',str(bundle)],
                               capture_output=True,timeout=45)
        if process.returncode!=73:raise ValueError('Crash simulation failed')
        # SQLite recovers the abandoned transaction on the isolated writable database.
        with closing(sqlite3.connect(crash)) as conn:conn.execute('PRAGMA integrity_check').fetchall()
        if read_snapshot(crash)!=initial:raise ValueError('Crash recovery changed original state')
        with controlled.exclusive_lock(Path(str(crash)+'.sync.lock')):pass
        cases['process_crash']='exit_73_journal_recovered_lock_released_original_state_restored'
        # Inject a same-source conflicting value in another isolated copy, never overwrite it.
        conflict=clone('conflict');c=candidates[0]
        with closing(sqlite3.connect(conflict)) as conn,conn:
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',(c['source'],c['sensor_id'],c['utc'],c['pollutant'],c['value']+1,c['unit']))
        conflict_before=read_snapshot(conflict)
        try:controlled.import_copy(bundle,conflict)
        except ValueError:pass
        else:raise AssertionError('Conflict not rejected')
        if read_snapshot(conflict)!=conflict_before:raise ValueError('Conflict overwrote records')
        cases['duplicate_conflicting_value']='rejected_and_original_preserved'
        # Simulate a later legitimate writer with a real, previously downloaded CAP row.
        # It keeps its original timestamp; no synthetic measurement or sync is executed.
        from data_ingestion.plan_recovery import utc_hour,stamp
        controls=list(csv.DictReader(io.StringIO(gzip.decompress((bundle/'later_control_sample.csv.gz').read_bytes()).decode('utf-8-sig'))))
        later=next(c for c in controls if c['parameter']=='pm25')
        if int(later['sensors_id'])!=8956473 or later['units']!='µg/m³':raise ValueError('Unexpected real control observation')
        later_tuple=(controlled.SOURCE,8956473,stamp(utc_hour(later['datetime'])),'pm25',float(later['value']),later['units'])
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',later_tuple)
            controlled.qc.evaluate(conn,8956473,controlled.SOURCE)
        report['later_real_control_observation']=later_tuple
        physical=read_snapshot(db)
        restored=folder/'restored_to_new_file.db';backup(first['backup'],restored)
        if read_snapshot(restored)!=initial or read_snapshot(db)!=physical:
            raise ValueError('Alternate-file backup restoration failed or changed live copy')
        cases['backup_restoration']='restored_to_new_file_live_copy_and_later_measurement_untouched'
        if not controlled.set_visibility(db,manifest['batch_id'],'inactive','Isolated rollback test'):raise AssertionError('Rollback missing')
        with closing(controlled.visible_connection(db)) as conn:
            visible=conn.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0]
            physical_count=conn.execute('SELECT COUNT(*) FROM main.mediciones').fetchone()[0]
            later_preserved=conn.execute('SELECT * FROM mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?',later_tuple[:4]).fetchone()
        if visible!=report['initial_records']+1 or physical_count!=report['initial_records']+72 or later_preserved!=later_tuple:
            raise ValueError('Logical rollback lost later records')
        if controlled.set_visibility(db,manifest['batch_id'],'inactive','Repeat rollback'):raise AssertionError('Rollback not idempotent')
        controlled.set_visibility(db,manifest['batch_id'],'active','Isolated reactivation')
        post_restore=read_snapshot(db)
        if any(v['missing_or_changed'] for v in compare(physical,post_restore).values()):raise ValueError('Restoration removed data')
        cases['logical_reversal_and_reactivation']='no_deletions_no_whole_database_restore'
        report['failure_cases']=cases
        # Existing Flask routes run unmodified, with the opt-in reader confined to this process.
        import app
        with patch.object(app,'DB',db):
            client=app.app.test_client()
            report['routes']={u:client.get(u).status_code for u in ('/','/v2','/v2/datos','/api/v2/observations?source=OpenAQ-Archive&period=all','/api/measurements?period=all')}
            controlled.set_visibility(db,manifest['batch_id'],'inactive','Endpoint rollback test')
            report['visible_api_after_rollback']=client.get('/api/v2/observations?source=OpenAQ-Archive&period=all').get_json()['stats']['count']
        if any(s!=200 for s in report['routes'].values()) or report['visible_api_after_rollback']!=8733:
            raise ValueError('Reader compatibility failure')
        with patch.object(app,'DB',db):
            report['unadapted_api_after_rollback']=app.app.test_client().get('/api/v2/observations?source=OpenAQ-Archive&period=all').get_json()['stats']['count']
        report['reader_adapter_not_deployed']=False
        report['protected_project_files_unchanged']=protected_files()==protected
        if not report['protected_project_files_unchanged']:raise ValueError('Protected project files changed')
        report['final_integrity']=read_snapshot(db)['integrity']
        report['final_foreign_key_violations']=read_snapshot(db)['fk']
        report['decision']='NO-GO for direct execution: prepared writer still deliberately accepts copies only'
        report.update(status='success',production_sha256_after=controlled.sha(controlled.PRODUCTION))
        report['production_byte_identical']=report['production_sha256_before']==report['production_sha256_after']
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc));save();raise
    finally:
        report['finished_utc']=controlled.now()
        # Execution evidence is retained outside temporary folders, without publishing databases.
        durable=ROOT/'data/source_research/archive_runs'/report['preparation_run_id']
        durable.mkdir(parents=True,exist_ok=False)
        journals=[]
        for path in sorted((folder/'archive_audits').glob('*.jsonl')):
            raw=path.read_bytes()
            with (durable/path.name).open('xb') as out:out.write(raw)
            journals.append({'path':path.name,'sha256':controlled.sha(path),
                             'last_state':json.loads(raw.decode().splitlines()[-1])['state']})
        report['durable_run_directory']=str(durable);report['audit_journals']=journals
        save()
        with (durable/'report.json').open('x',encoding='utf-8') as out:json.dump(report,out,indent=2,ensure_ascii=False)
    print(json.dumps({k:report[k] for k in ('status','bundle','initial_records','first','second','failure_cases','decision','production_byte_identical')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crash-copy',type=Path);parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    if args.crash_copy:
        def crash(stage,conn,i):
            if stage=='after_insert' and i==5:os._exit(73)
        controlled.import_copy(args.bundle,args.crash_copy,crash)
    else:run()
