"""Resumen de MAE y RMSE ponderados por muestras de ventanas disjuntas."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def summarize(paths):
    summaries=[]
    for path in paths:
        path=Path(path)
        report=json.loads(path.read_text(encoding='utf-8'))
        results=report['results']
        for horizon in sorted({r['horizon_hours'] for r in results}):
            rows=[r for r in results if r['horizon_hours']==horizon and r['status']=='ok']
            ordered=sorted(rows,key=lambda r:r['issue_start'])
            for previous,current in zip(ordered,ordered[1:]):
                if previous['issue_end_exclusive'] > current['issue_start']:
                    raise ValueError('Ventanas superpuestas: no agregarlas como muestras independientes')
            if not rows:
                summaries.append({'sensor_id':report['input']['sensor_id'],'horizon_hours':horizon,
                                  'status':'insufficient_data','metrics':{}})
                continue
            methods=set(rows[0]['metrics'])
            if any(set(r['metrics'])!=methods for r in rows):
                raise ValueError('Los métodos cambian entre ventanas')
            total=sum(r['test_samples'] for r in rows)
            candidates=sum(r['candidate_emissions'] for r in results if r['horizon_hours']==horizon)
            metrics={name:{
                'mae':sum(r['metrics'][name]['mae']*r['test_samples'] for r in rows)/total,
                'rmse':math.sqrt(sum(r['metrics'][name]['rmse']**2*r['test_samples'] for r in rows)/total)
            } for name in sorted(methods)}
            references=methods & {'persistencia','promedio_24h','estacional_24h'}
            best_reference=min(references,key=lambda name:metrics[name]['mae'])
            summaries.append({'sensor_id':report['input']['sensor_id'],'source':report['input']['source'],
                              'horizon_hours':horizon,'status':'ok','test_samples':total,
                              'coverage_pct':100*total/candidates,'metrics':metrics,
                              'best_reference':best_reference,
                              'best_method':min(methods,key=lambda name:metrics[name]['mae']),
                              'successful_folds':len(rows),
                              'input_report':str(path),'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'aggregation':'MAE weighted by n; RMSE sqrt(weighted MSE)',
            'interpretation':'Retrospective development folds; not an untouched final holdout',
            'summaries':summaries}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists():
        parser.error('El reporte de salida ya existe')
    result=summarize(args.reports)
    with args.output.open('x',encoding='utf-8') as target:
        json.dump(result,target,ensure_ascii=False,indent=2,allow_nan=False)
    for row in result['summaries']:
        print(row['sensor_id'],row['horizon_hours'],row['status'],
              {k:round(v['mae'],4) for k,v in row['metrics'].items()})


if __name__=='__main__':
    main()
