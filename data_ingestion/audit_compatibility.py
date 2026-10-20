"""Auditoria estricta, sin red, desplazamientos ni modificaciones a SQLite."""
import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def archive_inventory(manifest):
    evidence=json.loads(Path(manifest).read_text(encoding='utf8'))
    sensors={int(k):v for k,v in evidence['sensor_locations'].items()}
    selected=naive=mismatched=0
    first=last=None
    schemas=set()
    for item in evidence['files']:
        path=Path(item['path'])
        if not path.is_absolute():path=ROOT/path
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Archivo Archive alterado: '+str(path))
        with gzip.open(path,'rt',encoding='utf8',newline='') as handle:
            reader=csv.DictReader(handle);schemas.add(tuple(reader.fieldnames or []))
            for row in reader:
                sid=int(row['sensors_id'])
                if sid not in sensors or row['parameter']!='pm25':continue
                selected+=1
                mismatched+=int(int(row['location_id'])!=sensors[sid] or row['units']!='µg/m³')
                point=datetime.fromisoformat(row['datetime'].replace('Z','+00:00'))
                if point.tzinfo is None:naive+=1;continue
                point=point.astimezone(timezone.utc)
                first=min(first,point) if first else point
                last=max(last,point) if last else point
    return {'manifest':Path(manifest).name,'manifest_sha256':hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
            'verified_files':len(evidence['files']),'schemas':[list(s) for s in sorted(schemas)],
            'selected_pm25_raw_rows_including_partition_edges':selected,
            'identity_or_unit_mismatches':mismatched,'timestamps_without_timezone':naive,
            'first_reported_utc':first.isoformat() if first else None,'last_reported_utc':last.isoformat() if last else None,
            'explicit_hourly_period_and_aggregation_available':False}


def audit(db,manifest):
    db,manifest=Path(db).resolve(),Path(manifest).resolve()
    evidence=json.loads(manifest.read_text(encoding='utf8'))
    files=[]
    for item in evidence['files']:
        path=Path(item['path'])
        if not path.is_absolute():path=ROOT/path
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=item['sha256']:raise ValueError('Archivo Archive alterado: '+str(path))
        with gzip.open(path,'rt',encoding='utf8',newline='') as handle:
            reader=csv.DictReader(handle)
            columns=reader.fieldnames
            count=sum(1 for _ in reader)
        files.append({'url':item['url'],'sha256':digest,'columns':columns,'records':count})
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
        sources=[dict(zip(('source','sensor_id','year','records','first_utc','last_utc'),row)) for row in conn.execute(
            '''SELECT fuente,sensor_id,substr(fecha_utc,1,4),COUNT(*),MIN(fecha_utc),MAX(fecha_utc)
               FROM mediciones WHERE contaminante='pm25' GROUP BY 1,2,3 ORDER BY 1,2,3''')]
        has_observations=conn.execute("SELECT 1 FROM sqlite_master WHERE name='observaciones_api'").fetchone()
        verified=conn.execute('SELECT COUNT(*) FROM observaciones_api').fetchone()[0] if has_observations else 0
    return {'schema':'aeris-strict-source-audit-v1','audited_at_utc':datetime.now(timezone.utc).isoformat(),
        'database_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'sources':sources,'archive_files':files,'api_observation_receipts':verified,
        'overlap_archive_inventory':archive_inventory(manifest),
        'verified_comparable_pairs':0,'numeric_comparison_performed':False,
        'status':'unverified_keep_sources_separate','automatic_source_substitution_allowed':False,
        'historical_2025_recent_2026_training_compatibility':'not_demonstrated',
        'reasons':['Archive CSV does not supply explicit period start/end and aggregation evidence',
                   'Legacy API SQL rows do not preserve original period payloads',
                   'Matching sensor, unit, timestamp or a better shifted fit does not prove equivalence'],
        'required_next_evidence':['Preserve authenticated API /hours responses and location sensor metadata',
            'Obtain authoritative Archive period and aggregation definitions tied to these files',
            'Compare only identical sensor/location/parameter/unit/UTC start/end/aggregation pairs',
            'Assess remaining value differences and instrumental continuity before any new release'],
        'documentation':['https://docs.openaq.org/resources/measurements',
                         'https://docs.openaq.org/aws/about',
                         'https://docs.openaq.org/using-the-api/dates-datetimes'],
        'documented_time_convention':'OpenAQ hourly datetimes are exclusive time-ending; explicit API datetimeFrom is a period start',
        'unproven_explanation':'Archive reported datetime versus API period start may explain the previous diagnostic; no inferred periods or shifts applied',
        'archive_operational_limitation':'AWS publication 72 hours after local day end cannot alone meet candidate maximum data age of 2 hours',
        'applied_time_shift_hours':0,'measurements_modified':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=ROOT/'data/aeris_air_quality.db')
    parser.add_argument('--manifest',type=Path,default=ROOT/'data/manifests/openaq_temporal_overlap_20260918_20260922.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--historical-manifest',type=Path,default=ROOT/'data/manifests/openaq_20250601_20251001.json')
    args=parser.parse_args()
    result=audit(args.db,args.manifest)
    result['historical_archive_inventory']=archive_inventory(args.historical_manifest)
    with args.output.open('x',encoding='utf8') as handle:json.dump(result,handle,ensure_ascii=False,indent=2)
    print(result['status'])


if __name__=='__main__':main()
