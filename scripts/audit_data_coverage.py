"""Read-only coverage inventory; hourly-grid completeness is not instrument uptime."""
import calendar
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly


def timestamp(text):
    value=datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Timestamp without timezone')
    return value.astimezone(timezone.utc)


def stamp(value):return value.isoformat().replace('+00:00','Z')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-audit',action='store_true',help='Include withdrawn records for forensic preservation only')
    physical=parser.parse_args().physical_audit
    db=ROOT/'data/aeris_air_quality.db';now=datetime.now(timezone.utc)
    closed=now.replace(minute=0,second=0,microsecond=0)
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) if physical else connect_readonly(db)
    conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON')
    if physical:conn.execute('BEGIN')
    try:
        catalog=read_catalog(conn)
        rows=[dict(r) for r in conn.execute('SELECT * FROM mediciones')]
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        quality=[dict(r) for r in conn.execute('SELECT version_reglas,COUNT(*) count FROM calidad_mediciones GROUP BY version_reglas')]
        receipt_periods=[dict(r) for r in conn.execute('''SELECT intervalo,agregacion,COUNT(*) count,
            MIN((julianday(fin_utc)-julianday(fecha_utc))*24) min_hours,
            MAX((julianday(fin_utc)-julianday(fecha_utc))*24) max_hours
            FROM observaciones_api GROUP BY intervalo,agregacion''')]
        tables={}
        for table in ('mediciones','calidad_mediciones','historial_calidad','evaluaciones_calidad',
                      'reglas_calidad_versionadas','evaluaciones_calidad_ingestas'):
            columns=len(conn.execute('PRAGMA table_info('+table+')').fetchall())
            order=','.join(str(i) for i in range(1,min(3,columns)+1))
            values=conn.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall()
            tables[table]={'count':len(values),'sha256':hashlib.sha256(json.dumps([tuple(r) for r in values],ensure_ascii=False).encode()).hexdigest()}
    finally:conn.close()
    groups=defaultdict(list);series=defaultdict(list)
    for r in rows:
        t=timestamp(r['fecha_utc']);r['instant']=t
        groups[r['sensor_id'],r['contaminante'],r['fuente'],t.year,t.month].append(r)
        series[r['sensor_id'],r['contaminante'],r['fuente']].append(r)
    matrix=[];summary=[];gaps=[]
    for (sid,param,source,year,month),items in sorted(groups.items()):
        times=sorted({r['instant'] for r in items});first,last=times[0],times[-1]
        units=sorted({r['unidad'] for r in items})
        aligned=all(t.minute==t.second==t.microsecond==0 for t in times)
        hourly=aligned and len(times)>1 and units==['µg/m³'] and param=='pm25'
        begin=datetime(year,month,1,tzinfo=timezone.utc)
        finish=begin+timedelta(days=calendar.monthrange(year,month)[1]);finish=min(finish,closed)
        month_hours=max(0,int((finish-begin).total_seconds()/3600))
        span=int((last-first).total_seconds()/3600)+1 if hourly else None
        gap_hours=[int((b-a).total_seconds()/3600)-1 for a,b in zip(times,times[1:]) if b-a>timedelta(hours=1)] if hourly else []
        meta=catalog.get(sid,{})
        matrix.append({'municipality':meta.get('municipality','Unmapped'),
            'station':meta.get('name','Unmapped'),'sensor_id':sid,'location_id':meta.get('location_id'),
            'pollutant':param,'source':source,'year_utc':year,'month_utc':month,'records':len(items),
            'unique_instants':len(times),'duplicate_instants':len(items)-len(times),'unit':' | '.join(units),
            'first_utc':stamp(first),'latest_utc':stamp(last),'age_hours':(now-last).total_seconds()/3600,
            'full_month_hours_until_closed':month_hours if hourly else None,
            'coverage_month_grid_pct':len(times)/month_hours*100 if hourly and month_hours else None,
            'observed_span_hours':span,'missing_hours_inside_observed_span':span-len(times) if span else None,
            'coverage_observed_span_pct':len(times)/span*100 if span else None,
            'largest_internal_gap_hours':max(gap_hours,default=0) if hourly else None,
            'frequency_basis':'hour-aligned stored series; descriptive UTC grid, not certified operation' if hourly else 'not established',
            'status':'observations_present'})
    for (sid,param,source),items in sorted(series.items()):
        times=sorted({r['instant'] for r in items});first,last=times[0],times[-1]
        hourly=all(t.minute==t.second==t.microsecond==0 for t in times)
        span=int((last-first).total_seconds()/3600)+1 if hourly else None
        for a,b in zip(times,times[1:]):
            if b-a>timedelta(hours=1):gaps.append({'sensor_id':sid,'pollutant':param,'source':source,
                'from_utc':stamp(a+timedelta(hours=1)),'to_exclusive_utc':stamp(b),
                'missing_hour_slots':int((b-a).total_seconds()/3600)-1})
        summary.append({'sensor_id':sid,'pollutant':param,'source':source,
            'municipality':catalog.get(sid,{}).get('municipality'),'station':catalog.get(sid,{}).get('name'),
            'records':len(items),'first_utc':stamp(first),'latest_utc':stamp(last),
            'age_hours':(now-last).total_seconds()/3600,'fresh_within_two_hours':0<=(now-last).total_seconds()/3600<=2,
            'observed_span_hours':span,'missing_internal_hours':span-len(times) if span else None,
            'coverage_observed_span_pct':len(times)/span*100 if span else None})
    present={r['sensor_id'] for r in rows}
    absences=[{'municipality':s['municipality'],'station':s['name'],'sensor_id':sid,'status':'catalogue_without_records'}
              for sid,s in catalog.items() if sid not in present]
    absences.append({'municipality':'Huimilpan','station':None,'sensor_id':None,'status':'no_selected_station'})
    for a in absences:
        empty={k:None for k in matrix[0]};empty.update(municipality=a['municipality'],station=a['station'],
            sensor_id=a['sensor_id'],records=0,status=a['status']);matrix.append(empty)
    after=hashlib.sha256(db.read_bytes()).hexdigest()
    result={'audited_at_utc':stamp(now),'closed_hour_exclusive_utc':stamp(closed),
        'read_scope':'physical_forensic' if physical else 'analytical_visible_batches',
        'database_sha256_before':before,'database_sha256_after':after,'byte_identical_during_audit':before==after,
        'integrity_check':integrity,'foreign_key_violations':[list(r) for r in fk],
        'records':len(rows),'tables':tables,'catalog':list(catalog.values()),'quality_versions':quality,
        'api_receipt_intervals':receipt_periods,'series':summary,'absence_states':absences,
        'matrix':matrix,'gaps':gaps,'coverage_warning':'Month denominator is full UTC month through closed hour. Span denominator is first through last observation. Neither proves station uptime or geographic representativeness.'}
    report=ROOT/'reports/aeris_data_coverage.json'
    report.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    with (ROOT/'reports/aeris_data_coverage_matrix.csv').open('w',encoding='utf-8-sig',newline='') as out:
        writer=csv.DictWriter(out,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    with (ROOT/'reports/aeris_data_gaps.csv').open('w',encoding='utf-8-sig',newline='') as out:
        writer=csv.DictWriter(out,fieldnames=['sensor_id','pollutant','source','from_utc','to_exclusive_utc','missing_hour_slots']);writer.writeheader();writer.writerows(gaps)
    print(json.dumps({'records':len(rows),'matrix_rows':len(matrix),'internal_gap_intervals':len(gaps),
        'database_byte_identical':before==after,'integrity':integrity},indent=2))


if __name__=='__main__':main()
