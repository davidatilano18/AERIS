"""Offline May-2025 Archive rehearsal. Production is opened read-only, never imported into."""
import csv
import gzip
import hashlib
import io
import json
import math
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_ingestion import openaq_archive as archive
from data_ingestion.catalog import load_catalog
from data_ingestion.plan_recovery import utc_hour, stamp
from data_ingestion.quality_versioned import verify_current

SELECTED = {235225: (1352676, 24), 235234: (1352681, 24), 480392: (2694071, 23)}
PRODUCTION = ROOT/'data/aeris_air_quality.db'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def encoded(value): return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)


def validate_row(row, location, sensor, metadata, catalog):
    if int(row['location_id']) != location or int(row['sensors_id']) != sensor:
        raise ValueError('Station/sensor identity mismatch')
    parameters = [s['parameter'] for s in metadata['sensors'] if s['id'] == sensor]
    if len(parameters) != 1 or parameters[0]['name'] != 'pm25' or parameters[0]['units'] != 'µg/m³':
        raise ValueError('Sensor parameter metadata mismatch')
    if row['parameter'] != 'pm25' or row['units'] != 'µg/m³':
        raise ValueError('Pollutant/unit mismatch')
    if metadata['id'] != location or catalog['location_id'] != location:
        raise ValueError('Location metadata mismatch')
    for name, column, field in [('latitude', 'lat', 'lat'), ('longitude', 'lon', 'lon')]:
        # Only numerical representation precision, never geographic reassignment.
        if not math.isclose(float(row[column]), float(metadata['coordinates'][name]), abs_tol=1e-8, rel_tol=0):
            raise ValueError('Coordinates do not match downloaded metadata')
        if not math.isclose(float(row[column]), float(catalog[field]), abs_tol=1e-8, rel_tol=0):
            raise ValueError('Coordinates do not match local catalogue')
    instant = utc_hour(row['datetime'])
    original = datetime.fromisoformat(row['datetime'])
    if original.utcoffset() != instant.astimezone(ZoneInfo(metadata['timezone'])).utcoffset():
        raise ValueError('Explicit offset disagrees with location timezone')
    if not utc_hour('2025-05-01T07:00:00Z') <= instant <= utc_hour('2025-05-02T06:00:00Z'):
        raise ValueError('Outside approved historical sample')
    value = float(row['value'])
    if not math.isfinite(value) or value < 0:
        raise ValueError('Non-finite/negative candidate requires separate review')
    return {'sensor_id':sensor, 'location_id':location, 'source':archive.SOURCE,
            'pollutant':'pm25', 'unit':row['units'], 'value':value, 'original':row,
            'utc':stamp(instant), 'timezone':metadata['timezone'],
            'interval_start_utc':None, 'interval_end_utc':None, 'aggregation':'not_declared_in_archive'}


