"""Planificación por defecto; entrenamiento solo con --train explícito."""
import argparse
import json
import platform
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import numpy as np

from .hourly import HORIZONS, FEATURES, load_series, build_dataset, evaluate

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT/'data'/'aeris_air_quality.db')
    parser.add_argument('--sensor', type=int, required=True)
    parser.add_argument('--source', default='OpenAQ')
    parser.add_argument('--quality', choices=['evaluated', 'all'], default='evaluated')
    parser.add_argument('--horizons', type=int, nargs='+', choices=HORIZONS, default=list(HORIZONS))
    parser.add_argument('--latency-hours', type=int, default=1)
    parser.add_argument('--start', required=True, help='Primera emisión de prueba ISO con zona UTC')
    parser.add_argument('--fold-days', type=int, default=7)
    parser.add_argument('--folds', type=int, default=3)
    parser.add_argument('--min-train', type=int, default=500)
    parser.add_argument('--min-test', type=int, default=100)
    parser.add_argument('--baseline-only', action='store_true', help='Calcular métricas solo de referencias')
    parser.add_argument('--train', action='store_true', help='Entrenar modelos seleccionados por ventana y evaluar')
    parser.add_argument('--models', nargs='+', choices=['random_forest','hist_gradient_boosting'],
                        default=['random_forest','hist_gradient_boosting'])
    parser.add_argument('--trees',type=int,default=150)
    parser.add_argument('--output', type=Path, help='Reporte JSON nuevo; nunca sobrescribe archivos')
    args = parser.parse_args(argv)
    if min(args.fold_days, args.folds, args.min_train, args.min_test,args.trees) < 1 or args.latency_hours < 0:
        parser.error('Ventanas y mínimos positivos; latencia no negativa')
    if args.train and args.baseline_only:
        parser.error('--train y --baseline-only son excluyentes')
    if args.output and args.output.exists():
        parser.error('--output ya existe; selecciona un archivo nuevo')
    try:
        start = pd.Timestamp(args.start)
        if start.tzinfo is None or start != start.floor('h'):
            raise ValueError('--start requiere zona explícita y hora exacta')
        series, metadata = load_series(args.db, args.sensor, args.source, args.quality)
        factories = {}
        model_config = None
        sklearn_version = None
        if args.train:
            import sklearn
            from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
            sklearn_version = sklearn.__version__
            configurations = {
                'random_forest':{'n_estimators':args.trees,'min_samples_leaf':3,
                                 'max_features':0.8,'random_state':42,'n_jobs':2},
                'hist_gradient_boosting':{'max_iter':150,'learning_rate':0.05,
                                         'max_leaf_nodes':15,'l2_regularization':1.0,
                                         'early_stopping':False,'random_state':42}}
            model_config = {name:configurations[name] for name in dict.fromkeys(args.models)}
            constructors={'random_forest':RandomForestRegressor,'hist_gradient_boosting':HistGradientBoostingRegressor}
            factories={name:(lambda name=name:constructors[name](**model_config[name])) for name in model_config}
        results = []
        for horizon in dict.fromkeys(args.horizons):
            table = build_dataset(series, horizon, args.latency_hours)
            for fold in range(args.folds):
                left = start + pd.Timedelta(days=fold*args.fold_days)
                right = left + pd.Timedelta(days=args.fold_days)
                if args.train or args.baseline_only:
                    result = evaluate(table, left, right, min_train=args.min_train,
                                      min_test=args.min_test,model_factories=factories)
                else:
                    from .hourly import split_period
                    train, test = split_period(table, left, right)
                    complete = test.dropna(subset=FEATURES+['target','persistencia','promedio_24h','estacional_24h'])
                    result = {'status': 'plan_only', 'issue_start': left.isoformat(),
                              'issue_end_exclusive': right.isoformat(),
                              'training_samples': len(train.dropna(subset=FEATURES+['target'])),
                              'candidate_emissions': len(test), 'test_samples': len(complete)}
                results.append({'horizon_hours': horizon, 'fold': fold+1, **result})
                if args.train:
                    print(f'Horizonte {horizon}h, ventana {fold+1}: {result["status"]}',file=sys.stderr,flush=True)
        report = {'mode': 'train' if args.train else 'baseline_only' if args.baseline_only else 'plan_only',
                  'input': metadata, 'latency_hours_assumed': args.latency_hours,
                  'features': FEATURES, 'model_config': model_config,
                  'versions': {'python': platform.python_version(), 'pandas': pd.__version__,
                               'numpy': np.__version__, 'scikit_learn': sklearn_version},
                  'evaluation': 'expanding_window_by_issue_time', 'results': results,
                  'limitations': ['Latencia fija supuesta; no representa disponibilidad histórica medida.',
                                  'Los valores actuales pueden incorporar correcciones posteriores a la emisión.',
                                  'Sin imputación; métricas condicionadas a muestras completas.',
                                  'Reporte retrospectivo; no produce un modelo operativo.']}
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(text+'\n')
        print(text)
        return 1 if any(r['status'] == 'insufficient_data' for r in results) else 0
    except (OSError, ValueError, sqlite3.Error, pd.errors.DatabaseError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
