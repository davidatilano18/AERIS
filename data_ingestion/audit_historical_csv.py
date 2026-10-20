"""Perfil del CSV local; no atribuye procedencia ni convierte horas sin evidencia."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def audit(path):
    path = Path(path)
    frame = pd.read_csv(path, encoding='utf-8-sig')
    required = {'clave_estacion','nombre_estacion','clave_contaminante','fecha','hora',
                'valor','unidades','latitud','longitud'}
    if not required <= set(frame.columns):
        raise ValueError(f'Columnas faltantes: {sorted(required-set(frame.columns))}')
    hours = pd.to_numeric(frame['hora'], errors='coerce')
    dates = pd.to_datetime(frame['fecha'], errors='coerce')
    values = pd.to_numeric(frame['valor'], errors='coerce')
    valid_time = dates.notna() & hours.between(0,23) & hours.eq(hours.round())
    frame['timestamp_unzoned'] = dates+pd.to_timedelta(hours.where(valid_time), unit='h')
    groups = []
    for (station,pollutant,unit), group in frame.groupby(['clave_estacion','clave_contaminante','unidades'], dropna=False):
        times = group['timestamp_unzoned'].dropna()
        unique = times.nunique()
        expected = int((times.max()-times.min()).total_seconds()/3600)+1 if unique else 0
        group_values = values.loc[group.index]
        groups.append({'station':station,'name':str(group['nombre_estacion'].iloc[0]),
                       'pollutant':pollutant,'unit':str(unit),'records':len(group),
                       'first_unzoned':str(times.min()),'last_unzoned':str(times.max()),
                       'unique_hours':int(unique),'duplicates':int(len(times)-unique),
                       'expected_hours_within_observed_span':expected,
                       'coverage_pct_within_observed_span':round(100*unique/expected,2) if expected else None,
                       'zeros':int(group_values.eq(0).sum()),'negatives':int(group_values.lt(0).sum()),
                       'minimum':float(group_values.min()),'maximum':float(group_values.max())})
    lat = pd.to_numeric(frame['latitud'],errors='coerce')
    lon = pd.to_numeric(frame['longitud'],errors='coerce')
    return {'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'records':len(frame),'columns':list(frame.columns.drop('timestamp_unzoned')),
            'first_date':str(dates.min()),'last_date':str(dates.max()),
            'hours_present':sorted(int(v) for v in hours.dropna().unique()),
            'invalid_timestamps':int((~valid_time).sum()),'groups':groups,
            'apparent_swapped_coordinate_rows':int((lat.between(-102,-98)&lon.between(19,22)).sum()),
            'provenance_verified':False,'timezone_verified_for_this_file':False,
            'import_decision':'quarantine_until_original_url_content_and_time_convention_verified',
            'candidate_catalog_url':'https://www.datos.gob.mx/dataset/concentraciones_validadas_calidad_aire_entidad_federativa/resource/ae977e2f-78fb-4b2d-87fc-2eeb3753d050',
            'limitations':['El catálogo describe un recurso compatible, pero no se ha verificado identidad por hash.',
                           'Los porcentajes se refieren al rango observado, no garantizan cobertura anual.',
                           'No se asigna zona ni se mezcla este CSV con SQLite.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('data/queretaro_015.csv'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists():
        parser.error('El reporte ya existe')
    report=audit(args.input)
    with args.output.open('x',encoding='utf-8') as output:
        json.dump(report,output,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'output':str(args.output),'records':report['records'],'groups':len(report['groups'])}))


if __name__=='__main__':
    main()
