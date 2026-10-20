"""Prepara una autorizacion revisable; nunca escribe en SQLite original."""
import hashlib
import json
import os
import sqlite3
import subprocess
import uuid
from contextlib import closing
from pathlib import Path

from . import operations as ops
from .openaq_protocol import verify_sensor
from .verify_live import ObservedClient, inspect_received


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    """Fingerprint logico por tabla, integridad y referencias, en solo lectura."""
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        tables={}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            quoted='"'+name.replace('"','""')+'"'
            columns=[r[1] for r in conn.execute('PRAGMA table_info('+quoted+')')]
            order=','.join('"'+column.replace('"','""')+'"' for column in columns)
            digest=hashlib.sha256();count=0
            for row in conn.execute('SELECT * FROM '+quoted+' ORDER BY '+order):
                digest.update(json.dumps(row,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('utf8'))
                digest.update(b'\n');count+=1
            tables[name]={'rows':count,'sha256':digest.hexdigest(),'columns':columns}
        return {'integrity_check':[r[0] for r in conn.execute('PRAGMA integrity_check')],
                'foreign_key_violations':len(conn.execute('PRAGMA foreign_key_check').fetchall()),
                'tables':tables}


def credential_scan(root,key):
    """Solo devuelve ubicaciones de coincidencias; nunca contenido ni fragmentos."""
    patterns=[key.encode('utf8'),key.encode('utf-16-le')]
    def contains(data):return any(pattern in data for pattern in patterns)
    def git(*args):
        return subprocess.run(['git',*args],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=False)
    tracked=git('ls-files','-z').stdout.decode('utf8').split('\0')
    tracked=[p for p in tracked if p]
    matches=[];checked=0
    for name in tracked:
        path=root/name
        if path.is_file():
            checked+=1
            if contains(path.read_bytes()):matches.append({'scope':'tracked_worktree','path':name})
        for scope,revision in [('index',':'+name),('HEAD','HEAD:'+name)]:
            result=git('show',revision)
            if result.returncode==0:
                checked+=1
                if contains(result.stdout):matches.append({'scope':scope,'path':name})
    reports=list((root/'reports').rglob('*'))+list((root/'data/sync_runtime/reports').glob('*.json'))
    report_count=0
    for path in reports:
        if path.is_file():
            checked+=1;report_count+=1
            if contains(path.read_bytes()):matches.append({'scope':'report','path':str(path.relative_to(root))})
    ignored=git('check-ignore','.secrets/openaq_api_key.clixml').returncode==0
    tracked_secrets=[name for name in tracked if name.startswith('.secrets/')]
    return {'dpapi_decryption':'successful_by_current_windows_user','secret_file_git_ignored':ignored,
            'tracked_secret_paths':tracked_secrets,'contents_checked':checked,'report_files_checked':report_count,
            'exact_credential_matches':matches,'scope':'tracked worktree, Git index, HEAD, reports and sync reports',
            'limitation':'No audit of previous Git commits, editor unsaved buffers or third-party credentials'}


def main():
    root=ops.ROOT;db=root/'data/aeris_air_quality.db'
    holdout=root/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json'
    key=os.environ.get('OPENAQ_API_KEY','').strip()
    if not key:raise ValueError('Falta credencial local')
    identifier=ops.utcnow().strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=root/'reports'/('production_preflight_'+identifier+'.json')
    report={'schema':'aeris-production-preflight-v1','created_at_utc':ops.iso(ops.utcnow()),
            'status':'preparing','authorization_to_write_original':'pending_explicit_user_confirmation',
            'original_database_written':False,'task_installation_authorized':False,
            'original_sha256_before':sha(db),'reserved_holdout_sha256_before':sha(holdout)}
    try:
        report['credential_security']=credential_scan(root,key)
        security=report['credential_security']
        if security['exact_credential_matches'] or security['tracked_secret_paths'] or not security['secret_file_git_ignored']:
            raise ValueError('Fallo en comprobacion de proteccion de credenciales; revisar reporte sin contenido secreto')
        with ops.exclusive_lock(Path(str(db)+'.sync.lock')):
            before=snapshot(db)
            if before['integrity_check']!=['ok'] or before['foreign_key_violations']:
                raise ValueError('La base original requiere revisar integridad antes de continuar')
            backup=root/'data/backups'/('aeris_before_controlled_sync_'+identifier+'.db')
            backup.parent.mkdir(parents=True,exist_ok=True)
            ops.copy_database(db,backup)
            copied=snapshot(backup)
            if before!=copied:raise ValueError('El respaldo no coincide logicamente con la base original')
            report['baseline']=before
            report['backup']={'path':str(backup.relative_to(root)),'sha256':sha(backup),
                              'verified_logical_equality':True,'integrity_check':copied['integrity_check'],
                              'foreign_key_violations':copied['foreign_key_violations']}
        print('Respaldo creado y verificado; comprobando API y ensayo incremental...',flush=True)
        client=ObservedClient(key,Path(str(db)+'.sync.stop'))
        verify_sensor(client.get('/sensors/2694071',{}),2694071)
        report['authentication']='accepted'
        rehearsal=ops.run(db,list(ops.ACTIVE),dry_run=True,key=key,client=client)
        report['incremental_rehearsal']=rehearsal
        catalog=ops.load_catalog();clock=ops.utcnow()
        report['api_observations']=[]
        for result in rehearsal['results']:
            sid=result['sensor_id']
            report['api_observations'].append(inspect_received(client.rows.get(sid,[]),sid,catalog[sid]['location_id'],
                ops.parse_utc(result['window_from_utc']),ops.parse_utc(result['window_to_utc_exclusive']),clock))
        report['successful_requests']=client.requests
        report['planned_schema_additions']=[t for t in ('sensores','respuestas_api','observaciones_api','sincronizacion_estado','historial_calidad') if t not in before['tables']]
        report['planned_catalog_rows']=len(catalog)
        report['expected_new_measurements_from_rehearsal']=sum(r.get('new_measurements',0) for r in rehearsal['results'])
        report['expected_identical_from_rehearsal']=sum(r.get('identical',0) for r in rehearsal['results'])
        report['expected_conflicts_from_rehearsal']=sum(r.get('conflicting_candidates',0) for r in rehearsal['results'])
        report['production_python_arguments']=['-B','-m','data_ingestion.operations','--incremental','--sensor',
            *map(str,ops.ACTIVE),'--limit','100','--max-pages','50','--overlap-hours','48','--chunk-hours','168']
        report['status']='ready_awaiting_authorization' if rehearsal['status']=='success' else 'review_required_before_authorization'
    except (OSError,RuntimeError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        report['status']='preflight_failed'
        report['error']={'type':type(exc).__name__,'detail':str(exc).replace(key,'[redacted]')}
    report['original_sha256_after']=sha(db)
    report['reserved_holdout_sha256_after']=sha(holdout)
    report['original_database_unchanged']=report['original_sha256_before']==report['original_sha256_after']
    report['reserved_holdout_unchanged']=report['reserved_holdout_sha256_before']==report['reserved_holdout_sha256_after']
    report['finished_at_utc']=ops.iso(ops.utcnow())
    if not report['original_database_unchanged'] or not report['reserved_holdout_unchanged']:
        report['status']='baseline_changed_requires_review'
    with output.open('x',encoding='utf8') as handle:json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
    print('PREFLIGHT_REPORT:',output)
    print('STATUS:',report['status'],'NEW_ON_COPY:',report.get('expected_new_measurements_from_rehearsal'),
          'ORIGINAL_UNCHANGED:',report['original_database_unchanged'])
    return int(report['status']!='ready_awaiting_authorization')


if __name__=='__main__':raise SystemExit(main())
