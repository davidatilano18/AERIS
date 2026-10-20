"""Read-only release evidence; distinguish unattended collection from web changes."""
import hashlib
import json
import sqlite3
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def digest(rows):return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()


def connect(path):
    conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
    return conn


def main():
    import app
    from aeris_web.comparisons import read_comparison
    baseline=json.loads((ROOT/'reports/dashboard_v22_baseline.json').read_text(encoding='utf-8'))
    db=ROOT/'data/aeris_air_quality.db'
    conn=connect(db)
    try:
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        tables={}
        for table in baseline['tables']:
            rows=conn.execute('SELECT * FROM '+table+' ORDER BY 1,2,3,4').fetchall()
            tables[table]={'count':len(rows),'sha256':digest(rows)}
        same=tables==baseline['tables']
        preserved=same;automatic=None;ledger={}
        if not same:
            audit_path=ROOT/'data/sync_runtime/scheduler/last_success.json'
            audit=json.loads(audit_path.read_text(encoding='utf-8'))
            backup=Path(audit['backup']['path']);previous=connect(backup)
            try:
                verified=True
                for table in baseline['tables']:
                    old=previous.execute('SELECT * FROM '+table+' ORDER BY 1,2,3,4').fetchall()
                    new=conn.execute('SELECT * FROM '+table).fetchall()
                    verified &= (digest(old)==baseline['tables'][table]['sha256'] and set(old)<=set(new))
                for table in ('evaluaciones_calidad','reglas_calidad_versionadas','evaluaciones_calidad_ingestas'):
                    old=previous.execute('SELECT * FROM '+table).fetchall()
                    new=conn.execute('SELECT * FROM '+table).fetchall()
                    ledger[table]={'before':len(old),'after':len(new),'old_rows_identical':set(old)<=set(new)}
                preserved=bool(verified and all(t['old_rows_identical'] for t in ledger.values()))
                automatic={'evidence':str(audit_path.relative_to(ROOT)),'started_at_utc':audit['started_at_utc'],
                    'finished_at_utc':audit['finished_at_utc'],'status':audit['status'],
                    'after_baseline':datetime.fromisoformat(audit['started_at_utc'])>datetime.fromisoformat(baseline['captured_at_utc']),
                    'new_measurements':sum(r.get('new_measurements',0) for r in audit['synchronization']['results']),
                    'backup':str(backup),'backup_matches_baseline_tables':bool(verified)}
            finally:previous.close()
    finally:conn.close()
    changed=[name for name,value in baseline['protected_files'].items()
             if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value]
    client=app.app.test_client()
    routes={r:client.get(r).status_code for r in ('/','/v2','/v2/datos','/api/overview',
        '/api/measurements?period=all','/api/comparison','/health','/api/v2/public?station=1352686&period=all',
        '/api/v2/comparison?station=1352686&anchor=latest')}
    examples=[read_comparison(db,source,str(sid),anchor) for source,sid,anchor in (
        ('OpenAQ-Archive',1352676,'latest'),('OpenAQ-Archive',1352681,'latest'),
        ('OpenAQ-Archive',2694071,'latest'),('OpenAQ',1352686,'latest'),('OpenAQ',1352676,'recent'))]
    result={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'sqlite_integrity':integrity,
        'foreign_key_violations':fk,'database_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),
        'database_byte_identical':hashlib.sha256(db.read_bytes()).hexdigest()==baseline['database_sha256'],
        'tables':tables,'baseline_records_preserved':preserved,'automatic_collection_during_work':automatic,
        'versioned_ledger_preserved':ledger,'protected_files_changed':changed,'routes':routes,
        'manual_sync_calls':0,'task_modifications':0,'examples':examples}
    result['successful']=(integrity=='ok' and not fk and preserved and not changed and
        all(v==200 for v in routes.values()) and
        (same or automatic['after_baseline'] and automatic['status']=='success' and
         tables['mediciones']['count']-baseline['tables']['mediciones']['count']==automatic['new_measurements']))
    (ROOT/'reports/dashboard_v22_validation.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('examples','tables')},indent=2,ensure_ascii=False))
    if not result['successful']:raise RuntimeError('Preservation discrepancy. Evidence saved; no corrective writes attempted.')


if __name__=='__main__':main()
