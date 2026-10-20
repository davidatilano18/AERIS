"""Paquetes locales inmutables para selección congelada y evaluación futura."""
import argparse
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import joblib
import pandas as pd

from . import hourly
from .hourly import FEATURES, build_dataset, load_series
from .selection import select, reserve_holdout, validate_training_cutoff, sha
from data_ingestion import quality

ROOT=Path(__file__).resolve().parents[1]
REFERENCE_FEATURES={'persistencia':['persistencia'],'promedio_24h':['promedio_24h'],
                    'estacional_24h':['estacional_24h']}


class ReferenceModel:
    """Referencia sin parámetros aprendidos ni ajuste sobre el periodo de prueba."""
    def __init__(self,method):
        if method not in REFERENCE_FEATURES:raise ValueError('Referencia desconocida')
        self.method=method

    def predict(self,frame):return frame[self.method].to_numpy(dtype=float)


def dependencies():
    return {'python':platform.python_version(),'numpy':version('numpy'),
            'pandas':version('pandas'),'scikit-learn':version('scikit-learn'),
            'joblib':version('joblib')}


def contract():
    return {'id':'openaq-archive-reported-utc-hourly-v1','source':'OpenAQ-Archive',
            'timezone':'UTC','cadence_hours':1,'timestamp_semantics':'reported_archive_datetime_no_shift',
            'unit':'µg/m³','latency_hours_assumed':1,'automatic_cross_source_substitution':False}


def code_hashes():
    return {'hourly':sha(hourly.__file__),'quality':sha(quality.__file__)}


def write_bundle(folder,models,metadata):
    """Solo cargar paquetes locales de confianza; joblib no es un formato seguro para terceros."""
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    joblib.dump(models,folder/'estimators.joblib',compress=3)
    metadata={**metadata,'model_file_sha256':sha(folder/'estimators.joblib')}
    with (folder/'metadata.json').open('x',encoding='utf8') as target:
        json.dump(metadata,target,indent=2,ensure_ascii=False,allow_nan=False)
    return {'path':folder.name,'metadata_sha256':sha(folder/'metadata.json'),
            'model_sha256':metadata['model_file_sha256']}


def build_release(db,reports,output,release_version,training_cutoff,holdout_start,holdout_end,temporal_report):
    output=Path(output)
    if output.exists():raise ValueError('La versión ya existe; no se sobrescribe')
    frozen_at=datetime.now(timezone.utc).isoformat()
    selection=select(reports)
    holdout=reserve_holdout(selection,holdout_start,holdout_end,frozen_at)
    cutoff=validate_training_cutoff(selection,training_cutoff,holdout_start,frozen_at)
    temporal=json.loads(Path(temporal_report).read_text(encoding='utf8'))
    if temporal.get('automatic_source_substitution_allowed') is not False:
        raise ValueError('Se requiere auditoría temporal con separación explícita de fuentes')
    # Validar todos los fingerprints antes de crear una versión parcial.
    datasets={}
    for decision in selection['decisions']:
        sid=decision['sensor_id']
        if sid not in datasets:datasets[sid]=load_series(db,sid,source='OpenAQ-Archive')
        if datasets[sid][1]['input_sha256']!=decision['development_input_sha256']:
            raise ValueError('El insumo cambió respecto a la evaluación; reevaluar antes de seleccionar')
        if pd.Timestamp(datasets[sid][1]['end_utc'])>=pd.Timestamp(holdout_start):
            raise ValueError('La reserva contiene datos ya presentes en el insumo inspeccionado')
    output.mkdir(parents=True,exist_ok=False)
    for filename,value in [('selection.json',selection),('holdout_plan.json',holdout),('temporal_audit.json',temporal)]:
        with (output/filename).open('x',encoding='utf8') as target:json.dump(value,target,indent=2,ensure_ascii=False)
    from sklearn.ensemble import RandomForestRegressor,HistGradientBoostingRegressor
    constructors={'random_forest':RandomForestRegressor,'hist_gradient_boosting':HistGradientBoostingRegressor}
    entries=[]
    for decision in selection['decisions']:
        sid,horizon=decision['sensor_id'],decision['horizon_hours']
        series,metadata=datasets[sid]
        # Cortar antes de crear variables: no incorporar objetivos posteriores al cutoff.
        available=series.loc[series.index+pd.Timedelta(hours=1)<cutoff]
        table=build_dataset(available,horizon,latency_hours=1)
        train=table.loc[table['label_available_at']<cutoff].dropna(subset=FEATURES+['target'])
        if len(train)<500:raise ValueError('Muestras insuficientes para congelar los candidatos')
        models={name:ReferenceModel(name) for name in REFERENCE_FEATURES}
        for name,constructor in constructors.items():
            model=constructor(**decision['model_config'][name])
            model.fit(train[FEATURES],train['target'])
            models[name]=model
        manifest={'schema':'aeris-pm25-bundle-v1','release_version':release_version,
                  'sensor_id':sid,'horizon_hours':horizon,'created_at':frozen_at,
                  'selected_method':decision['selected_method'],'selection_reason':decision['reason'],
                  'validation_state':'candidate_pending_independent_test','operational_enabled':False,
                  'temporal_contract':contract(),'required_quality_version':quality.VERSION,
                  'features_by_method':{**REFERENCE_FEATURES,**{name:FEATURES for name in constructors}},
                  'development_metrics':decision['development'], 'model_config':decision['model_config'],
                  'selection_evidence':decision['evidence'],'selection_sha256':sha(output/'selection.json'),
                  'holdout_plan_sha256':sha(output/'holdout_plan.json'),
                  'temporal_audit_sha256':sha(output/'temporal_audit.json'),
                  'training':{'cutoff_exclusive':cutoff.isoformat(),'samples':len(train),
                              'first_emission':train.index.min().isoformat(),'last_emission':train.index.max().isoformat(),
                              'last_target':train['target_at'].max().isoformat(),
                              'last_label_available_at':train['label_available_at'].max().isoformat(),
                              'input':metadata},
                  'dependencies':dependencies(),'code_hashes':code_hashes(),
                  'max_data_age_hours':2,'max_training_age_days':90,
                  'limitations':['Fixed latency is assumed, not observed.',
                                 'Historical revisions may differ from values known at issuance.',
                                 'Development metrics are not final validation.']}
        entry=write_bundle(output/f'{sid}_{horizon}h',models,manifest)
        entries.append({'sensor_id':sid,'horizon_hours':horizon,**entry})
        print(f'Paquete {sid}/{horizon}h: {decision["selected_method"]}',flush=True)
    registry={'schema':'aeris-release-v1','version':release_version,'created_at':frozen_at,
              'selection_sha256':sha(output/'selection.json'),'holdout_plan_sha256':sha(output/'holdout_plan.json'),
              'temporal_audit_sha256':sha(output/'temporal_audit.json'),'entries':entries}
    with (output/'registry.json').open('x',encoding='utf8') as target:json.dump(registry,target,indent=2)
    return registry


