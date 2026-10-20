"""Audita indicadores almacenados frente a v2; v1 se investiga como hipotesis."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .quality_versioned import calculate,utc
from .production_preflight import sha


def audit(path):
    path=Path(path).resolve();differences=[];hypotheses={
        'previous_only_any_gap':0,'next_only_any_gap':0,
        'both_neighbors_any_gap':0,'both_neighbors_exact_hour':0}
    examined=0
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        for (sid,) in conn.execute("SELECT DISTINCT sensor_id FROM mediciones WHERE fuente='OpenAQ' ORDER BY sensor_id"):
            rows=conn.execute('''SELECT m.fecha_utc,m.valor,m.unidad,q.es_cero,q.es_extremo,q.salto_abrupto,
                q.requiere_revision,q.version_reglas FROM mediciones m JOIN calidad_mediciones q
                USING(fuente,sensor_id,fecha_utc,contaminante) WHERE m.fuente='OpenAQ' AND m.sensor_id=?
                AND m.contaminante='pm25' ORDER BY julianday(m.fecha_utc)''',(sid,)).fetchall()
            computed=calculate([r[:3] for r in rows])
            for i,(row,new) in enumerate(zip(rows,computed)):
                prev=rows[i-1] if i else None;nxt=rows[i+1] if i+1<len(rows) else None
                previous_delta=abs(row[1]-prev[1]) if prev else None
                next_delta=abs(row[1]-nxt[1]) if nxt else None
                previous_hours=(utc(row[0])-utc(prev[0])).total_seconds()/3600 if prev else None
                next_hours=(utc(nxt[0])-utc(row[0])).total_seconds()/3600 if nxt else None
                left=previous_delta is not None and previous_delta>=100
                right=next_delta is not None and next_delta>=100
                for name,jump in [('previous_only_any_gap',left),('next_only_any_gap',right),
                                  ('both_neighbors_any_gap',left or right),
                                  ('both_neighbors_exact_hour',(left and previous_hours==1) or (right and next_hours==1))]:
                    flags=(int(row[1]==0),int(row[1]>100),int(jump),int(row[1]<0 or row[1]>100 or jump))
                    hypotheses[name]+=int(tuple(row[3:7])!=flags)
                examined+=1
                if tuple(row[3:7])!=new['flags']:
                    differences.append({'sensor_id':sid,'timestamp_utc':row[0],'value':row[1],'unit':row[2],
                        'stored_version':row[7],'stored_flags':list(row[3:7]),'v2_flags':list(new['flags']),
                        'previous':None if prev is None else {'timestamp_utc':prev[0],'value':prev[1],
                            'elapsed_hours':previous_hours,'absolute_delta':previous_delta},
                        'next':None if nxt is None else {'timestamp_utc':nxt[0],'value':nxt[1],
                            'elapsed_hours':next_hours,'absolute_delta':next_delta},
                        'explanation':'Stored jump matches next-neighbor edge; v2 uses only previous neighbor',
                        'current_hourly_gap_explains_difference':previous_hours!=1 or next_hours!=1})
    return {'schema':'aeris-qc-rule-difference-audit-v1','database_sha256':sha(path),'rows_examined':examined,
        'flags_order':['es_cero','es_extremo','salto_abrupto','requiere_revision'],
        'v2_differences':differences,'hypothesis_mismatch_counts':hypotheses,
        'historical_v1_source_recovered':False,
        'conclusion':'All stored OpenAQ flags match a bidirectional-neighbor hypothesis; v2 is causal, previous-only',
        'limitations':['Historical v1 code and original evaluation context unavailable',
            'No observed case distinguishes v1 gap-aware from gap-unaware bidirectional policy',
            'Matching all rows supports behavior but does not establish historical intent or exclude past edits'],
        'original_database_writes':0}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('data/aeris_air_quality.db'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with args.output.open('x',encoding='utf8') as out:json.dump(audit(args.db),out,ensure_ascii=False,indent=2)