def read_snapshot(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        content = {t: Counter(encoded(tuple(r)) for r in conn.execute('SELECT * FROM "'+t.replace('"','""')+'"')) for t in tables}
        schema = list(conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
        return {'tables':content, 'schema':schema, 'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0],
                'fk':[list(r) for r in conn.execute('PRAGMA foreign_key_check')]}


def compare(before, after):
    return {t:{'original_rows':sum(rows.values()),
               'missing_or_changed':sum((rows-after['tables'].get(t,Counter())).values()),
               'added_rows':sum((after['tables'].get(t,Counter())-rows).values()),
               'original_rows_sha256':hashlib.sha256(encoded(sorted(rows.items())).encode()).hexdigest()}
            for t,rows in before['tables'].items()}


def require_preserved(before, after):
    comparison = compare(before, after)
    if after['integrity'] != 'ok' or after['fk'] or any(v['missing_or_changed'] for v in comparison.values()):
        raise ValueError('Critical integrity/preservation failure')
    if before['schema'] != after['schema']:
        raise ValueError('Unexpected schema change in historical rehearsal')
    return comparison


def isolated_import(manifest, db, isolated_root):
    isolated_root = Path(isolated_root).resolve(); db = Path(db).resolve()
    if db == PRODUCTION.resolve() or not db.is_relative_to(isolated_root) or not db.is_file():
        raise ValueError('Import destination must be an existing isolated copy')
    # Reuse the existing importer unchanged. Its cache and backups must stay isolated.
    with patch.object(archive, 'ROOT', isolated_root), patch.object(archive, 'get_bytes', side_effect=AssertionError('Offline rehearsal')):
        return archive.import_manifest(manifest, db)


def protected_files():
    files = [ROOT/'app.py', ROOT/'data/queretaro_015.csv']
    for folder in ('data_ingestion','forecasting','models','aeris_web','templates','static/v2'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return {str(p.relative_to(ROOT)):sha(p) for p in files if p.exists()}


def main():
    folder = Path(tempfile.mkdtemp(prefix='tmp_aeris_archive_rehearsal_', dir=ROOT/'reports'))
    report = {'started_at_utc':datetime.now(timezone.utc).isoformat(), 'temporary_directory':str(folder),
              'status':'preparing', 'production':str(PRODUCTION), 'production_sha256_before':sha(PRODUCTION)}
    evidence = ROOT/'reports/aeris_archive_import_dry_run.json'
    def save(): evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    save(); protected = protected_files()
    try:
        research = json.loads((ROOT/'reports/aeris_source_probe_manifest.json').read_text(encoding='utf-8'))
        entries = {r['label']:r for r in research['requests'] if r.get('status') == 200 and r.get('path') and not r.get('truncated')}
        def raw(label):
            entry = entries[label]; path = Path(entry['path']).resolve()
            if not path.is_relative_to(Path(research['temporary_directory']).resolve()) or sha(path) != entry['captured_sha256']:
                raise ValueError('Research sample path/checksum mismatch')
            return path.read_bytes(), entry
        catalog = load_catalog(); candidates = []; files = []
        cache = folder/'data/raw/openaq_archive'; cache.mkdir(parents=True)
        metadata_files = {}
        for location,(sid,count) in SELECTED.items():
            b, entry = raw(f'archive_day_{location}_20250501')
            expected_url = archive.BUCKET+f'records/csv.gz/locationid={location}/year=2025/month=05/location-{location}-20250501.csv.gz'
            if entry['url'] != expected_url: raise ValueError('Unexpected provenance URL')
            md, md_entry = raw('api_location_'+str(location))
            metadata = json.loads(md)['results'][0]
            metadata_files[str(location)] = {'sha256':md_entry['captured_sha256'], 'url':md_entry['url'],
                                           'requested_at_utc':md_entry['requested_at_utc']}
            rows = list(csv.DictReader(io.StringIO(gzip.decompress(b).decode('utf-8-sig'))))
            selected = [r for r in rows if r['parameter'] == 'pm25']
            if len(selected) != count: raise ValueError('Candidate count differs from approved sample')
            for number,row in enumerate(rows,2):
                if row['parameter'] != 'pm25': continue
                candidate = validate_row(row, location, sid, metadata, catalog[sid])
                candidate.update(file_sha256=entry['captured_sha256'], row_number=number)
                candidates.append(candidate)
            destination = cache/(entry['captured_sha256']+'.csv.gz')
            destination.write_bytes(b)
            files.append({'location_id':location,'url':entry['url'],'sha256':entry['captured_sha256'],
                          'path':str(destination.relative_to(folder)),'bytes':len(b)})
        keys = [(r['sensor_id'],r['utc']) for r in candidates]
        if len(candidates) != 71 or len(set(keys)) != 71: raise ValueError('Expected 71 unique candidates')
        report.update(candidates=candidates, candidate_count=len(candidates), metadata_evidence=metadata_files,
                      skipped_non_pm25_rows=sum(len(list(csv.DictReader(io.StringIO(gzip.decompress((cache/(f['sha256']+'.csv.gz')).read_bytes()).decode('utf-8-sig'))))) for f in files)-71)
        # SQLite Online Backup API: coherent snapshot even if the normal scheduler remains active.
        baseline = folder/'baseline.db'; working = folder/'rehearsal.db'
        with closing(sqlite3.connect(PRODUCTION.resolve().as_uri()+'?mode=ro', uri=True)) as src:
            src.execute('PRAGMA query_only=ON')
            with closing(sqlite3.connect(baseline)) as dst: src.backup(dst)
        initial = read_snapshot(baseline)
        if initial['integrity'] != 'ok' or initial['fk']: raise ValueError('Initial snapshot failed integrity checks')
        baseline_hash = sha(baseline)
        with closing(sqlite3.connect(baseline.as_uri()+'?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(working)) as dst: src.backup(dst)
        require_preserved(initial, read_snapshot(working))
        initial_rows = [json.loads(r) for r in initial['tables']['mediciones']]
        semantic = []; exact = []; locations = {sid:m['location_id'] for sid,m in catalog.items()}
        for candidate in candidates:
            for row in initial_rows:
                source,sid,time,param,value,unit = row
                if param != 'pm25' or locations.get(sid) != candidate['location_id'] or stamp(utc_hour(time)) != candidate['utc']: continue
                target = exact if source == archive.SOURCE and sid == candidate['sensor_id'] else semantic
                target.append({'candidate':candidate['utc'],'sensor_id':sid,'source':source,
                               'same_value_and_unit':value == candidate['value'] and unit == candidate['unit']})
        report.update(initial={'database_sha256':sha(working),'baseline_sha256':baseline_hash,
                    'records':sum(initial['tables']['mediciones'].values()),'integrity':initial['integrity'],
                    'foreign_key_violations':initial['fk']}, exact_existing=exact, possible_semantic_duplicates=semantic)
        save()
        if exact or semantic: raise ValueError('Unexpected duplicate identity requires review before rehearsal import')
        manifest = {'format':'aeris-openaq-archive-v1','source':archive.SOURCE,
                    'downloaded_at_utc':min(entries[f'archive_day_{loc}_20250501']['requested_at_utc'] for loc in SELECTED),
                    'from_utc':'2025-05-01T07:00:00Z','to_utc_exclusive':'2025-05-02T07:00:00Z',
                    'sensor_locations':{str(sid):loc for loc,(sid,_) in SELECTED.items()}, 'files':files,
                    'timestamp_semantics':'reported_archive_datetime_no_shift; interval boundaries unknown'}
        manifest_path = folder/'manifest.json'; manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        report['first_import'] = isolated_import(manifest_path, working, folder)
        first = read_snapshot(working); report['first_preservation'] = require_preserved(initial, first)
        first_backup = read_snapshot(report['first_import']['backup'])
        if first_backup != initial: raise ValueError('First importer backup differs from baseline')
        if report['first_import']['new_measurements'] != 71 or report['first_import']['conflicting_candidates'] or report['first_import']['rejected_rows']:
            raise ValueError('Unexpected first import result')
        report['second_import'] = isolated_import(manifest_path, working, folder)
        second = read_snapshot(working); report['second_preservation'] = require_preserved(first, second)
        second_backup = read_snapshot(report['second_import']['backup'])
        if second_backup != first: raise ValueError('Second importer backup differs from first result')
        report['backups_verified'] = {report[k]['backup']:{'sha256':sha(report[k]['backup']),
                                      'integrity':'ok','foreign_key_violations':[]} for k in ('first_import','second_import')}
        if report['second_import']['new_measurements'] or report['second_import']['identical'] != 71 or report['second_import']['conflicting_candidates']:
            raise ValueError('Import is not measurement-idempotent')
        for table in ('mediciones','calidad_mediciones','evaluaciones_calidad','observaciones_archivo','archivos_origen'):
            if first['tables'][table] != second['tables'][table]: raise ValueError('Idempotency failed: '+table)
        with closing(sqlite3.connect(working.as_uri()+'?mode=ro',uri=True)) as conn:
            conn.execute('PRAGMA query_only=ON')
            for candidate in candidates:
                stored=conn.execute("SELECT valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante='pm25'",
                                    (archive.SOURCE,candidate['sensor_id'],candidate['utc'])).fetchone()
                if stored != (candidate['value'],candidate['unit']): raise ValueError('Imported candidate key/value mismatch')
            report['imported_candidate_keys_values_verified']=len(candidates)
            report['current_quality_verified'] = {str(sid):verify_current(conn,sid,archive.SOURCE) for sid,_ in SELECTED.values()}
            report['new_quality'] = [list(r) for r in conn.execute("SELECT sensor_id,COUNT(*),SUM(es_cero),SUM(es_extremo),SUM(salto_abrupto),SUM(requiere_revision),version_reglas FROM calidad_mediciones WHERE fuente=? AND fecha_utc>=? AND fecha_utc<? GROUP BY sensor_id,version_reglas",(archive.SOURCE,manifest['from_utc'],manifest['to_utc_exclusive']))]
            report['quality_assessment_origins']=[list(r) for r in conn.execute('SELECT origen,COUNT(*) FROM evaluaciones_calidad GROUP BY origen')]
            report['historic_initial_vs_current_flag_differences']=conn.execute('''SELECT COUNT(*) FROM calidad_mediciones q
                JOIN evaluaciones_calidad e USING(fuente,sensor_id,fecha_utc,contaminante)
                WHERE q.fuente=? AND q.fecha_utc>=? AND e.origen='reevaluation' AND e.version_reglas='aeris_qc_v2'
                AND (q.es_cero!=e.es_cero OR q.es_extremo!=e.es_extremo OR q.salto_abrupto!=e.salto_abrupto OR q.requiere_revision!=e.requiere_revision)''',
                (archive.SOURCE,'2025-06-01T00:00:00Z')).fetchone()[0]
        # Use Flask's test client only against the isolated copy; no server or sync is started.
        import app
        from aeris_web.data import read_dashboard
        fixed_now = datetime.now(timezone.utc)
        with patch('aeris_web.data.utc_now',return_value=fixed_now):
            report['dashboard_counts'] = {}
            for source in ('OpenAQ','OpenAQ-Archive'):
                a=read_dashboard(baseline,source=source,period='all'); b=read_dashboard(working,source=source,period='all')
                delta=b['stats']['count']-a['stats']['count']
                if delta != (71 if source == archive.SOURCE else 0): raise ValueError('Historical source query mismatch')
                report['dashboard_counts'][source]={'before':a['stats']['count'],'after':b['stats']['count'],'delta':delta}
            with patch.object(app,'DB',working):
                client=app.app.test_client()
                urls=['/','/v2','/v2/datos','/api/v2/observations?source=OpenAQ-Archive&period=all',
                      '/api/v2/public?source=OpenAQ-Archive&period=all&station=1352676']
                report['endpoints']={url:client.get(url).status_code for url in urls}
                if any(s != 200 for s in report['endpoints'].values()): raise ValueError('Endpoint compatibility failed')
        if sha(baseline) != baseline_hash: raise ValueError('Pristine backup changed')
        if protected_files() != protected: raise ValueError('Protected project files changed')
        report.update(status='success',final_records=sum(second['tables']['mediciones'].values()),
                      final_integrity=second['integrity'],final_foreign_key_violations=second['fk'],
                      original_rows_preserved=all(v['missing_or_changed']==0 for v in compare(initial,second).values()),
                      protected_files_unchanged=True,production_sha256_after=sha(PRODUCTION))
        report['production_byte_identical_during_rehearsal']=report['production_sha256_before']==report['production_sha256_after']
    except Exception as exc:
        report.update(status='stopped',error_type=type(exc).__name__,error=str(exc),production_sha256_after=sha(PRODUCTION))
        save()
        raise
    finally:
        report['finished_at_utc']=datetime.now(timezone.utc).isoformat();save()
    print(json.dumps({k:report[k] for k in ('status','temporary_directory','initial','first_import','second_import','final_records','new_quality','production_byte_identical_during_rehearsal')},indent=2))


if __name__ == '__main__': main()
