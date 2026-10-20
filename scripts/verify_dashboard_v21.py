"""Verify preservation against the pre-implementation snapshot, in read-only mode."""
import hashlib
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import app
    baseline=json.loads((ROOT/'reports/dashboard_v21_baseline.json').read_text(encoding='utf-8'))
    path=ROOT/'data/aeris_air_quality.db'
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        tables={}
        for table in baseline['tables']:
            rows=conn.execute('SELECT * FROM '+table+' ORDER BY 1,2,3,4').fetchall()
            tables[table]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
        coverage=conn.execute('''SELECT sensor_id,fuente,strftime('%Y',fecha_utc),count(*),
            min(fecha_utc),max(fecha_utc) FROM mediciones GROUP BY 1,2,3''').fetchall()
    finally:conn.close()
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    protected_changed=[name for name,expected in baseline['protected_files'].items()
                       if not (ROOT/name).is_file() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected]
    client=app.app.test_client()
    routes={url:client.get(url).status_code for url in (
        '/','/v2','/v2/datos','/api/overview','/api/measurements?period=all',
        '/api/comparison','/api/export.csv?period=all','/health','/api/v2/observations',
        '/api/v2/public?station=1352686&period=all')}
    historical=client.get('/api/v2/public?station=1352686&period=all').get_json()
    recent=client.get('/api/v2/public?station=1352686').get_json()
    result={'verified_at_utc':datetime.now(timezone.utc).isoformat(),
        'sqlite_integrity':integrity,'foreign_key_violations':fk,'database_sha256':sha,
        'database_byte_identical':sha==baseline['database_sha256'],
        'tables':tables,'original_keys_and_values_identical':tables==baseline['tables'],
        'protected_files_changed':protected_changed,'routes':routes,'coverage':coverage,
        'marques':{'historical_count':historical['stats']['count'],
                   'coverage':historical['public']['coverage'],
                   'latest':historical['station_latest'],
                   'recent_period_count':recent['stats']['count']},
        'manual_sync_calls':0,'task_operations':0}
    result['successful']=(integrity=='ok' and not fk and result['database_byte_identical']
        and result['original_keys_and_values_identical'] and not protected_changed
        and all(status==200 for status in routes.values()))
    (ROOT/'reports/dashboard_v21_validation.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if not result['successful']:raise RuntimeError('Preservation check failed; inspect the report. No corrective writes attempted.')


if __name__=='__main__':main()
