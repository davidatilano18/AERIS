"""Inferencia sin Flask: decisiones explícitas de abstención, sin cambiar SQLite."""
import argparse
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .artifacts import load_bundle,contract
from .hourly import build_dataset,load_series


def issue_features(series,issued_at,horizon,latency=1):
    issued_at=pd.Timestamp(issued_at)
    if issued_at.tzinfo is None or issued_at!=issued_at.floor('h'):
        raise ValueError('Emisión con zona explícita y hora exacta requerida')
    issued_at=issued_at.tz_convert('UTC')
    # Nunca utilizar mediciones futuras o aún no disponibles según la latencia pactada.
    known=series.loc[series.index+pd.Timedelta(hours=latency)<=issued_at]
    index=pd.date_range(issued_at-pd.Timedelta(hours=168+latency),issued_at,freq='h')
    frame=build_dataset(known.reindex(index),horizon,latency)
    return frame.loc[[issued_at]],known


def predict(release,db,sensor_id,horizon,source,issued_at=None,mode='operational',now=None):
    """El modo replay exige emisión explícita; no equivale a un pronóstico operativo."""
    result={'status':'abstained','sensor_id':sensor_id,'horizon_hours':horizon,'source':source,'reasons':[]}
    reasons=result['reasons']
    try:
        if mode not in ('operational','replay'):raise ValueError('Modo inválido')
        current=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
        if current.tzinfo is None:raise ValueError('Reloj sin zona')
        if mode=='replay' and issued_at is None:raise ValueError('Replay requiere emisión explícita')
        issue=pd.Timestamp(issued_at) if issued_at is not None else current.floor('h')
        if issue.tzinfo is None or issue!=issue.floor('h') or issue>current:
            raise ValueError('Emisión inválida, no horaria o futura')
        if mode=='operational' and issue!=current.floor('h'):
            reasons.append('operational_issue_must_be_current_hour')
        meta,folder=load_bundle(release,sensor_id,horizon)
        result.update({'release_version':meta['release_version'],'method':meta['selected_method'],
                       'issued_at':issue.isoformat(),'target_at':(issue+pd.Timedelta(hours=horizon)).isoformat(),
                       'validation_state':meta['validation_state']})
        if meta['temporal_contract']!=contract() or source!=meta['temporal_contract']['source']:
            reasons.append('incompatible_temporal_source')
            return result
        if mode=='operational' and (meta['validation_state']!='final_verified' or not meta['operational_enabled']):
            reasons.append('independent_final_validation_pending')
        train_cutoff=pd.Timestamp(meta['training']['cutoff_exclusive'])
        if issue<train_cutoff:reasons.append('model_was_not_available_at_requested_emission')
        if mode=='operational' and issue-train_cutoff>pd.Timedelta(days=meta['max_training_age_days']):
            reasons.append('model_training_too_old')
        series,information=load_series(db,sensor_id,source=source)
        if information['quality_versions']!=[meta['required_quality_version']]:
            reasons.append('incompatible_quality_rules')
        row,known=issue_features(series,issue,horizon,meta['temporal_contract']['latency_hours_assumed'])
        observed=known.dropna()
        if observed.empty:reasons.append('no_available_measurements')
        else:
            last=observed.index.max()
            result['last_available_measurement']=last.isoformat()
            result['data_age_hours']=float((issue-last)/pd.Timedelta(hours=1))
            if issue-last>pd.Timedelta(hours=meta['max_data_age_hours']):reasons.append('stale_measurements')
        required=meta['features_by_method'][meta['selected_method']]
        if not np.isfinite(row[required].to_numpy(dtype=float)).all():
            reasons.append('missing_required_observations')
        if reasons:return result
        # Solo después de comprobar contrato, dependencias, reglas, edad e integridad.
        models=joblib.load(folder/'estimators.joblib')
        value=float(models[meta['selected_method']].predict(row[required])[0])
        if not np.isfinite(value) or value<0:
            reasons.append('invalid_model_output')
            return result
        result.update({'status':'exploratory_replay' if mode=='replay' else 'predicted',
                       'pm25_ug_m3':value,'operational':mode=='operational'})
        return result
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,sqlite3.Error,pd.errors.DatabaseError,ImportError) as exc:
        reasons.append('invalid_input_or_artifact')
        result['detail']=str(exc)
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--db',type=Path,default=Path('data/aeris_air_quality.db'))
    parser.add_argument('--sensor',type=int,required=True)
    parser.add_argument('--horizon',type=int,choices=[1,6,24],required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--issued-at')
    parser.add_argument('--mode',choices=['operational','replay'],default='operational')
    args=parser.parse_args(argv)
    result=predict(args.release,args.db,args.sensor,args.horizon,args.source,args.issued_at,args.mode)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return int(result['status']=='abstained')


if __name__=='__main__':raise SystemExit(main())
