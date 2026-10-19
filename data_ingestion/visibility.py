"""Central, snapshot-consistent read policy. Only TEMP objects; main SQLite stays read-only."""
import sqlite3
from pathlib import Path

POLICY = 'aeris-batch-visibility-v1'
LEDGER = {'archive_batches','archive_batch_keys','archive_batch_events'}
KEY = ('fuente','sensor_id','fecha_utc','contaminante')


def match(a,b): return ' AND '.join(f'{a}.{k}={b}.{k}' for k in KEY)


def connect_readonly(path, timeout=10):
    path=Path(path).resolve()
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=timeout)
    try:
        # Ledger state and observations belong to the same SQLite snapshot.
        conn.execute('BEGIN')
        tables={r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        present=tables & LEDGER
        if present and present!=LEDGER:raise sqlite3.DatabaseError('Incomplete historical batch ledger')
        if present:
            states=dict(conn.execute('''SELECT b.batch_id,
                (SELECT action FROM main.archive_batch_events e WHERE e.batch_id=b.batch_id ORDER BY id DESC LIMIT 1)
                FROM main.archive_batches b'''))
            if any(v not in ('active','inactive') for v in states.values()):
                raise sqlite3.DatabaseError('Batch has missing or invalid effective state')
            keys=conn.execute('SELECT batch_id,fuente,sensor_id,fecha_utc,contaminante FROM main.archive_batch_keys').fetchall()
            if any(r[0] not in states or r[1]!='OpenAQ-Archive' or r[4]!='pm25' for r in keys):
                raise sqlite3.DatabaseError('Invalid batch ownership; no geographic/source reassignment allowed')
            if conn.execute('''SELECT 1 FROM main.archive_batch_keys k WHERE NOT EXISTS
                (SELECT 1 FROM main.mediciones m WHERE '''+match('m','k')+') LIMIT 1').fetchone():
                raise sqlite3.DatabaseError('Batch key has no original measurement')
            excluded=[r[1:] for r in keys if states[r[0]]=='inactive']
            if excluded: _install(conn,tables,excluded)
        conn.execute('PRAGMA query_only=ON')
        return conn
    except BaseException:
        conn.close();raise


def _install(conn,tables,excluded):
    conn.execute('''CREATE TEMP TABLE _aeris_excluded_keys (
        fuente TEXT,sensor_id INTEGER,fecha_utc TEXT,contaminante TEXT,
        PRIMARY KEY(fuente,sensor_id,fecha_utc,contaminante))''')
    conn.executemany('INSERT INTO _aeris_excluded_keys VALUES (?,?,?,?)',excluded)
    conn.execute('''CREATE TEMP VIEW mediciones AS SELECT m.* FROM main.mediciones m
        WHERE NOT EXISTS (SELECT 1 FROM temp._aeris_excluded_keys x WHERE '''+match('m','x')+')')
    # A visible successor may have a stored jump flag that depended on a withdrawn row.
    # Keep the observation but expose its quality as pending rather than invent new flags.
    conn.execute('''CREATE TEMP TABLE _aeris_pending_quality (
        fuente TEXT,sensor_id INTEGER,fecha_utc TEXT,contaminante TEXT,
        PRIMARY KEY(fuente,sensor_id,fecha_utc,contaminante))''')
    if 'calidad_mediciones' in tables:
        conn.execute('''INSERT INTO temp._aeris_pending_quality
            SELECT p.fuente,p.sensor_id,p.fecha_utc,p.contaminante FROM
            (SELECT m.*,LAG(fecha_utc) OVER (PARTITION BY fuente,sensor_id,contaminante
             ORDER BY julianday(fecha_utc),fecha_utc) previous_stamp FROM main.mediciones m) p
            JOIN main.calidad_mediciones q ON '''+match('p','q')+'''
            WHERE NOT EXISTS (SELECT 1 FROM temp._aeris_excluded_keys x WHERE '''+match('p','x')+''')
            AND EXISTS (SELECT 1 FROM temp._aeris_excluded_keys x
                WHERE x.fuente=p.fuente AND x.sensor_id=p.sensor_id AND x.contaminante=p.contaminante
                AND x.fecha_utc=p.previous_stamp)
            AND (q.version_reglas<>'aeris_qc_v2' OR ABS((julianday(p.fecha_utc)-julianday(p.previous_stamp))*24-1)<0.00001)''')
        conn.execute('''CREATE TEMP VIEW calidad_mediciones AS SELECT q.* FROM main.calidad_mediciones q
            WHERE EXISTS (SELECT 1 FROM temp.mediciones m WHERE '''+match('m','q')+''')
            AND NOT EXISTS (SELECT 1 FROM temp._aeris_pending_quality p WHERE '''+match('p','q')+')')
    if 'evaluaciones_calidad' in tables:
        if conn.execute("SELECT 1 FROM main.evaluaciones_calidad WHERE NOT json_valid(contexto_json) LIMIT 1").fetchone():
            raise sqlite3.DatabaseError('Invalid assessment context')
        conn.execute('''CREATE TEMP VIEW evaluaciones_calidad AS SELECT e.* FROM main.evaluaciones_calidad e
            WHERE EXISTS (SELECT 1 FROM temp.mediciones m WHERE '''+match('m','e')+''')
            AND NOT EXISTS (SELECT 1 FROM temp._aeris_pending_quality p WHERE '''+match('p','e')+''')
            AND NOT EXISTS (SELECT 1 FROM temp._aeris_excluded_keys x
              WHERE x.fuente=e.fuente AND x.sensor_id=e.sensor_id AND x.contaminante=e.contaminante
              AND julianday(x.fecha_utc)=julianday(COALESCE(json_extract(e.contexto_json,'$.previous.stored_timestamp'),
                                                        json_extract(e.contexto_json,'$.previous.utc'))))''')
        if 'evaluaciones_calidad_ingestas' in tables:
            conn.execute('''CREATE TEMP VIEW evaluaciones_calidad_ingestas AS SELECT l.*
                FROM main.evaluaciones_calidad_ingestas l
                WHERE EXISTS (SELECT 1 FROM temp.evaluaciones_calidad e WHERE e.id=l.evaluacion_id)''')
