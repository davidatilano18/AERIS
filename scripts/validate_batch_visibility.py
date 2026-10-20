"""Real Archive batch visibility validation on a fresh copy; no sync, training or production writes."""
import ast
import csv
import io
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from data_ingestion import archive_controlled as archive
from data_ingestion.visibility import connect_readonly,POLICY
from data_ingestion.operations import store_sensor
from data_ingestion.openaq_protocol import verify_location_sensor,parse_verified_hour
from scripts.prepare_archive_readiness import prepare_bundle,backup
from scripts.rehearse_archive_expansion import read_snapshot,compare,protected_files


def inventory():
    paths=list(ROOT.glob('*.py'))
    for folder in ('aeris_web','forecasting','data_ingestion','scripts'):
        paths.extend((ROOT/folder).glob('*.py'))
    result=[]
    for path in sorted(paths):
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        connections=[];csv_reads=[];sql=[];central=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                call=ast.unparse(node.func)
                if call.endswith(('.connect','CONNECT')):connections.append(node.lineno)
                if call.endswith('read_csv'):csv_reads.append(node.lineno)
                if call.endswith(('connect_readonly','visible_connection')):central.append(node.lineno)
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                value=node.value.lower()
                if any(table in value for table in ('mediciones','evaluaciones_calidad')) and any(word in value for word in ('select ','from ','join ')):
                    sql.append(node.lineno)
        if connections or csv_reads or sql or central:
            result.append({'file':str(path.relative_to(ROOT)).replace('\\','/'),'raw_connection_lines':sorted(set(connections)),
                           'central_reader_lines':sorted(set(central)),'csv_read_lines':sorted(set(csv_reads)),
                           'sql_measurement_assessment_lines':sorted(set(sql))})
    (ROOT/'reports/aeris_batch_reader_inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    folder=Path(tempfile.mkdtemp(prefix='tmp_aeris_batch_visibility_',dir=ROOT/'reports'))
    report={'started_utc':archive.now(),'temporary_directory':str(folder),'policy':POLICY,'status':'preparing',
            'production_sha256_before':archive.sha(archive.PRODUCTION),'reader_inventory':inventory()}
    protected=protected_files();output=ROOT/'reports/aeris_batch_visibility_validation.json'
    def save():output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    save()
    try:
        bundle=prepare_bundle();manifest,candidates=archive.verify_bundle(bundle)
        baseline=folder/'baseline.db';db=folder/'visibility.db'
        backup(archive.PRODUCTION,baseline);backup(baseline,db)
        initial=read_snapshot(baseline)
        report.update(bundle=str(bundle),batch_id=manifest['batch_id'],manifest_sha256=archive.sha(bundle/'manifest.json'),
                      baseline_records=sum(initial['tables']['mediciones'].values()))
        import app
        from aeris_web.data import read_dashboard
        from aeris_web.comparisons import read_comparison
        from forecasting.hourly import load_series
        series_before,metadata_before=load_series(baseline,1352676,archive.SOURCE)
        report['import']=archive.import_copy(bundle,db)
        # Replay ONE real stored API response through the actual persistence function, offline.
        # This is not a call to collect/run/scheduled_sync and never accesses the network.
        probe=json.loads((ROOT/'reports/aeris_source_probe_manifest.json').read_text(encoding='utf-8'))
        entries={r['label']:r for r in probe['requests'] if r.get('status')==200 and r.get('path')}
        def captured(label):
            e=entries[label];p=Path(e['path']).resolve()
            if not p.is_relative_to(Path(probe['temporary_directory']).resolve()) or archive.sha(p)!=e['captured_sha256']:
                raise ValueError('Original API evidence mismatch')
            return p.read_bytes(),e
        raw,receipt=captured('api_cor_hours_20250501')
        metadata,_=captured('api_location_235225')
        verify_location_sensor(json.loads(metadata),1352676,235225)
        record=parse_verified_hour(json.loads(raw)['results'][0],1352676,235225)
        raw_path=folder/'later_real_api_response.json';raw_path.write_bytes(raw)
        run_id=archive.uuid.uuid4().hex
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('INSERT INTO ingestas VALUES (?,?,?,?,?)',(run_id,archive.now(),archive.now(),'isolated_replay','{}'))
            later=store_sensor(conn,run_id,1352676,[(record,receipt['captured_sha256'],0)],
                               [(receipt['captured_sha256'],receipt['url'],str(raw_path),receipt['requested_at_utc'])])
        if later['new_measurements']!=1:raise ValueError('Expected one real subsequent API observation')
        report['later_persistence']={'run_id':run_id,'record':record,'result':later,
                                     'response_sha256':receipt['captured_sha256'],'url':receipt['url']}
        active_physical=read_snapshot(db)
        def capture_state():
            with patch.object(app,'DB',db):
                client=app.app.test_client()
                urls=('/', '/v2','/v2/datos','/api/overview','/api/measurements?period=all',
                      '/api/comparison','/api/export.csv?period=all','/health',
                      '/api/v2/observations?source=OpenAQ-Archive&period=all',
                      '/api/v2/public?source=OpenAQ-Archive&period=all&station=1352676',
                      '/api/v2/stations?source=OpenAQ-Archive&period=all',
                      '/api/v2/comparison?source=OpenAQ-Archive&station=1352676&anchor=latest')
                responses={u:client.get(u) for u in urls}
                if any(r.status_code not in (200,503) for r in responses.values()):raise ValueError('Endpoint failure')
                if any(r.status_code!=200 for u,r in responses.items() if u!='/health'):raise ValueError('Data route failed')
                exported=list(csv.DictReader(io.StringIO(responses['/api/export.csv?period=all'].get_data(as_text=True).lstrip('\ufeff'))))
                all_points=[(r['fuente'],r['sensor_id'],r['fecha_utc']) for r in exported]
                with closing(connect_readonly(db)) as conn:
                    quality_counts={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in
                                    ('calidad_mediciones','evaluaciones_calidad','evaluaciones_calidad_ingestas')}
                data=read_dashboard(db,source=archive.SOURCE,period='all',include_history=True)
                series,meta=load_series(db,1352676,archive.SOURCE)
                return {'routes':{u:r.status_code for u,r in responses.items()},'csv_records':len(exported),
                        'exported_batch_rows':sum((c['source'],str(c['sensor_id']),c['utc']) in all_points for c in candidates),
                        'exported_later_api_rows':sum(key==('OpenAQ','1352676',record['from_utc']) for key in all_points),
                        'overview':responses['/api/overview'].get_json()['total'],
                        'measurements_stats':responses['/api/measurements?period=all'].get_json()['stats'],
                        'archive_stats':data['stats'],'inventory':data['inventory'],
                        'quality_counts':quality_counts,'research_records':meta['records'],'research_sha256':meta['input_sha256'],
                        'comparison':responses['/api/v2/comparison?source=OpenAQ-Archive&station=1352676&anchor=latest'].get_json(),
                        'health':responses['/health'].get_json()},series
        active,_=capture_state()
        archive.set_visibility(db,manifest['batch_id'],'inactive','AERIS 2.6 isolated reader validation')
        reverted,restored_series=capture_state()
        if active['exported_batch_rows']!=71 or reverted['exported_batch_rows']!=0 or reverted['exported_later_api_rows']!=1:
            raise ValueError('Export/source visibility failure')
        if active['archive_stats']['count']-reverted['archive_stats']['count']!=71:
            raise ValueError('Public statistics visibility failure')
        if reverted['csv_records']!=report['baseline_records']+1:raise ValueError('Legitimate observations hidden')
        if not restored_series.equals(series_before) or reverted['research_sha256']!=metadata_before['input_sha256']:
            raise ValueError('Research reader differs from original visible observations')
        preservation=compare(active_physical,read_snapshot(db))
        if any(v['missing_or_changed'] for v in preservation.values()):raise ValueError('Reversion mutated physical history')
        archive.set_visibility(db,manifest['batch_id'],'active','Restore isolated reader validation')
        reactivated,_=capture_state()
        if reactivated['exported_batch_rows']!=71 or reactivated['csv_records']!=active['csv_records']:
            raise ValueError('Reactivation visibility failure')
        final=read_snapshot(db)
        if final['integrity']!='ok' or final['fk']:raise ValueError('Final isolated integrity failure')
        report.update(active=active,reverted=reverted,reactivated=reactivated,reversion_preservation=preservation,
                      original_preservation=compare(initial,final),final_integrity=final['integrity'],foreign_key_violations=final['fk'],
                      protected_files_unchanged=protected_files()==protected,status='success',production_sha256_after=archive.sha(archive.PRODUCTION))
        if not report['protected_files_unchanged']:raise ValueError('Unexpected runtime change to project files')
        report['production_byte_identical']=report['production_sha256_before']==report['production_sha256_after']
        report['decision']='GO for reader policy; NO-GO for immediate production execution: writer intentionally copy-only and separate authorization required'
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
    finally:report['finished_utc']=archive.now();save()
    print(json.dumps({k:report[k] for k in ('status','batch_id','baseline_records','import','later_persistence','decision','production_byte_identical')},indent=2))


if __name__=='__main__':main()
