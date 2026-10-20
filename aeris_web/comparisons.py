"""Read-only, matched-hour descriptive comparisons. Never a health interpretation."""
import math
import sqlite3
from contextlib import closing
from datetime import timedelta,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from data_ingestion.catalog import read_catalog
from .data import SOURCES,instant,stamp,utc_now

POLICY={'version':'aeris-matched-24h-v1','minimum_pairs':18,'expected_per_window':24,
        'minimum_pairs_per_six_hour_block':3,'quality':'initial immutable assessment; single version',
        'allowed_quality_versions':['aeris_qc_v1','aeris_qc_v2'],
        'similarity':'equal matched means rounded to 2 decimals, half up; not statistical equivalence',
        'scope':'descriptive concentration only; no health or causal conclusion'}
REASONS={
    'no_observations':'No hay mediciones de esta estación y fuente en las ventanas comparadas.',
    'insufficient_coverage':'No hay suficientes horas utilizables en ambos periodos.',
    'insufficient_matched_hours':'No coinciden suficientes horas utilizables entre ambos periodos.',
    'unbalanced_hours':'Las horas comparables se concentran en una parte del día; faltan horas en otros tramos.',
    'mixed_quality_versions':'Las revisiones iniciales usan distintas versiones; no resumimos el cambio como comparable.',
    'local_time_change':'Estas ventanas cruzan un cambio de horario local; no comparamos horas distintas como equivalentes.'}


