"""Archivo público OpenAQ: descargar evidencia y después importar sin sobrescribir.

Los timestamps del archivo se conservan como reportados, normalizados a UTC.
La fuente se separa de /hours hasta verificar equivalencia temporal documental.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sqlite3
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from .catalog import load_catalog
from .sync_pm25_queretaro import ensure_db
from .quality_versioned import evaluate as evaluate_versioned
from .plan_recovery import utc_hour, stamp

ROOT = Path(__file__).resolve().parents[1]
BUCKET = 'https://openaq-data-archive.s3.amazonaws.com/'
SOURCE = 'OpenAQ-Archive'
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}


def get_bytes(url):
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'AERIS-Research/3.0'}), timeout=45) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def list_keys(location, year, month):
    prefix = f'records/csv.gz/locationid={location}/year={year}/month={month:02}/'
    token = None
    keys = []
    while True:
        params = {'list-type': '2', 'prefix': prefix}
        if token:
            params['continuation-token'] = token
        root = ET.fromstring(get_bytes(BUCKET+'?'+urlencode(params)))
        keys.extend(node.text for node in root.findall('s:Contents/s:Key', NS))
        if root.findtext('s:IsTruncated', default='false', namespaces=NS) != 'true':
            return keys
        next_token = root.findtext('s:NextContinuationToken', namespaces=NS)
        if not next_token or next_token == token:
            raise ValueError('Paginación S3 incompleta')
        token = next_token


def download(sensor_ids, start, end, output):
    start, end = utc_hour(start), utc_hour(end)
    if start >= end:
        raise ValueError('Intervalo vacío')
    catalog = load_catalog()
    if not set(sensor_ids) <= catalog.keys():
        raise ValueError('Sensores fuera del catálogo verificado')
    # Particiones por día local; incluir bordes adyacentes y filtrar en UTC al importar.
    first, last = (start-timedelta(days=1)).date(), end.date()
    months = set()
    day = first
    while day <= last:
        months.add((day.year, day.month))
        day += timedelta(days=1)
    keys = []
    for location in sorted({catalog[s]['location_id'] for s in sensor_ids}):
        for year, month in sorted(months):
            for key in list_keys(location, year, month):
                date = datetime.strptime(key.rsplit('-', 1)[-1].split('.')[0], '%Y%m%d').date()
                if first <= date <= last:
                    keys.append((location, key))
    cache = ROOT/'data'/'raw'/'openaq_archive'
    cache.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        location, key = item
        url = BUCKET+quote(key, safe='/=')
        try:
            raw = get_bytes(url)
            digest = hashlib.sha256(raw).hexdigest()
            path = cache/(digest+'.csv.gz')
            try:
                with path.open('xb') as target:
                    target.write(raw)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Cache alterado')
            return {'location_id': location, 'url': url, 'sha256': digest,
                    'path': str(path.relative_to(ROOT)), 'bytes': len(raw)}
        except (OSError, ValueError) as exc:
            return {'location_id': location, 'url': url, 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(fetch, keys))
    manifest = {'format': 'aeris-openaq-archive-v1', 'source': SOURCE,
                'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
                'from_utc': stamp(start), 'to_utc_exclusive': stamp(end),
                'sensor_locations': {str(s): catalog[s]['location_id'] for s in sensor_ids},
                'timestamp_semantics': 'reported_archive_datetime_no_shift',
                'listed_files': len(keys), 'files': files}
    with Path(output).open('x', encoding='utf-8') as target:
        json.dump(manifest, target, ensure_ascii=False, indent=2)
    return manifest


def parse_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest.get('format') != 'aeris-openaq-archive-v1' or manifest.get('source') != SOURCE:
        raise ValueError('Formato o fuente incorrectos')
    if not manifest['files'] or any('error' in item for item in manifest['files']):
        raise ValueError('Manifiesto vacío o con descargas fallidas; no se importa')
    start, end = utc_hour(manifest['from_utc']), utc_hour(manifest['to_utc_exclusive'])
    if start >= end:
        raise ValueError('Intervalo vacío')
    catalog = load_catalog()
    locations = {int(k): int(v) for k, v in manifest['sensor_locations'].items()}
    if not locations or any(s not in catalog or catalog[s]['location_id'] != loc for s, loc in locations.items()):
        raise ValueError('Relación sensor/ubicación no verificada')
    records = []
    rejected = outside = 0
    for item in manifest['files']:
        loc = item['location_id']
        prefix = BUCKET+f'records/csv.gz/locationid={loc}/'
        if loc not in locations.values() or not item['url'].startswith(prefix):
            raise ValueError('URL de origen incompatible')
        cached = (ROOT/item['path']).resolve()
        if not cached.is_relative_to((ROOT/'data'/'raw'/'openaq_archive').resolve()):
            raise ValueError('Ruta de cache fuera del directorio permitido')
        raw = cached.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('SHA-256 no coincide; no se modifica SQLite')
        reader = csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf-8-sig')))
        required = {'location_id', 'datetime', 'parameter', 'value'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Columnas de archivo incompatibles')
        for number, row in enumerate(reader, 2):
            try:
                sid = int(row.get('sensors_id', row.get('sensor_id', '')))
                if sid not in locations or row['parameter'] != 'pm25':
                    continue
                if int(row['location_id']) != locations[sid] or int(row['location_id']) != loc:
                    raise ValueError('Ubicación incompatible')
                instant = utc_hour(row['datetime'])
                if not start <= instant < end:
                    outside += 1
                    continue
                value = float(row['value'])
                unit = row.get('units', row.get('unit'))
                if not math.isfinite(value) or unit not in ('µg/m³', 'ug/m3'):
                    raise ValueError('Valor/unidad incompatible')
                # Se conservan negativos para revisión, no se usan para entrenar.
                records.append((sid, stamp(instant), value, item['sha256'], number))
            except (ValueError, TypeError, OverflowError):
                rejected += 1
    if not records:
        raise ValueError('No hay registros horarios PM2.5 compatibles; no se modifica SQLite')
    return manifest, records, rejected, outside


def import_manifest(path, db):
    # Validar todos los insumos antes de abrir la base en escritura.
    manifest, records, rejected, outside = parse_manifest(path)
    db = Path(db).resolve()
    run_id = uuid.uuid4().hex
    backup = None
    if db.exists():
        folder = db.parent/'backups'
        folder.mkdir(exist_ok=True)
        backup = folder/(db.stem+'_before_archive_'+run_id+'.db')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
    db.parent.mkdir(parents=True, exist_ok=True)
    added = identical = conflicts = 0
    with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
        ensure_db(conn)
        conn.execute('''CREATE TABLE IF NOT EXISTS archivos_origen (
            sha256 TEXT PRIMARY KEY,url TEXT NOT NULL,ruta_local TEXT NOT NULL,
            descargado_utc TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS observaciones_archivo (
            archivo_sha256 TEXT NOT NULL, fila INTEGER NOT NULL,
            fuente TEXT NOT NULL,sensor_id INTEGER NOT NULL,fecha_utc TEXT NOT NULL,
            valor REAL NOT NULL,coincide_vigente INTEGER NOT NULL,
            PRIMARY KEY(archivo_sha256,fila),
            FOREIGN KEY(archivo_sha256) REFERENCES archivos_origen(sha256))''')
        for item in manifest['files']:
            conn.execute('INSERT OR IGNORE INTO archivos_origen VALUES (?,?,?,?)',
                         (item['sha256'],item['url'],item['path'],manifest['downloaded_at_utc']))
        for sid, instant, value, digest, number in records:
            old = conn.execute('''SELECT valor FROM mediciones WHERE
                fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante='pm25' ''',
                               (SOURCE,sid,instant)).fetchone()
            if old is None:
                conn.execute("INSERT INTO mediciones VALUES (?,?,?,'pm25',?,'µg/m³')",
                             (SOURCE,sid,instant,value))
                added += 1
            elif old[0] == value:
                identical += 1
            else:
                conflicts += 1
            # Conservar también candidatos corregidos sin sustituir el valor original.
            conn.execute('INSERT OR IGNORE INTO observaciones_archivo VALUES (?,?,?,?,?,?,?)',
                         (digest,number,SOURCE,sid,instant,value,int(old is None or old[0] == value)))
        for sid in {r[0] for r in records}:
            evaluate_versioned(conn, sid, SOURCE, run_id=run_id)
        report = {'run_id':run_id,'source':SOURCE,'manifest':str(Path(path).resolve()),
                  'manifest_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                  'new_measurements':added,'identical':identical,'conflicting_candidates':conflicts,
                  'rejected_rows':rejected,'outside_window':outside,
                  'backup':str(backup) if backup else None,'original_measurements_overwritten':0}
        conn.execute('INSERT INTO ingestas VALUES (?,?,?,?,?)',
                     (run_id,datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat(),
                      'partial' if rejected or conflicts else 'success',json.dumps(report)))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('download')
    fetch.add_argument('--sensor', type=int, nargs='+', required=True)
    fetch.add_argument('--from', dest='start', required=True)
    fetch.add_argument('--to', dest='end', required=True)
    fetch.add_argument('--output', type=Path, required=True)
    ingest = sub.add_parser('import')
    ingest.add_argument('--manifest', type=Path, required=True)
    ingest.add_argument('--db', type=Path, default=ROOT/'data'/'aeris_air_quality.db')
    args = parser.parse_args(argv)
    try:
        if args.command == 'download':
            if args.output.exists():
                parser.error('El manifiesto ya existe; no se sobrescribe')
            result = download(args.sensor,args.start+'T00:00:00Z',args.end+'T00:00:00Z',args.output)
            print(json.dumps({'manifest':str(args.output),'listed_files':result['listed_files'],
                              'failed_files':sum('error' in f for f in result['files'])}))
            return int(not result['files'] or any('error' in f for f in result['files']))
        report = import_manifest(args.manifest,args.db)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return int(bool(report['rejected_rows'] or report['conflicting_candidates']))
    except (OSError,ValueError,KeyError,sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
