"""Calidad aditiva: primera evaluacion inmutable y reevaluaciones con contexto."""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .quality import VERSION, ensure_quality

KEY=('fuente','sensor_id','fecha_utc','contaminante')
FLAGS=('es_cero','es_extremo','salto_abrupto','requiere_revision')
V2_DEFINITION={'version':VERSION,'zero':'value == 0','extreme':'value > 100',
               'jump':'abs(value - previous_value) >= 100 only for exactly one elapsed hour',
               'review':'negative or extreme or jump','order':'UTC ascending',
               'lookahead':False,'interpolation':False,'unit':'µg/m³'}


def encoded(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode('utf8')).hexdigest()
def registered_now():return datetime.now(timezone.utc).isoformat()


def utc(stamp):
    value=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Calidad requiere zona horaria explicita')
    value=value.astimezone(timezone.utc)
    if value.minute or value.second or value.microsecond:raise ValueError('Calidad requiere hora entera')
    return value


def calculate(rows):
    """Tuplas (fecha, valor, unidad); reproduce v2 ordenando por instante real."""
    ordered=sorted(rows,key=lambda row:utc(row[0]));previous=None;seen=set();result=[]
    for stamp,value,unit in ordered:
        point=utc(stamp)
        if point in seen:raise ValueError('Instante UTC duplicado: evaluacion ambigua')
        seen.add(point)
        if not math.isfinite(value):raise ValueError('Valor no finito en calidad')
        adjacent=previous is not None and point-previous[0]==timedelta(hours=1)
        jump=int(adjacent and abs(value-previous[2])>=100)
        extreme=int(value>100);flags=(int(value==0),extreme,jump,int(value<0 or extreme or jump))
        context={'schema':'aeris-qc-input-v1','current':{'stored_timestamp':stamp,'utc':point.isoformat(),
                 'value':value,'unit':unit},'previous':None if previous is None else {
                 'stored_timestamp':previous[1],'utc':previous[0].isoformat(),'value':previous[2],
                 'unit':previous[3]},'previous_is_adjacent':adjacent,'future_observations_used':False}
        result.append({'timestamp':stamp,'flags':flags,'context':context,'context_sha256':digest(context)})
        previous=(point,stamp,value,unit)
    return result


