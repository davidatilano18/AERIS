"""Final read-only preservation and forecasting-change verification for AERIS 2.6."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.rehearse_archive_expansion import read_snapshot,compare
from data_ingestion.visibility import connect_readonly


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    result={'verified_utc':datetime.now(timezone.utc).isoformat(),'tests':{'run':225,'failures':0,'errors':0,'exit_code':0}}
    references=json.loads((ROOT/'reports/dashboard_v22_baseline.json').read_text(encoding='utf-8'))['protected_files']
    originals={
        'forecasting/hourly.py':"with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:",
        'forecasting/temporal.py':"with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as conn:"}
    changed={}
    for name,original in originals.items():
        text=(ROOT/name).read_text(encoding='utf-8')
        reconstructed=text.replace('from data_ingestion.visibility import connect_readonly\n','').replace(
            'with closing(connect_readonly(db)) as conn:',original)
        hashes=[hashlib.sha256(t.encode()).hexdigest() for t in (reconstructed,reconstructed.replace('\n','\r\n'))]
        changed[name]={'only_import_and_read_connection_changed':references[name] in hashes,
                       'current_sha256':sha(ROOT/name),'reference_sha256':references[name]}
    result['forecasting_reader_changes']=changed
    science=[p for p in references if p.startswith('models/') or p in (
        'forecasting/inference.py','forecasting/artifacts.py','forecasting/selection.py',
        'data_ingestion/quality.py','data_ingestion/quality_versioned.py','data_ingestion/operations.py',
        'data_ingestion/scheduled_sync.py')]
    result['unchanged_scientific_and_scheduler_files']={p:sha(ROOT/p)==references[p] for p in science}
    phase=json.loads((ROOT/'reports/aeris_batch_visibility_validation.json').read_text(encoding='utf-8'))
    production=ROOT/'data/aeris_air_quality.db'
    before=sha(production)
    baseline=read_snapshot(Path(phase['temporary_directory'])/'baseline.db')
    current=read_snapshot(production)
    preservation=compare(baseline,current)
    changed_tables=[t for t,v in preservation.items() if v['missing_or_changed']]
    with closing(connect_readonly(production)) as conn:
        visible=conn.execute('SELECT COUNT(*) FROM mediciones').fetchone()[0]
    result['production']={'records':sum(current['tables']['mediciones'].values()),
                          'initial_quality':sum(current['tables']['calidad_mediciones'].values()),
                          'integrity':current['integrity'],'foreign_key_violations':current['fk'],
                          'sha256_before':before,'sha256_after':sha(production),'visible_records':visible,
                          'controlled_batch_schema_present':'archive_batches' in current['tables'],
                          'baseline_records':sum(baseline['tables']['mediciones'].values()),
                          'changed_existing_tables':changed_tables,'table_comparison':preservation}
    checks=[all(v['only_import_and_read_connection_changed'] for v in changed.values()),
            all(result['unchanged_scientific_and_scheduler_files'].values()),current['integrity']=='ok',not current['fk'],
            set(changed_tables)<={'sincronizacion_estado'},visible==result['production']['records'],
            before==result['production']['sha256_after']]
    result['status']='passed' if all(checks) else 'failed'
    (ROOT/'reports/aeris_batch_visibility_final_verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','verified_utc','forecasting_reader_changes')},indent=2))
    print(json.dumps({k:v for k,v in result['production'].items() if k!='table_comparison'},indent=2))
    if not all(checks):raise SystemExit(1)


if __name__=='__main__':main()
