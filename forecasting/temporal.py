"""Auditoría de alineación: comparar fuentes sin fusionar ni desplazar registros."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

from data_ingestion.openaq_archive import parse_manifest
from data_ingestion.visibility import connect_readonly


def alignment(archive, api, min_pairs=72, tolerance=1e-8):
    """shift significa archive[t] comparado con API[t+shift]."""
    candidates=[]
    for shift in (-2,-1,0,1,2):
        shifted=archive.copy()
        shifted.index=shifted.index+pd.Timedelta(hours=shift)
        pairs=pd.concat([shifted.rename('archive'),api.rename('api')],axis=1,sort=True).dropna()
        errors=(pairs['archive']-pairs['api']).abs()
        candidates.append({'shift_hours':shift,'pairs':len(pairs),
                           'distinct_archive_values':int(pairs['archive'].nunique()),
                           'matching_pairs':int((errors<=tolerance).sum()),
                           'match_fraction':float((errors<=tolerance).mean()) if len(pairs) else 0,
                           'mae':float(errors.mean()) if len(pairs) else None})
    eligible=[c for c in candidates if c['pairs']>=min_pairs and c['distinct_archive_values']>=10]
    best=min(eligible,key=lambda c:(-c['match_fraction'],c['mae'],abs(c['shift_hours']))) if eligible else None
    confident=best is not None and best['match_fraction']>=0.99
    status=('aligned_on_sample_only' if best['shift_hours']==0 else 'timestamp_mismatch') if confident else 'unverified'
    return {'status':status,'best_shift_hours':best['shift_hours'] if best else None,
            'candidates':candidates,'automatic_source_substitution_allowed':False,
            'scope':'overlap sample; does not certify aggregation, latency or future equivalence'}


def audit(db, manifest):
    metadata,records,rejected,outside=parse_manifest(manifest)
    if rejected:
        raise ValueError('La muestra tiene filas rechazadas')
    results=[]
    with closing(connect_readonly(db)) as conn:
        conn.execute('PRAGMA query_only=ON')
        for sid in sorted({r[0] for r in records}):
            values={}
            for sensor,instant,value,_,_ in records:
                if sensor!=sid:continue
                time=pd.Timestamp(instant)
                if time in values and values[time]!=value:
                    raise ValueError('Muestra de archivo con valores conflictivos')
                values[time]=value
            archive=pd.Series(values,dtype=float).sort_index()
            rows=conn.execute("SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente='OpenAQ' AND sensor_id=? AND contaminante='pm25'",(sid,)).fetchall()
            api_values={}
            for instant,value,unit in rows:
                time=pd.Timestamp(instant)
                if time.tzinfo is None or time!=time.floor('h') or unit!='µg/m³':
                    raise ValueError('Fecha/unidad incompatible en API')
                time=time.tz_convert('UTC')
                if time in api_values:raise ValueError('Hora duplicada en API')
                api_values[time]=value
            api=pd.Series(api_values,dtype=float).sort_index()
            results.append({'sensor_id':sid,**alignment(archive,api)})
    return {'mode':'read_only_temporal_audit','manifest_sha256':hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
            'from_utc':metadata['from_utc'],'to_utc_exclusive':metadata['to_utc_exclusive'],
            'sensors':results,'automatic_source_substitution_allowed':False,
            'source_documentation':'https://docs.openaq.org/resources/measurements'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('data/aeris_air_quality.db'))
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists():parser.error('El reporte ya existe')
    result=audit(args.db,args.manifest)
    with args.output.open('x',encoding='utf8') as output:json.dump(result,output,indent=2,ensure_ascii=False,allow_nan=False)
    for row in result['sensors']:print(row['sensor_id'],row['status'],row['best_shift_hours'])


if __name__=='__main__':main()