def ensure_versioned(conn):
    ensure_quality(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS reglas_calidad_versionadas (
        version_reglas TEXT PRIMARY KEY,definicion_json TEXT NOT NULL,definicion_sha256 TEXT NOT NULL,
        codigo_referencia_sha256 TEXT,es_ejecutable INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS evaluaciones_calidad (
        id INTEGER PRIMARY KEY,fuente TEXT NOT NULL,sensor_id INTEGER NOT NULL,fecha_utc TEXT NOT NULL,
        contaminante TEXT NOT NULL,version_reglas TEXT NOT NULL,
        es_cero INTEGER NOT NULL,es_extremo INTEGER NOT NULL,salto_abrupto INTEGER NOT NULL,
        requiere_revision INTEGER NOT NULL,contexto_sha256 TEXT NOT NULL,contexto_json TEXT NOT NULL,
        origen TEXT NOT NULL,registrada_utc TEXT NOT NULL,evaluada_originalmente_utc TEXT,
        codigo_evaluador_sha256 TEXT,
        UNIQUE(fuente,sensor_id,fecha_utc,contaminante,version_reglas,contexto_sha256),
        FOREIGN KEY(fuente,sensor_id,fecha_utc,contaminante)
            REFERENCES mediciones(fuente,sensor_id,fecha_utc,contaminante),
        FOREIGN KEY(version_reglas) REFERENCES reglas_calidad_versionadas(version_reglas))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS evaluaciones_calidad_ingestas (
        ingesta_id TEXT NOT NULL,evaluacion_id INTEGER NOT NULL,
        PRIMARY KEY(ingesta_id,evaluacion_id),
        FOREIGN KEY(ingesta_id) REFERENCES ingestas(id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(evaluacion_id) REFERENCES evaluaciones_calidad(id))''')
    # La tabla consumida por Flask conserva siempre la primera evaluacion.
    for table in ('calidad_mediciones','reglas_calidad_versionadas','evaluaciones_calidad','evaluaciones_calidad_ingestas'):
        for action in ('UPDATE','DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_inmutable_{action.lower()}
                BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Calidad historica inmutable; registrar otra evaluacion'); END''')
    reference=hashlib.sha256(Path(__file__).with_name('quality.py').read_bytes()).hexdigest()
    versions={r[0] for r in conn.execute('SELECT DISTINCT version_reglas FROM calidad_mediciones')}|{VERSION}
    for version in versions:
        definition=V2_DEFINITION if version==VERSION else {
            'version':version,'status':'legacy_snapshot_only','executable_historical_source_available':False,
            'original_evaluation_context':'unknown; not reconstructed as fact'}
        entry=(version,encoded(definition),digest(definition),reference if version==VERSION else None,int(version==VERSION))
        old=conn.execute('SELECT * FROM reglas_calidad_versionadas WHERE version_reglas=?',(version,)).fetchone()
        if old is not None and tuple(old)!=entry:raise ValueError('La definicion de una version no puede cambiar')
        if old is None:conn.execute('INSERT INTO reglas_calidad_versionadas VALUES (?,?,?,?,?)',entry)
    rows=conn.execute('''SELECT q.* FROM calidad_mediciones q WHERE NOT EXISTS
        (SELECT 1 FROM evaluaciones_calidad e WHERE e.fuente=q.fuente AND e.sensor_id=q.sensor_id
         AND e.fecha_utc=q.fecha_utc AND e.contaminante=q.contaminante)''').fetchall()
    now=registered_now()
    for row in rows:
        context={'schema':'legacy-stored-assessment-v1','stored_row':list(row),
                 'original_input_context':'unknown','original_evaluation_time':'unknown'}
        conn.execute('''INSERT INTO evaluaciones_calidad
            (fuente,sensor_id,fecha_utc,contaminante,version_reglas,es_cero,es_extremo,salto_abrupto,
             requiere_revision,contexto_sha256,contexto_json,origen,registrada_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (*row[:4],row[8],*row[4:8],digest(context),encoded(context),'original_snapshot',now))


def evaluate(conn,sensor_id,source='OpenAQ',run_id=None):
    ensure_versioned(conn)
    rows=conn.execute("SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND contaminante='pm25'",
                      (source,sensor_id)).fetchall()
    evaluations=calculate(rows);new_initial=created=0
    implementation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();now=registered_now()
    for entry in evaluations:
        key=(source,sensor_id,entry['timestamp'],'pm25')
        old=conn.execute('SELECT 1 FROM calidad_mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?',key).fetchone()
        if old is None:
            conn.execute('INSERT INTO calidad_mediciones VALUES (?,?,?,?,?,?,?,?,?)',(*key,*entry['flags'],VERSION))
            new_initial+=1
        cursor=conn.execute('''INSERT OR IGNORE INTO evaluaciones_calidad
            (fuente,sensor_id,fecha_utc,contaminante,version_reglas,es_cero,es_extremo,salto_abrupto,
             requiere_revision,contexto_sha256,contexto_json,origen,registrada_utc,codigo_evaluador_sha256)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (*key,VERSION,*entry['flags'],entry['context_sha256'],encoded(entry['context']),
             'initial_current' if old is None else 'reevaluation',now,implementation))
        created+=int(cursor.rowcount>0)
        assessment=conn.execute('''SELECT id,es_cero,es_extremo,salto_abrupto,requiere_revision FROM evaluaciones_calidad
            WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=? AND version_reglas=? AND contexto_sha256=?''',
            (*key,VERSION,entry['context_sha256'])).fetchone()
        if tuple(assessment[1:])!=entry['flags']:raise ValueError('Mismo contexto y version con resultado distinto')
        if run_id is not None:
            conn.execute('INSERT OR IGNORE INTO evaluaciones_calidad_ingestas VALUES (?,?)',(run_id,assessment[0]))
    return {'version':VERSION,'evaluated':len(evaluations),'new_initial_quality':new_initial,
            'new_versioned_assessments':created,'reused_versioned_assessments':len(evaluations)-created,
            'original_quality_rows_overwritten':0}


def verify_current(conn,sensor_id,source='OpenAQ'):
    """Comprueba la evaluacion por contexto/version, sin tocar la primera evaluacion."""
    rows=conn.execute("SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND contaminante='pm25'",
                      (source,sensor_id)).fetchall()
    for entry in calculate(rows):
        actual=conn.execute('''SELECT es_cero,es_extremo,salto_abrupto,requiere_revision FROM evaluaciones_calidad
            WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante='pm25'
            AND version_reglas=? AND contexto_sha256=?''',
            (source,sensor_id,entry['timestamp'],VERSION,entry['context_sha256'])).fetchone()
        if actual is None or tuple(actual)!=entry['flags']:raise ValueError('Falta evaluacion reproducible del contexto actual')
    return len(rows)
