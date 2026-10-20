"""Selección conservadora solo con ventanas de desarrollo; no certifica validación final."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from .hourly import FEATURES
from .summarize_evaluations import summarize

POLICY={'version':'aeris-selection-v1','minimum_mae_improvement':0.05,
        'minimum_coverage_pct':70,'minimum_test_samples':500,'minimum_folds':3,
        'minimum_fold_wins':2,'rmse_must_not_worsen':True,
        'interpretation':'engineering threshold, not statistical significance'}
REFERENCES=('persistencia','promedio_24h','estacional_24h')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select(paths):
    reports={}
    for path in paths:
        report=json.loads(Path(path).read_text(encoding='utf8'))
        sid=report['input']['sensor_id']
        if sid in reports:raise ValueError('Estación duplicada')
        if (report['input']['source']!='OpenAQ-Archive' or report['input']['quality_policy']!='evaluated'
                or report['input']['quality_versions']!=['aeris_qc_v2']
                or report['features']!=FEATURES or report['mode']!='train'
                or report['latency_hours_assumed']!=1):
            raise ValueError('Reporte no compatible con el contrato de entrenamiento')
        if set(report['model_config'])!={'random_forest','hist_gradient_boosting'}:
            raise ValueError('Faltan modelos comparados')
        reports[sid]=(Path(path),report)
    decisions=[]
    for summary in summarize(paths)['summaries']:
        if summary['status']!='ok':raise ValueError('No hay evaluación utilizable')
        sid,horizon=summary['sensor_id'],summary['horizon_hours']
        path,report=reports[sid]
        rows=[r for r in report['results'] if r['horizon_hours']==horizon and r['status']=='ok']
        baseline=min(REFERENCES,key=lambda name:summary['metrics'][name]['mae'])
        evidence=[]
        for name in ('random_forest','hist_gradient_boosting'):
            base=summary['metrics'][baseline]
            metric=summary['metrics'][name]
            gain=(base['mae']-metric['mae'])/base['mae'] if base['mae']>0 else 0
            wins=sum(r['metrics'][name]['mae']<r['metrics'][baseline]['mae'] for r in rows)
            passes=(gain>=POLICY['minimum_mae_improvement'] and metric['rmse']<=base['rmse']
                    and wins>=POLICY['minimum_fold_wins']
                    and len(rows)>=POLICY['minimum_folds']
                    and summary['coverage_pct']>=POLICY['minimum_coverage_pct']
                    and summary['test_samples']>=POLICY['minimum_test_samples'])
            evidence.append({'method':name,'mae_improvement_fraction':gain,'fold_wins':wins,'passes_policy':passes})
        passing=[e['method'] for e in evidence if e['passes_policy']]
        chosen=min(passing,key=lambda name:summary['metrics'][name]['mae']) if passing else baseline
        decisions.append({'sensor_id':sid,'horizon_hours':horizon,'source':'OpenAQ-Archive',
                          'selected_method':chosen,'reference_method':baseline,'status':'exploratory_candidate',
                          'reason':'model_passes_development_rule' if passing else 'simple_reference_no_convincing_model',
                          'evidence':evidence,'development':summary,'report_path':str(path),
                          'report_sha256':sha(path),'model_config':report['model_config'],
                          'development_input_sha256':report['input']['input_sha256'],
                          'last_development_target_at':max(r['last_target_at'] for r in rows),
                          'last_development_label_available_at':
                              (max(pd.Timestamp(r['last_target_at']) for r in rows)+pd.Timedelta(hours=1)).isoformat()})
    return {'policy':POLICY,'final_validation_status':'pending_independent_observations',
            'decisions':decisions}


def reserve_holdout(selection, start, end, frozen_at):
    start,end,frozen_at=map(pd.Timestamp,(start,end,frozen_at))
    if any(t.tzinfo is None or t!=t.floor('h') for t in (start,end)) or frozen_at.tzinfo is None:
        raise ValueError('Fechas UTC explícitas y ventanas horarias requeridas')
    if not frozen_at<start<end:raise ValueError('La reserva debe ser prospectiva respecto a su congelación')
    if any(pd.Timestamp(d['last_development_label_available_at'])>=start for d in selection['decisions']):
        raise ValueError('Etiquetas de desarrollo invaden la reserva')
    return {'schema':'aeris-holdout-v1','status':'reserved_not_evaluated','independence':'prospective_reserved',
            'issue_start':start.isoformat(),'issue_end_exclusive':end.isoformat(),'frozen_at':frozen_at.isoformat(),
            'source':'OpenAQ-Archive','latency_hours_assumed':1,
            'minimum_samples_per_station_horizon':500,'minimum_coverage_pct':70,
            'rules':['Freeze selection and hyperparameters before first emission.',
                     'Never reselect using this final test; future revisions require a new holdout.',
                     'Compare all methods on the exact same complete emissions.',
                     'Final results require observed targets and a frozen release; unavailable periods stay pending.',
                     'No claim of live data availability: timestamp latency is assumed, not measured.']}


def validate_training_cutoff(selection,cutoff,holdout_start,frozen_at):
    cutoff,start,frozen=map(pd.Timestamp,(cutoff,holdout_start,frozen_at))
    if any(t.tzinfo is None for t in (cutoff,start,frozen)):
        raise ValueError('Cortes de entrenamiento con zona explícita requeridos')
    latest=max(pd.Timestamp(d['last_development_label_available_at']) for d in selection['decisions'])
    if not latest<cutoff<=frozen or cutoff>=start:
        raise ValueError('El corte debe seguir a las etiquetas de selección, preceder la prueba y no ser futuro')
    return cutoff
