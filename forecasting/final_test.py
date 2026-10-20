"""Evaluar un periodo previamente reservado; jamás seleccionar ni reentrenar con él."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .artifacts import load_bundle
from .hourly import FEATURES,load_series,build_dataset,split_period
from .selection import sha


def evaluate_reserved(release,db,now=None):
    release=Path(release)
    if (release/'final_test_consumed.json').exists():
        raise ValueError('La prueba final ya se consumió para esta versión')
    registry=json.loads((release/'registry.json').read_text(encoding='utf8'))
    plan=json.loads((release/'holdout_plan.json').read_text(encoding='utf8'))
    if sha(release/'holdout_plan.json')!=registry['holdout_plan_sha256']:
        raise ValueError('Reserva alterada')
    start,end=pd.Timestamp(plan['issue_start']),pd.Timestamp(plan['issue_end_exclusive'])
    if not pd.Timestamp(plan['frozen_at'])<start<end:raise ValueError('Reserva no prospectiva')
    clock=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:raise ValueError('Reloj sin zona')
    result={'release_version':registry['version'],'holdout_plan_sha256':registry['holdout_plan_sha256'],
            'issue_start':plan['issue_start'],'issue_end_exclusive':plan['issue_end_exclusive'],
            'status':'pending_observations','operational_validation':False,'results':[]}
    latest_target=end-pd.Timedelta(hours=1)+pd.Timedelta(hours=max(e['horizon_hours'] for e in registry['entries']))
    result['last_required_target_at']=latest_target.isoformat()
    if clock<latest_target+pd.Timedelta(hours=plan['latency_hours_assumed']):
        result['reason']='reserved_period_not_closed_or_targets_not_available'
        return result
    prepared=[]
    for entry in registry['entries']:
        sid,horizon=entry['sensor_id'],entry['horizon_hours']
        meta,folder=load_bundle(release,sid,horizon)
        if not pd.Timestamp(meta['training']['last_label_available_at'])<start:
            raise ValueError('Fuga de etiquetas de entrenamiento hacia la prueba final')
        series,information=load_series(db,sid,source=plan['source'])
        if information['quality_versions']!=[meta['required_quality_version']]:
            raise ValueError('Reglas de calidad incompatibles')
        table=build_dataset(series,horizon,plan['latency_hours_assumed'])
        _,test=split_period(table,start,end)
        methods=list(meta['features_by_method'])
        required=list(dict.fromkeys(FEATURES+[f for cols in meta['features_by_method'].values() for f in cols]+['target']))
        cohort=test.dropna(subset=required)
        n=len(cohort)
        row={'sensor_id':sid,'horizon_hours':horizon,'selected_method':meta['selected_method'],
             'candidate_emissions':len(test),'test_samples':n,'coverage_pct':100*n/len(test),
             'metrics':{}}
        if n<plan['minimum_samples_per_station_horizon'] or row['coverage_pct']<plan['minimum_coverage_pct']:
            result['results'].append({**row,'status':'insufficient_data'})
            continue
        result['results'].append({**row,'status':'ready_not_scored'})
        prepared.append((meta,folder,cohort))
    # No revelar métricas parciales mientras falten otras estaciones/horizontes.
    if len(prepared)!=len(registry['entries']):
        result['reason']='insufficient_native_source_observations'
        result['selection_changed']=False
        return result
    for row,(meta,folder,cohort) in zip(result['results'],prepared):
        methods=list(meta['features_by_method'])
        models=joblib.load(folder/'estimators.joblib')
        actual=cohort['target'].to_numpy(dtype=float)
        for method in methods:
            predicted=np.asarray(models[method].predict(cohort[meta['features_by_method'][method]]),dtype=float)
            if predicted.shape!=actual.shape or not np.isfinite(predicted).all():raise ValueError('Salida no finita')
            errors=actual-predicted
            row['metrics'][method]={'mae':float(np.abs(errors).mean()),'rmse':float(np.sqrt(np.mean(errors**2)))}
        row['status']='evaluated_frozen_methods'
    result['status']='independent_retrospective_test_evaluated'
    result['selection_changed']=False
    result['limitation']='Assumed latency and source revisions prevent a claim of live operational validation.'
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--db',type=Path,default=Path('data/aeris_air_quality.db'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists():parser.error('El resultado ya existe')
    result=evaluate_reserved(args.release,args.db)
    if result['status']=='independent_retrospective_test_evaluated':
        # Marcador exclusivo: el mismo release no permite consumir de nuevo la prueba final.
        with (args.release/'final_test_consumed.json').open('x',encoding='utf8') as target:
            json.dump({'evaluated_at':datetime.now(timezone.utc).isoformat(),
                       'holdout_plan_sha256':result['holdout_plan_sha256'],'result':result},target,indent=2)
    with args.output.open('x',encoding='utf8') as target:json.dump(result,target,indent=2,ensure_ascii=False,allow_nan=False)
    print(result['status'])
    return int(result['status']=='pending_observations')


if __name__=='__main__':raise SystemExit(main())