def rounded(value):
    return str(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def compare_windows(rows,end,now,source,sensor_id):
    """Two closed 24h UTC windows. Match offsets, never impute absent hours."""
    if source not in SOURCES:raise ValueError('Fuente no válida.')
    if now.tzinfo is None or end.tzinfo is None:raise ValueError('Se requiere zona horaria explícita.')
    now=now.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    if end!=end.replace(minute=0,second=0,microsecond=0) or end>now.replace(minute=0,second=0,microsecond=0):
        raise ValueError('Los periodos deben terminar en una hora completa, sin horas futuras.')
    start=end-timedelta(hours=48);middle=end-timedelta(hours=24)
    indexed={}
    for row in rows:
        if row['source']!=source or row['sensor_id']!=sensor_id or row['unit']!='µg/m³':
            raise RuntimeError('Incompatible station, source or unit')
        t=instant(row['timestamp_utc'])
        if not start<=t<end:raise RuntimeError('Observation outside comparison windows')
        if t in indexed:raise RuntimeError('Ambiguous duplicate UTC hour')
        try:value=float(row['value'])
        except (ValueError,TypeError):raise RuntimeError('Invalid observation') from None
        if not math.isfinite(value):raise RuntimeError('Non-finite observation')
        indexed[t]={**row,'value':value}

    def usable(row):
        return bool(row and row['value']>=0 and row['quality_version'] in POLICY['allowed_quality_versions'] and
                    all(row.get(k)==0 for k in ('review','extreme','jump')))

    def describe(a,b):
        subset=[r for t,r in indexed.items() if a<=t<b]
        valid=sum(usable(r) for r in subset)
        return {'from_utc':stamp(a),'to_exclusive_utc':stamp(b),'expected_hours':24,
                'received_hours':len(subset),'usable_hours':valid,'usable_coverage_pct':valid/24*100}

    pairs=[];versions=set();used=[];blocks=[0,0,0,0]
    for i in range(24):
        a=start+timedelta(hours=i);b=middle+timedelta(hours=i)
        before=indexed.get(a);after=indexed.get(b)
        eligible=usable(before) and usable(after)
        same_version=bool(eligible and before['quality_version']==after['quality_version'])
        if eligible:versions.update((before['quality_version'],after['quality_version']))
        included=bool(same_version)
        if included:used.append((before['value'],after['value']));blocks[i//6]+=1
        pairs.append({'previous_utc':stamp(a),'current_utc':stamp(b),
            'previous_value':before['value'] if before else None,'current_value':after['value'] if after else None,
            'included':included,'reason':'included' if included else
            'missing' if not before or not after else 'quality_or_negative' if not eligible else 'quality_version_mismatch'})
    previous=describe(start,middle);current=describe(middle,end)
    reasons=[]
    if not indexed:reasons.append('no_observations')
    if min(previous['usable_hours'],current['usable_hours'])<18:reasons.append('insufficient_coverage')
    if len(used)<18:reasons.append('insufficient_matched_hours')
    if min(blocks)<3:reasons.append('unbalanced_hours')
    if len(versions)>1:reasons.append('mixed_quality_versions')
    zone=ZoneInfo('America/Mexico_City')
    if len({(start+timedelta(hours=i)).astimezone(zone).utcoffset() for i in range(48)})!=1:
        reasons.append('local_time_change')
    result={'status':'abstained' if reasons else 'compared','source':source,'sensor_id':sensor_id,
        'unit':'µg/m³','previous':previous,'current':current,'matched_hours':len(used),
        'matched_coverage_pct':len(used)/24*100,'pairs_per_six_hour_block':blocks,
        'quality_versions':sorted(versions),'pairs':pairs,'reasons':reasons,
        'reason_messages':[REASONS[r] for r in reasons],'policy':POLICY,
        'direction':None,'previous_mean':None,'current_mean':None,'difference':None,
        'previous_display':None,'current_display':None}
    if reasons:
        result['summary']='No mostramos una comparación. '+result['reason_messages'][0]
        return result
    old_decimal=sum(Decimal(str(a)) for a,b in used)/Decimal(len(used))
    new_decimal=sum(Decimal(str(b)) for a,b in used)/Decimal(len(used))
    old,new=float(old_decimal),float(new_decimal)
    old_text,new_text=rounded(old_decimal),rounded(new_decimal)
    direction='similar' if old_text==new_text else 'up' if new>old else 'down'
    verb={'similar':'se mantuvo similar al redondear a dos decimales','up':'subió','down':'bajó'}[direction]
    result.update(direction=direction,previous_mean=old,current_mean=new,difference=new-old,
                  previous_display=old_text,current_display=new_text,
                  summary=f'El promedio de concentración observado {verb}: de {old_text} a {new_text} µg/m³, '
                          f'usando las mismas {len(used)} horas comparables de cada periodo. '
                          'Esto no determina un cambio de riesgo para la salud.')
    return result


def read_comparison(path,source='OpenAQ',station='all',anchor='recent'):
    if source not in SOURCES or anchor not in ('recent','latest'):raise ValueError('Fuente o ventana no válida.')
    if not station.isdigit():raise ValueError('Elige una estación para comparar.')
    path=Path(path).resolve()
    if not path.is_file():raise FileNotFoundError('Base no disponible')
    now=utc_now();closed=now.replace(minute=0,second=0,microsecond=0)
    from data_ingestion.visibility import connect_readonly
    with closing(connect_readonly(path)) as conn:
        conn.row_factory=sqlite3.Row
        catalog=read_catalog(conn);sid=int(station)
        if sid not in catalog:raise ValueError('Estación no válida.')
        end=closed
        if anchor=='latest':
            last=conn.execute('''SELECT fecha_utc FROM mediciones WHERE fuente=? AND sensor_id=?
                AND contaminante='pm25' AND julianday(fecha_utc)<julianday(?)
                ORDER BY julianday(fecha_utc) DESC LIMIT 1''',(source,sid,stamp(closed))).fetchone()
            if last:end=instant(last['fecha_utc'])+timedelta(hours=1)
        has_qc=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calidad_mediciones'").fetchone()
        flags='q.version_reglas quality_version,q.requiere_revision review,q.es_extremo extreme,q.salto_abrupto jump' if has_qc else \
              'NULL quality_version,NULL review,NULL extreme,NULL jump'
        join='LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if has_qc else ''
        rows=conn.execute('SELECT m.fuente source,m.sensor_id,m.fecha_utc timestamp_utc,m.valor value,m.unidad unit,'+
            flags+' FROM mediciones m '+join+''' WHERE m.fuente=? AND m.sensor_id=? AND m.contaminante='pm25'
            AND julianday(m.fecha_utc)>=julianday(?) AND julianday(m.fecha_utc)<julianday(?)
            ORDER BY julianday(m.fecha_utc)''',(source,sid,stamp(end-timedelta(hours=48)),stamp(end))).fetchall()
        result=compare_windows([dict(r) for r in rows],end,now,source,sid)
    result.update(generated_at_utc=stamp(now),station_name=catalog[sid]['name'],anchor=anchor,
                  anchor_note='48 horas terminadas en la última hora registrada; puede ser historial antiguo.' if anchor=='latest'
                  else '48 horas anteriores a la hora actual completa; no incluye la hora en curso.')
    return result
