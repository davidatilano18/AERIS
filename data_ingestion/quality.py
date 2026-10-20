"""Reglas exploratorias reproducibles; no certifican validez instrumental."""
from datetime import datetime, timedelta

VERSION = 'aeris_qc_v2'


def ensure_quality(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS calidad_mediciones (
        fuente TEXT NOT NULL, sensor_id INTEGER NOT NULL, fecha_utc TEXT NOT NULL,
        contaminante TEXT NOT NULL, es_cero INTEGER NOT NULL DEFAULT 0,
        es_extremo INTEGER NOT NULL DEFAULT 0, salto_abrupto INTEGER NOT NULL DEFAULT 0,
        requiere_revision INTEGER NOT NULL DEFAULT 0, version_reglas TEXT NOT NULL,
        PRIMARY KEY (fuente,sensor_id,fecha_utc,contaminante),
        FOREIGN KEY (fuente,sensor_id,fecha_utc,contaminante)
        REFERENCES mediciones(fuente,sensor_id,fecha_utc,contaminante))''')


def refresh_quality(conn, sensor_id, source='OpenAQ'):
    """Reevaluar también sucesores afectados por correcciones o relleno de huecos.

    Un salto solo compara observaciones separadas exactamente una hora.
    Los ceros se señalan, pero no se consideran inválidos automáticamente.
    """
    rows = conn.execute('''SELECT fecha_utc,valor FROM mediciones
        WHERE fuente=? AND sensor_id=? AND contaminante='pm25'
        ORDER BY fecha_utc''', (source, sensor_id)).fetchall()
    previous = None
    flags = []
    for stamp, value in rows:
        instant = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        jump = int(previous is not None and instant - previous[0] == timedelta(hours=1)
                   and abs(value - previous[1]) >= 100)
        extreme = int(value > 100)
        review = int(value < 0 or extreme or jump)
        flags.append((source, sensor_id, stamp, 'pm25', int(value == 0),
                      extreme, jump, review, VERSION))
        previous = instant, value
    conn.executemany('''INSERT INTO calidad_mediciones
        (fuente,sensor_id,fecha_utc,contaminante,es_cero,es_extremo,
         salto_abrupto,requiere_revision,version_reglas) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(fuente,sensor_id,fecha_utc,contaminante) DO UPDATE SET
        es_cero=excluded.es_cero,es_extremo=excluded.es_extremo,
        salto_abrupto=excluded.salto_abrupto,requiere_revision=excluded.requiere_revision,
        version_reglas=excluded.version_reglas''', flags)
    return len(flags)
