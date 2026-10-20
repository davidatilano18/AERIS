r"""AERIS: sincronización de PM2.5 horario de estaciones seleccionadas en Querétaro.

Uso (PowerShell):
  $env:OPENAQ_API_KEY = Read-Host 'Clave OpenAQ'
  .\.venv\Scripts\python.exe .\data_ingestion\sync_pm25_queretaro.py --days 7

Solo usa observaciones devueltas por OpenAQ; no genera datos sintéticos.
"""
import argparse
import json
import os
import sqlite3
import time
import uuid
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .quality import ensure_quality
    from .quality_versioned import evaluate as evaluate_versioned
    from .catalog import SELECTED, load_catalog, persist_catalog
else:
    from quality import ensure_quality
    from catalog import SELECTED, load_catalog, persist_catalog

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'data' / 'aeris_air_quality.db'
API_ROOT = 'https://api.openaq.org/v3'

# Sensores PM2.5 identificados en la consulta de ubicaciones de OpenAQ.
# No mezclar sensores de una misma estación sin analizar continuidad y equivalencia.
SENSORS = {name: sid for sid, (name, _) in SELECTED.items()}


def api_get(path, params, key, retries=3):
    url = f'{API_ROOT}{path}?{urlencode(params)}'
    for attempt in range(retries):
        req = Request(url, headers={'X-API-Key': key, 'Accept': 'application/json', 'User-Agent': 'AERIS-Research/2.1'})
        try:
            with urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                delay = 2 ** (attempt + 1)
                print(f'    HTTP {exc.code}; reintentando en {delay}s...')
                time.sleep(delay)
                continue
            raise RuntimeError(f'OpenAQ HTTP {exc.code}') from None
        except (URLError, TimeoutError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f'Error de red: {exc}') from exc


def ensure_db(conn):
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('''CREATE TABLE IF NOT EXISTS mediciones (
        fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL,
        fecha_utc TEXT NOT NULL, contaminante TEXT NOT NULL,
        valor REAL NOT NULL, unidad TEXT,
        PRIMARY KEY (fuente, sensor_id, fecha_utc, contaminante)
    )''')
    ensure_quality(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS ingestas (
        id TEXT PRIMARY KEY, inicio_utc TEXT NOT NULL, fin_utc TEXT,
        estado TEXT NOT NULL, reporte_json TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS revisiones_mediciones (
        id INTEGER PRIMARY KEY, ingesta_id TEXT NOT NULL,
        sensor_id INTEGER NOT NULL, fecha_utc TEXT NOT NULL,
        valor_anterior REAL NOT NULL, valor_nuevo REAL NOT NULL,
        registrado_utc TEXT NOT NULL,
        FOREIGN KEY(ingesta_id) REFERENCES ingestas(id))''')


def parse_hour(row):
    if not isinstance(row, dict):
        return None
    period = row.get('period') or {}
    if not isinstance(period, dict):
        return None
    date_from = period.get('datetimeFrom') or {}
    if not isinstance(date_from, dict):
        return None
    dt = date_from.get('utc')
    val = row.get('value')
    if not dt or val is None:
        return None
    try:
        number = float(val)
        if not isinstance(dt, str) or isinstance(val, bool):
            return None
        original = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        if original.tzinfo is None:
            return None
        stamp = original.astimezone(timezone.utc)
        if stamp.minute or stamp.second or stamp.microsecond:
            return None
        if not (number == number and abs(number) != float('inf')):
            return None
        return stamp.isoformat(timespec='seconds').replace('+00:00', 'Z'), number
    except (TypeError, ValueError, OverflowError):
        return None


def sync_sensor(conn, name, sensor_id, start, end, key, page_limit, max_pages, run_id):
    inserted, updated, received, skipped = 0, 0, 0, 0
    first, last = None, None
    for page in range(1, max_pages + 1):
        payload = api_get(f'/sensors/{sensor_id}/hours', {
            'datetime_from': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'datetime_to': end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'limit': page_limit, 'page': page,
        }, key)
        rows = payload.get('results')
        if not isinstance(rows, list):
            raise RuntimeError('Respuesta OpenAQ sin lista results; no se considera descarga completa')
        received += len(rows)
        for row in rows:
            parsed = parse_hour(row)
            if parsed is None:
                skipped += 1
                continue
            stamp, value = parsed
            instant = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if not start <= instant < end:
                skipped += 1
                continue
            first = stamp if first is None or stamp < first else first
            last = stamp if last is None or stamp > last else last
            # Conservar el original; una discrepancia queda pendiente de revision.
            exists = conn.execute('''SELECT valor FROM mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?''',
                                  ('OpenAQ', sensor_id, stamp, 'pm25')).fetchone()
            if exists is None:
                conn.execute('''INSERT INTO mediciones (fuente,sensor_id,fecha_utc,contaminante,valor,unidad)
                                VALUES (?,?,?,?,?,?)''', ('OpenAQ', sensor_id, stamp, 'pm25', value, 'µg/m³'))
                inserted += 1
            elif exists[0] != value:
                conn.execute('''INSERT INTO revisiones_mediciones
                    (ingesta_id,sensor_id,fecha_utc,valor_anterior,valor_nuevo,registrado_utc)
                    VALUES (?,?,?,?,?,?)''', (run_id, sensor_id, stamp, exists[0], value,
                                              datetime.now(timezone.utc).isoformat()))
        if __package__:
            from .quality_versioned import evaluate as evaluate_versioned
        else:
            sys.path.insert(0,str(ROOT))
            from data_ingestion.quality_versioned import evaluate as evaluate_versioned
        evaluate_versioned(conn, sensor_id, run_id=run_id)
        conn.commit()
        print(f'    Página {page}: {len(rows)} registros (acumulados: {received})')
        if len(rows) < page_limit:
            return {'estacion': name, 'sensor_id': sensor_id, 'recibidos': received,
                    'nuevos': inserted, 'actualizados': updated, 'invalidos': skipped,
                    'primera_fecha_utc': first, 'ultima_fecha_utc': last, 'completo': True}
        time.sleep(0.25)
    return {'estacion': name, 'sensor_id': sensor_id, 'recibidos': received,
            'nuevos': inserted, 'actualizados': updated, 'invalidos': skipped,
            'primera_fecha_utc': first, 'ultima_fecha_utc': last, 'completo': False}


def main():
    # Entrada antigua compatible: toda ejecucion CLI usa el sincronizador seguro.
    if not __package__:
        sys.path.insert(0,str(ROOT))
    from data_ingestion.operations import main as safe_main
    return safe_main()


if __name__ == '__main__':
    sys.exit(main())