def load_bundle(release,sensor_id,horizon):
    release=Path(release).resolve()
    registry=json.loads((release/'registry.json').read_text(encoding='utf8'))
    if registry['schema']!='aeris-release-v1':raise ValueError('Esquema de versión incompatible')
    found=[e for e in registry['entries'] if e['sensor_id']==sensor_id and e['horizon_hours']==horizon]
    if len(found)!=1:raise ValueError('No hay paquete único para estación/horizonte')
    entry=found[0]
    folder=(release/entry['path']).resolve()
    if folder.parent!=release:raise ValueError('Ruta de paquete inválida')
    if sha(folder/'metadata.json')!=entry['metadata_sha256'] or sha(folder/'estimators.joblib')!=entry['model_sha256']:
        raise ValueError('Integridad del paquete incorrecta')
    meta=json.loads((folder/'metadata.json').read_text(encoding='utf8'))
    if (meta['schema']!='aeris-pm25-bundle-v1' or meta['sensor_id']!=sensor_id or meta['horizon_hours']!=horizon
            or meta['model_file_sha256']!=entry['model_sha256'] or meta['release_version']!=registry['version']):
        raise ValueError('Metadatos del paquete incompatibles')
    for filename,key in [('selection.json','selection_sha256'),('holdout_plan.json','holdout_plan_sha256'),
                         ('temporal_audit.json','temporal_audit_sha256')]:
        if sha(release/filename)!=registry[key] or meta[key]!=registry[key]:
            raise ValueError('Política o evidencia alterada')
    if meta['dependencies']!=dependencies() or meta['code_hashes']!=code_hashes():
        raise ValueError('Versiones de dependencias o reglas incompatibles')
    return meta,folder


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=ROOT/'data'/'aeris_air_quality.db')
    parser.add_argument('--reports',type=Path,nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--training-cutoff',required=True)
    parser.add_argument('--holdout-start',required=True)
    parser.add_argument('--holdout-end',required=True)
    parser.add_argument('--temporal-report',type=Path,required=True)
    args=parser.parse_args(argv)
    build_release(args.db,args.reports,args.output,args.version,args.training_cutoff,
                  args.holdout_start,args.holdout_end,args.temporal_report)


if __name__=='__main__':main()
