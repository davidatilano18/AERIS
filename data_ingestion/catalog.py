"""Catálogo PM2.5 respaldado por la instantánea local de metadatos OpenAQ."""
import json
from pathlib import Path

METADATA = Path(__file__).resolve().parents[1] / 'data' / 'openaq_stations.json'
# Selección explícita: no fusionar sensores paralelos o históricos.
SELECTED = {
    8956473: ('Carrillo Puerto', 'Querétaro'),
    1352676: ('Corregidora', 'Corregidora'),
    2694071: ('Epigmenio González', 'Querétaro'),
    1352681: ('Félix Osores', 'Querétaro'),
    1352719: ('Josefa Vergara', 'Querétaro'),
    17320548: ('San Juan del Río (ubicación 6498868)', 'San Juan del Río'),
    1352718: ('San Juan del Río (ubicación 235232)', 'San Juan del Río'),
    1352686: ('El Marqués (histórico)', 'El Marqués'),
}


def load_catalog(path=METADATA):
    snapshot = json.loads(Path(path).read_text(encoding='utf-8'))
    result = {}
    for location in snapshot['estaciones']:
        for sensor in location.get('sensors', []):
            sid = sensor['id']
            if sid not in SELECTED:
                continue
            parameter = sensor.get('parameter') or {}
            if parameter.get('name') != 'pm25' or parameter.get('units') != 'µg/m³':
                raise ValueError(f'Metadatos incompatibles para sensor {sid}')
            if sid in result:
                raise ValueError(f'Sensor duplicado en metadatos: {sid}')
            coordinates = location.get('coordinates') or {}
            lat, lon = coordinates.get('latitude'), coordinates.get('longitude')
            if lat is not None and lon is not None:
                if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
                    raise ValueError(f'Coordenadas inválidas para {sid}')
            result[sid] = {
                'sensor_id': sid, 'location_id': location['id'],
                'name': SELECTED[sid][0], 'municipality': SELECTED[sid][1],
                'lat': lat, 'lon': lon,
                'provider': (location.get('provider') or {}).get('name'),
                'metadata_at': snapshot.get('fecha_consulta_utc'),
            }
    missing = SELECTED.keys() - result.keys()
    if missing:
        raise ValueError(f'Sensores sin metadatos: {sorted(missing)}')
    return result


def persist_catalog(conn, catalog):
    conn.execute('''CREATE TABLE IF NOT EXISTS sensores (
        fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL, location_id INTEGER NOT NULL,
        nombre TEXT NOT NULL, municipio TEXT NOT NULL, latitud REAL, longitud REAL,
        proveedor TEXT, metadatos_utc TEXT,
        PRIMARY KEY(fuente,sensor_id))''')
    conn.executemany('''INSERT INTO sensores VALUES ('OpenAQ',?,?,?,?,?,?,?,?)
        ON CONFLICT(fuente,sensor_id) DO UPDATE SET
        location_id=excluded.location_id,nombre=excluded.nombre,
        municipio=excluded.municipio,latitud=excluded.latitud,longitud=excluded.longitud,
        proveedor=excluded.proveedor,metadatos_utc=excluded.metadatos_utc''',
        [(s['sensor_id'], s['location_id'], s['name'], s['municipality'],
          s['lat'], s['lon'], s['provider'], s['metadata_at']) for s in catalog.values()])


def read_catalog(conn):
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sensores'").fetchone()
    if not exists:
        return load_catalog()
    rows = conn.execute('''SELECT sensor_id,location_id,nombre,municipio,latitud,
        longitud,proveedor,metadatos_utc FROM sensores WHERE fuente='OpenAQ' ''')
    keys = ('sensor_id', 'location_id', 'name', 'municipality', 'lat', 'lon', 'provider', 'metadata_at')
    return {r[0]: dict(zip(keys, r)) for r in rows}
