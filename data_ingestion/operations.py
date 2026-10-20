"""Sincronización de una corrida: incremental, aditiva, auditable y sin predicciones."""
import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing,contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

from .catalog import load_catalog,persist_catalog,SELECTED
from .openaq_protocol import parse_verified_hour,verify_location_sensor,parse_utc
from .quality_versioned import ensure_versioned, evaluate as evaluate_versioned
from .sync_pm25_queretaro import ensure_db

ROOT=Path(__file__).resolve().parents[1]
API='https://api.openaq.org/v3'
ACTIVE=(8956473,1352676,2694071,1352681,17320548)


class Stopped(RuntimeError):pass


def utcnow():return datetime.now(timezone.utc)


def iso(value):return value.isoformat(timespec='seconds').replace('+00:00','Z')


@contextmanager
def exclusive_lock(path):
    """Bloqueo del SO: se libera incluso si termina el proceso; no borrar el archivo."""
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b')
    locked=False
    try:
        if path.stat().st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        locked=True
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


class ApiClient:
    def __init__(self,key,stop_path):
        self.key,self.stop_path,self.last_request=key,stop_path,0.

    def check_stop(self):
        if self.stop_path.exists():raise Stopped('Parada solicitada')

    def wait(self,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.check_stop();time.sleep(max(0,min(.25,until-time.monotonic())))

    def get(self,path,params):
        for attempt in range(4):
            self.check_stop()
            self.wait(max(0,1.1-(time.monotonic()-self.last_request)))
            self.last_request=time.monotonic()
            request=Request(API+path+'?'+urlencode(params),headers={'X-API-Key':self.key,'Accept':'application/json','User-Agent':'AERIS-Research/4.0'})
            try:
                with urlopen(request,timeout=45) as response:payload=json.load(response)
                self.check_stop()
                return payload
            except HTTPError as exc:
                # Nunca copiar cuerpos HTTP ni cabeceras de autenticación a los logs.
                retry=exc.headers.get('Retry-After','')
                exc.close()
                if exc.code not in (429,500,502,503,504) or attempt==3:
                    raise RuntimeError(f'OpenAQ HTTP {exc.code}') from None
                delay=float(retry) if retry.isdigit() else 2**(attempt+1)
                if delay>60:raise RuntimeError('OpenAQ solicita esperar más de 60 s; reintentar en otra corrida') from None
                self.wait(delay)
            except (URLError,TimeoutError):
                if attempt==3:raise RuntimeError('Conexión OpenAQ fallida') from None
                self.wait(2**(attempt+1))


def ensure_operations(conn):
    ensure_db(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS respuestas_api (
        sha256 TEXT NOT NULL,url TEXT NOT NULL,ruta_local TEXT NOT NULL,
        consultada_utc TEXT NOT NULL,PRIMARY KEY(sha256,url))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS observaciones_api (
        ingesta_id TEXT NOT NULL,respuesta_sha256 TEXT NOT NULL,fila INTEGER NOT NULL,
        sensor_id INTEGER NOT NULL,location_id INTEGER NOT NULL,fecha_utc TEXT NOT NULL,
        fin_utc TEXT NOT NULL,valor REAL NOT NULL,unidad TEXT NOT NULL,
        periodo_etiqueta TEXT NOT NULL,intervalo TEXT NOT NULL,agregacion TEXT NOT NULL,
        estado TEXT NOT NULL,PRIMARY KEY(ingesta_id,respuesta_sha256,fila),
        FOREIGN KEY(ingesta_id) REFERENCES ingestas(id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sincronizacion_estado (
        sensor_id INTEGER PRIMARY KEY,consulta_completa_hasta_utc TEXT NOT NULL,
        ultima_actualizacion_utc TEXT NOT NULL,ingesta_id TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS historial_calidad (
        ingesta_id TEXT NOT NULL,fuente TEXT NOT NULL,sensor_id INTEGER NOT NULL,
        fecha_utc TEXT NOT NULL,contaminante TEXT NOT NULL,
        flags_anteriores_json TEXT NOT NULL,registrado_utc TEXT NOT NULL,
        PRIMARY KEY(ingesta_id,fuente,sensor_id,fecha_utc,contaminante))''')
    ensure_versioned(conn)


def evaluate_quality(conn,sid,run_id):
    return evaluate_versioned(conn,sid,run_id=run_id)


def snapshot_metrics(conn,sid,start,end,clock):
    rows=conn.execute('''SELECT m.fecha_utc,m.valor,q.sensor_id,q.requiere_revision FROM mediciones m
        LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)
        WHERE m.fuente='OpenAQ' AND m.sensor_id=? AND m.contaminante='pm25' ''',(sid,)).fetchall()
    observed=[]
    latest=None
    pending=review=0
    for instant,value,quality_sid,flag in rows:
        point=datetime.fromisoformat(instant.replace('Z','+00:00'))
        if point.tzinfo is None:raise ValueError('Fecha histórica sin zona; requiere revisión')
        point=point.astimezone(timezone.utc)
        if point>clock:continue
        latest=max(latest,point) if latest else point
        pending+=int(quality_sid is None)
        review+=int(bool(flag))
        if start<=point<end:observed.append(point)
    hours=max(0,int((end-start).total_seconds()/3600))
    distinct=len(set(observed))
    unverified=conn.execute('''SELECT COUNT(*) FROM mediciones m WHERE m.fuente='OpenAQ'
        AND m.sensor_id=? AND m.contaminante='pm25' AND NOT EXISTS
        (SELECT 1 FROM observaciones_api o WHERE o.sensor_id=m.sensor_id
         AND julianday(o.fecha_utc)=julianday(m.fecha_utc) AND o.valor=m.valor
         AND o.estado IN ('new','identical'))''',(sid,)).fetchone()[0]
    return {'window_from_utc':iso(start),'window_to_utc_exclusive':iso(end),
            'expected_hours':hours,'observed_hours':distinct,
            'duplicate_instants':len(observed)-distinct,'missing_hours':max(0,hours-distinct),
            'coverage_pct':round(100*distinct/hours,2) if hours else None,
            'latest_measurement_utc':iso(latest) if latest else None,
            'age_hours':round((clock-latest).total_seconds()/3600,2) if latest else None,
            'quality_pending':pending,'quality_review':review,'temporal_evidence_pending':unverified,
            'freshness_status':'fresh' if latest and clock-latest<=timedelta(hours=2) else 'stale_or_missing'}


def copy_database(source,destination):
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:src.backup(dst)


def collect(client,sid,location,start,end,limit,max_pages,raw_dir,key):
    evidence=[]
    def fetch(path,params):
        payload=client.get(path,params)
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf8')
        if len(key)>=8 and key.encode() in raw:raise ValueError('Respuesta con credencial: no se conserva')
        digest=hashlib.sha256(raw).hexdigest()
        target=raw_dir/(digest+'.json')
        try:
            with target.open('xb') as output:output.write(raw)
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Evidencia alterada')
        evidence.append((digest,API+path+'?'+urlencode(params),str(target),iso(utcnow())))
        return payload,digest
    metadata,_=fetch(f'/locations/{location}',{})
    verify_location_sensor(metadata,sid,location)
    accepted=[];seen={};rejected=outside=received=0;complete=False
    for page in range(1,max_pages+1):
        payload,digest=fetch(f'/sensors/{sid}/hours',{'datetime_from':iso(start),'datetime_to':iso(end),'limit':limit,'page':page})
        if not isinstance(payload,dict) or not isinstance(payload.get('results'),list):
            raise ValueError('Respuesta sin results; no se declara completa')
        rows=payload['results'];received+=len(rows)
        for position,row in enumerate(rows):
            try:record=parse_verified_hour(row,sid,location)
            except (KeyError,ValueError,TypeError,OverflowError):rejected+=1;continue
            point=parse_utc(record['from_utc'])
            if not start<=point<end:outside+=1;continue
            if record['from_utc'] in seen and seen[record['from_utc']]!=record['value']:
                raise ValueError('La API devolvió valores contradictorios para el mismo periodo')
            seen[record['from_utc']]=record['value']
            accepted.append((record,digest,position))
        if len(rows)<limit:complete=True;break
    return accepted,evidence,{'received':received,'rejected':rejected,'outside_window':outside,'complete':complete}


def store_sensor(conn,run_id,sid,records,evidence):
    new=identical=conflicts=0
    for item in evidence:conn.execute('INSERT OR IGNORE INTO respuestas_api VALUES (?,?,?,?)',item)
    for record,digest,position in records:
        instant,value=record['from_utc'],record['value']
        existing=conn.execute('''SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente='OpenAQ'
            AND sensor_id=? AND contaminante='pm25' AND julianday(fecha_utc)=julianday(?)''',(sid,instant)).fetchall()
        if len(existing)>1:raise ValueError('Duplicados UTC previos: no se incorporan observaciones ambiguas')
        if not existing:
            conn.execute("INSERT INTO mediciones VALUES ('OpenAQ',?,?,'pm25',?,'µg/m³')",(sid,instant,value))
            new+=1;status='new'
        elif existing[0][2]!=record['unit']:raise ValueError('Unidad original incompatible: revisar antes de incorporar')
        elif existing[0][1]==value:identical+=1;status='identical'
        else:conflicts+=1;status='conflict_original_preserved'
        receipt=conn.execute('INSERT OR IGNORE INTO observaciones_api VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (run_id,digest,position,sid,record['location_id'],instant,record['to_utc'],value,
                             record['unit'],record['period_label'],record['interval'],record['aggregation'],status))
        if status=='conflict_original_preserved' and receipt.rowcount:
            conn.execute('''INSERT INTO revisiones_mediciones
                (ingesta_id,sensor_id,fecha_utc,valor_anterior,valor_nuevo,registrado_utc) VALUES (?,?,?,?,?,?)''',
                         (run_id,sid,existing[0][0],existing[0][1],value,iso(utcnow())))
    quality=evaluate_quality(conn,sid,run_id)
    return {'new_measurements':new,'identical':identical,'conflicting_candidates':conflicts,
            'originals_overwritten':0,'versioned_quality':quality}


def run(db,sensor_ids,dry_run=False,offline=False,start=None,end=None,overlap_hours=48,
        chunk_hours=168,limit=100,max_pages=50,key=None,client=None):
    db=Path(db).resolve()
    if offline and not dry_run:raise ValueError('Offline solo se permite con dry-run')
    if min(overlap_hours,chunk_hours,limit,max_pages)<1 or limit>1000 or chunk_hours<=overlap_hours:raise ValueError('Parámetros fuera de rango')
    catalog=load_catalog()
    if not sensor_ids or not set(sensor_ids)<=catalog.keys():raise ValueError('Sensor no verificado en catálogo')
    if not offline and not key:raise ValueError('Falta OPENAQ_API_KEY; no se inició la sincronización')
    if (start is None)!=(end is None):raise ValueError('Indicar inicio y fin juntos')
    clock=utcnow();query_end=end or clock.replace(minute=0,second=0,microsecond=0)
    if query_end.tzinfo is None or query_end>clock or (start and (start.tzinfo is None or start>=query_end)):
        raise ValueError('Intervalo futuro o inválido')
    if start and end and end-start>timedelta(hours=chunk_hours):
        raise ValueError('Dividir el intervalo explicito en bloques de --chunk-hours o menos')
    run_id=uuid.uuid4().hex
    runtime=db.parent/'sync_runtime';runtime.mkdir(parents=True,exist_ok=True)
    reports=runtime/'reports';reports.mkdir(exist_ok=True)
    stop_path=Path(str(db)+'.sync.stop')
    report={'run_id':run_id,'dry_run':dry_run,'offline':offline,'started_at_utc':iso(clock),
            'database':str(db),'originals_overwritten':0,'results':[],'backup':None}
    client=client or ApiClient(key,stop_path)
    with exclusive_lock(Path(str(db)+'.sync.lock')):
        with tempfile.TemporaryDirectory(prefix='aeris-sync-') as temporary:
            target=Path(temporary)/'test.db' if dry_run else db
            if dry_run and db.exists():copy_database(db,target)
            if not dry_run and db.exists():
                backups=db.parent/'backups';backups.mkdir(exist_ok=True)
                backup=backups/(db.stem+'_before_sync_'+run_id+'.db')
                copy_database(db,backup);report['backup']=str(backup)
            raw_dir=(Path(temporary)/'raw') if dry_run else runtime/'raw'
            raw_dir.mkdir(exist_ok=True)
            with closing(sqlite3.connect(target,timeout=30)) as conn:
                ensure_operations(conn)
                persist_catalog(conn,catalog)
                # Corridas cortadas se documentan después del respaldo, sin tocar mediciones.
                conn.execute("UPDATE ingestas SET estado='interrupted' WHERE estado='running'")
                conn.execute('INSERT INTO ingestas VALUES (?,?,NULL,?,NULL)',(run_id,iso(clock),'running'))
                conn.commit()
                try:
                    for sid in dict.fromkeys(sensor_ids):
                        if stop_path.exists():raise Stopped('Parada solicitada')
                        try:
                            lower=start
                            if lower is None:
                                saved=conn.execute('SELECT consulta_completa_hasta_utc FROM sincronizacion_estado WHERE sensor_id=?',(sid,)).fetchone()
                                last=conn.execute("SELECT MAX(fecha_utc) FROM mediciones WHERE fuente='OpenAQ' AND sensor_id=? AND contaminante='pm25'",(sid,)).fetchone()[0]
                                cursor=parse_utc(saved[0]) if saved else (parse_utc(last) if last else query_end-timedelta(days=7))
                                lower=cursor-timedelta(hours=overlap_hours) if saved or last else cursor
                            if lower>=query_end:raise ValueError('Cursor futuro o intervalo vacío')
                            upper=min(query_end,lower+timedelta(hours=chunk_hours))
                            if offline:
                                with conn:evaluate_quality(conn,sid,run_id)
                                statistics={'received':0,'rejected':0,'complete':False,'outside_window':0}
                                changes={'new_measurements':0,'originals_overwritten':0}
                            else:
                                records,evidence,statistics=collect(client,sid,catalog[sid]['location_id'],lower,upper,limit,max_pages,raw_dir,key)
                                if stop_path.exists():raise Stopped('Parada solicitada')
                                with conn:
                                    changes=store_sensor(conn,run_id,sid,records,evidence)
                                    if statistics['complete'] and not statistics['rejected']:
                                        conn.execute('''INSERT INTO sincronizacion_estado VALUES (?,?,?,?)
                                            ON CONFLICT(sensor_id) DO UPDATE SET
                                            consulta_completa_hasta_utc=MAX(sincronizacion_estado.consulta_completa_hasta_utc,excluded.consulta_completa_hasta_utc),
                                            ultima_actualizacion_utc=excluded.ultima_actualizacion_utc,ingesta_id=excluded.ingesta_id''',
                                                     (sid,iso(upper),iso(utcnow()),run_id))
                            metrics=snapshot_metrics(conn,sid,lower,upper,clock)
                            report['results'].append({'sensor_id':sid,'name':catalog[sid]['name'],
                                'status':'offline_audit' if offline else 'synchronized','remaining_until_utc':iso(query_end),
                                'backlog_hours':max(0,int((query_end-upper).total_seconds()/3600)),
                                **statistics,**changes,**metrics})
                        except Stopped:raise
                        except (OSError,RuntimeError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                            conn.rollback()
                            quality_error=None
                            try:
                                with conn:evaluate_quality(conn,sid,run_id)
                            except (ValueError,TypeError,sqlite3.Error) as quality_exc:
                                conn.rollback()
                                quality_error=str(quality_exc).replace(key,'[redacted]') if key else str(quality_exc)
                            text=str(exc).replace(key,'[redacted]') if key else str(exc)
                            metrics=snapshot_metrics(conn,sid,query_end-timedelta(hours=168),query_end,clock)
                            report['results'].append({'sensor_id':sid,'status':'error','error':text,
                                                      'quality_error':quality_error,**metrics})
                    bad=any(r['status']=='error' or r.get('rejected',0) or r.get('conflicting_candidates',0)
                            or not r.get('complete',False) for r in report['results'])
                    report['status']='offline_audit' if offline else 'partial' if bad else 'success'
                except (Stopped,KeyboardInterrupt):
                    conn.rollback();report['status']='cancelled'
                report['finished_at_utc']=iso(utcnow())
                serialized=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)
                with conn:conn.execute('UPDATE ingestas SET fin_utc=?,estado=?,reporte_json=? WHERE id=?',
                                       (report['finished_at_utc'],report['status'],serialized,run_id))
            with (reports/(run_id+'.json')).open('x',encoding='utf8') as output:output.write(serialized)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=ROOT/'data'/'aeris_air_quality.db')
    parser.add_argument('--sensor',type=int,nargs='+')
    parser.add_argument('--station',choices=[v[0] for v in SELECTED.values()])
    parser.add_argument('--incremental',action='store_true',help='Modo predeterminado; no combina fechas explícitas')
    parser.add_argument('--from',dest='date_from');parser.add_argument('--to',dest='date_to')
    parser.add_argument('--days',type=int)
    parser.add_argument('--overlap-hours',type=int,default=48)
    parser.add_argument('--chunk-hours',type=int,default=168)
    parser.add_argument('--limit',type=int,default=100);parser.add_argument('--max-pages',type=int,default=50)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--request-stop',action='store_true');parser.add_argument('--clear-stop',action='store_true')
    args=parser.parse_args(argv)
    db=args.db.resolve();stop=Path(str(db)+'.sync.stop')
    try:
        if args.request_stop and args.clear_stop:raise ValueError('Parada y reanudación excluyentes')
        if args.request_stop:
            stop.parent.mkdir(parents=True,exist_ok=True);stop.touch(exist_ok=True)
            print('Parada solicitada; no se alteró SQLite');return 0
        if args.clear_stop:
            stop.unlink(missing_ok=True);print('Parada retirada; no se inició una sincronización');return 0
        if stop.exists():print('Sincronización pausada por archivo de parada');return 0
        if args.sensor and args.station:raise ValueError('Usar --sensor o --station')
        if (args.date_from is None)!=(args.date_to is None):raise ValueError('Indicar --from y --to juntos')
        if args.days is not None and (args.incremental or args.date_from):raise ValueError('--days no combina otros periodos')
        if args.incremental and args.date_from:raise ValueError('--incremental no combina fechas explícitas')
        start=end=None
        if args.date_from:
            start=parse_utc(args.date_from+'T00:00:00Z');end=parse_utc(args.date_to+'T00:00:00Z')
        if args.days is not None:
            if not 1<=args.days<=365:raise ValueError('--days debe estar entre 1 y 365')
            end=utcnow().replace(minute=0,second=0,microsecond=0);start=end-timedelta(days=args.days)
        sensors=args.sensor or ([sid for sid,v in SELECTED.items() if v[0]==args.station] if args.station else list(ACTIVE))
        report=run(db,sensors,args.dry_run,args.offline,start,end,args.overlap_hours,args.chunk_hours,args.limit,args.max_pages,os.getenv('OPENAQ_API_KEY','').strip())
        print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
        return 0 if report['status'] in ('success','offline_audit') else 1
    except (ValueError,OSError,sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__=='__main__':raise SystemExit(main())
