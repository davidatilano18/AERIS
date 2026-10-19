"""Observed PM2.5 only: source-separated hourly series, no imputations or writes."""
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly

SOURCES={'OpenAQ':'OpenAQ API v3','OpenAQ-Archive':'OpenAQ Archive'}
PERIODS={'24h':24,'7d':168,'30d':720,'all':None}
MAX_ROWS=24000


def utc_now(): return datetime.now(timezone.utc)
def stamp(value): return value.isoformat(timespec='seconds').replace('+00:00','Z')


def instant(value):
    try: parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError): raise RuntimeError('Invalid stored timestamp') from None
    if parsed.tzinfo is None: raise RuntimeError('Timestamp without time zone')
    parsed=parsed.astimezone(timezone.utc)
    if parsed.minute or parsed.second or parsed.microsecond: raise RuntimeError('Non-hourly observation')
    return parsed


class TooManyRows(ValueError): pass


def read_dashboard(path,source='OpenAQ',station='all',period='7d',include_history=False):
    if source not in SOURCES or period not in PERIODS: raise ValueError('Filtro de fuente o periodo no válido.')
    path=Path(path).resolve()
    if not path.is_file(): raise FileNotFoundError('Base no disponible')
    now=utc_now(); end=now.replace(minute=0,second=0,microsecond=0)
    start=end-timedelta(hours=PERIODS[period]) if PERIODS[period] is not None else None
    with closing(connect_readonly(path)) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        catalog=read_catalog(conn)
        if station!='all' and (not station.isdigit() or int(station) not in catalog):
            raise ValueError('Estación no válida.')
        ids=list(catalog) if station=='all' else [int(station)]
        has_qc=bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calidad_mediciones'").fetchone())
        availability={}
        for row in conn.execute('''SELECT sensor_id,COUNT(*) count,MIN(fecha_utc) first,MAX(fecha_utc) latest
            FROM mediciones WHERE fuente=? AND contaminante='pm25' AND julianday(fecha_utc)<julianday(?)
            GROUP BY sensor_id''',(source,stamp(end))): availability[row['sensor_id']]=dict(row)
        flags='q.es_cero,q.es_extremo,q.salto_abrupto,q.requiere_revision,q.version_reglas' if has_qc else \
              'NULL es_cero,NULL es_extremo,NULL salto_abrupto,NULL requiere_revision,NULL version_reglas'
        join='LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if has_qc else ''
        conditions=['m.fuente=?',"m.contaminante='pm25'",'julianday(m.fecha_utc)<julianday(?)',
                    'm.sensor_id IN ('+','.join('?' for _ in ids)+')']
        parameters=[source,stamp(end),*ids]
        if start is not None:
            conditions.append('julianday(m.fecha_utc)>=julianday(?)'); parameters.append(stamp(start))
        rows=conn.execute('SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,m.unidad,'+flags+
            ' FROM mediciones m '+join+' WHERE '+' AND '.join(conditions)+
            ' ORDER BY julianday(m.fecha_utc),m.sensor_id LIMIT ?',(*parameters,MAX_ROWS+1)).fetchall()
        inventory=[]; last_rows=[]
        if include_history:
            inventory=[dict(r) for r in conn.execute('''SELECT sensor_id,fuente source,
                strftime('%Y',fecha_utc) year,COUNT(*) count,MIN(fecha_utc) first_utc,MAX(fecha_utc) latest_utc
                FROM mediciones WHERE contaminante='pm25' AND julianday(fecha_utc)<julianday(?)
                GROUP BY sensor_id,fuente,strftime('%Y',fecha_utc) ORDER BY sensor_id,fuente,year''',(stamp(end),))
                if r['sensor_id'] in catalog and r['source'] in SOURCES]
            if station!='all':
                last_rows=conn.execute('SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,m.unidad,'+flags+
                    ' FROM mediciones m '+join+''' WHERE m.fuente=? AND m.sensor_id=?
                    AND m.contaminante='pm25' AND julianday(m.fecha_utc)<julianday(?)
                    ORDER BY julianday(m.fecha_utc) DESC LIMIT 2''',(source,int(station),stamp(end))).fetchall()
    if len(rows)>MAX_ROWS: raise TooManyRows('Demasiadas observaciones. Selecciona una estación o un periodo más corto.')
    grouped=defaultdict(list); observations=[]; seen=set()
    for row in rows:
        point=instant(row['fecha_utc']); value=float(row['valor']); sid=row['sensor_id']
        if row['unidad']!='µg/m³' or not math.isfinite(value):
            raise RuntimeError('Incompatible concentration unit or value')
        if (sid,point) in seen: raise RuntimeError('Ambiguous duplicate UTC hour')
        seen.add((sid,point))
        item={'timestamp_utc':stamp(point),'epoch_ms':int(point.timestamp()*1000),'value':value,
              'sensor_id':sid,'source':source,'unit':row['unidad'],'name':catalog[sid]['name'],
              'quality':{'evaluated':row['version_reglas'] is not None,'version':row['version_reglas'],
                'zero':row['es_cero'],'extreme':row['es_extremo'],'jump':row['salto_abrupto'],'review':row['requiere_revision']}}
        grouped[sid].append(item); observations.append(item)
    series=[]
    for sid,items in grouped.items():
        points=[]; previous=None; missing=0
        for item in items:
            if previous is not None and item['epoch_ms']-previous['epoch_ms']>3600000:
                missing+=(item['epoch_ms']-previous['epoch_ms'])//3600000-1
                # Presentation separator, explicitly NOT an observed/synthetic measurement.
                points.append({'epoch_ms':previous['epoch_ms']+3600000,'value':None,'gap':True})
            points.append(item); previous=item
        series.append({'sensor_id':sid,'name':catalog[sid]['name'],'source':source,'points':points,'missing_hours_between_observations':missing})
    stations=[]
    for sid,meta in sorted(catalog.items(),key=lambda x:x[1]['name']):
        available=availability.get(sid,{}); latest=available.get('latest')
        age=(now-instant(latest)).total_seconds()/3600 if latest else None
        stations.append({**meta,'source':source,'count':available.get('count',0),'latest_utc':latest,
            'age_hours':age,'fresh':source=='OpenAQ' and age is not None and 0<=age<=2,
            'coordinate_scope':'OpenAQ location metadata; historical validity not established',
            'period_count':len(grouped.get(sid,[]))})
    latest=max(observations,key=lambda x:x['epoch_ms']) if observations else None
    age=(now-instant(latest['timestamp_utc'])).total_seconds()/3600 if latest else None
    result={'generated_at_utc':stamp(now),'source':source,'source_label':SOURCES[source],
        'selection':{'station':station,'period':period},'unit':'µg/m³',
        'window':{'from_utc':stamp(start) if start else None,'to_exclusive_utc':stamp(end),'basis':'UTC; completed hourly periods'},
        'stations':stations,'series':series,
        'stats':{'count':len(observations),'stations_with_data':len(grouped),
            'mean':sum(r['value'] for r in observations)/len(observations) if observations else None,
            'latest':latest,'age_hours':age,'review':sum(bool(r['quality']['review']) for r in observations),
            'pending_quality':sum(not r['quality']['evaluated'] for r in observations)},
        'recent_observations':list(reversed(observations[-100:])),
        'quality_basis':'Initial immutable assessment; version is reported per observation',
        'freshness_limit_hours':2,'predictions':{'enabled':False,'status':'Validación independiente pendiente; sin pronósticos'},
        'notes':['Fuentes separadas; sin imputación ni interpolación.',
                 'La media es de observaciones disponibles, no una media espacial ni un índice de salud.',
                 'Última observación no equivale a última sincronización.']}
    if include_history:
        last=None
        if last_rows:
            r=last_rows[0]; point=instant(r['fecha_utc']); value=float(r['valor'])
            if r['unidad']!='µg/m³' or not math.isfinite(value):
                raise RuntimeError('Incompatible latest observation')
            if len(last_rows)>1 and instant(last_rows[1]['fecha_utc'])==point:
                raise RuntimeError('Ambiguous latest observation')
            last={'timestamp_utc':stamp(point),'epoch_ms':int(point.timestamp()*1000),
                  'value':value,'source':source,'sensor_id':r['sensor_id'],'unit':r['unidad'],
                  'name':catalog[r['sensor_id']]['name'],
                  'quality':{'evaluated':r['version_reglas'] is not None,'version':r['version_reglas'],
                             'review':r['requiere_revision']}}
        result.update(inventory=inventory,station_latest=last)
    return result
