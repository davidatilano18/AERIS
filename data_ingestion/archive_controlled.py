"""Offline, copy-only preparation of controlled Archive batches. No production writer CLI."""
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import quality_versioned as qc
from .operations import exclusive_lock

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT/'data/aeris_air_quality.db'
SOURCE = 'OpenAQ-Archive'
CONNECT = sqlite3.connect


def canonical(value): return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',',':'), allow_nan=False)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()


def check_copy(path):
    path = Path(path).resolve()
    # Preparation cannot accidentally become production execution, including aliases.
    if path == PRODUCTION.resolve() or not path.is_relative_to((ROOT/'reports').resolve()):
        raise ValueError('Only isolated report copies are enabled in this preparation')
    if not any(p.startswith('tmp_aeris_') for p in path.relative_to(ROOT/'reports').parts[:-1]) or not path.is_file():
        raise ValueError('Existing isolated temporary database required')
    if path.samefile(PRODUCTION): raise ValueError('Production file alias rejected')
    return path


def verify_bundle(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    descriptor = manifest['descriptor']
    if manifest['batch_id'] != hashlib.sha256(canonical(descriptor).encode()).hexdigest():
        raise ValueError('Bundle identity mismatch')
    for item in descriptor['evidence']:
        path = (folder/item['path']).resolve()
        if not path.is_relative_to(folder) or sha(path) != item['sha256']:
            raise ValueError('Evidence checksum/path mismatch')
    paths={i['path'] for i in descriptor['evidence']}
    required={'candidates.json','catalog.json','quality_definition.json','metadata/license36.json',
              'code/quality.py','code/quality_versioned.py','code/archive_controlled.py','code/visibility.py'}
    if not required<=paths:raise ValueError('Incomplete durable evidence')
    if json.loads((folder/'quality_definition.json').read_text(encoding='utf-8'))!=qc.V2_DEFINITION:
        raise ValueError('Quality rules changed since preparation')
    for name in ('quality.py','quality_versioned.py','archive_controlled.py','visibility.py'):
        if sha(folder/'code'/name)!=sha(Path(__file__).with_name(name)):
            raise ValueError('Evaluator/importer code differs from pinned evidence')
    candidates = json.loads((folder/'candidates.json').read_text(encoding='utf-8'))
    keys=set()
    from .plan_recovery import utc_hour
    import math
    for c in candidates:
        key=(c['source'],c['sensor_id'],c['utc'],c['pollutant'])
        if key in keys: raise ValueError('Duplicate candidate key in bundle')
        keys.add(key)
        if c['source'] != SOURCE or c['pollutant'] != 'pm25' or c['unit'] != 'µg/m³' or not math.isfinite(c['value']):
            raise ValueError('Unsupported source/unit/value')
        t=utc_hour(c['utc'])
        if not utc_hour('2025-05-01T07:00:00Z') <= t < utc_hour('2025-05-02T07:00:00Z'):
            raise ValueError('Outside May-2025 approved scope')
    if len(candidates)!=71 or {c['sensor_id'] for c in candidates}!={1352676,1352681,2694071}:
        raise ValueError('Unexpected scope')
    import csv,gzip,io
    for item in descriptor['archive_files']:
        if item['path'] not in paths or sha(folder/item['path'])!=item['sha256']:raise ValueError('Missing raw archive evidence')
        rows=list(csv.DictReader(io.StringIO(gzip.decompress((folder/item['path']).read_bytes()).decode('utf-8-sig'))))
        for c in (c for c in candidates if c['location_id']==item['location_id']):
            if c['file_sha256']!=item['sha256'] or rows[c['row_number']-2]!=c['original']:
                raise ValueError('Candidate no longer matches raw observation')
            original=c['original']
            if (int(original['sensors_id'])!=c['sensor_id'] or float(original['value'])!=c['value']
                    or original['units']!=c['unit'] or utc_hour(original['datetime'])!=utc_hour(c['utc'])):
                raise ValueError('Candidate identity/value mismatch')
    return manifest,candidates


def content(conn):
    return {t: list(conn.execute('SELECT * FROM "'+t.replace('"','""')+'"')) for (t,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}


def intact(conn, previous):
    for table,rows in previous.items():
        current=set(conn.execute('SELECT * FROM "'+table.replace('"','""')+'"'))
        if not set(rows)<=current: raise ValueError('Preexisting rows changed: '+table)
    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Integrity/foreign-key failure')


def ledger(conn):
    # Never use executescript: it could commit the active transaction.
    for sql in [
        '''CREATE TABLE IF NOT EXISTS archive_batches (
        batch_id TEXT PRIMARY KEY,manifest_sha256 TEXT NOT NULL,run_id TEXT NOT NULL,
        created_utc TEXT NOT NULL,report_json TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS archive_batch_keys (
        batch_id TEXT NOT NULL,fuente TEXT NOT NULL,sensor_id INTEGER NOT NULL,
        fecha_utc TEXT NOT NULL,contaminante TEXT NOT NULL,
        PRIMARY KEY(fuente,sensor_id,fecha_utc,contaminante),
        FOREIGN KEY(batch_id) REFERENCES archive_batches(batch_id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(fuente,sensor_id,fecha_utc,contaminante)
        REFERENCES mediciones(fuente,sensor_id,fecha_utc,contaminante))''',
        '''CREATE TABLE IF NOT EXISTS archive_batch_events (
        id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL,action TEXT NOT NULL CHECK(action IN ('active','inactive')),
        registered_utc TEXT NOT NULL,reason TEXT NOT NULL,
        FOREIGN KEY(batch_id) REFERENCES archive_batches(batch_id))''',
        '''CREATE VIEW IF NOT EXISTS aeris_visible_mediciones AS SELECT m.* FROM main.mediciones m
        WHERE NOT EXISTS (SELECT 1 FROM main.archive_batch_keys k
        WHERE k.fuente=m.fuente AND k.sensor_id=m.sensor_id AND k.fecha_utc=m.fecha_utc AND k.contaminante=m.contaminante
        AND (SELECT action FROM main.archive_batch_events e WHERE e.batch_id=k.batch_id ORDER BY id DESC LIMIT 1)='inactive')''']:
        conn.execute(sql)
    for table in ('archive_batches','archive_batch_keys','archive_batch_events'):
        for action in ('UPDATE','DELETE'):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only archive ledger'); END")


def scoped_quality(conn, before, changed, run_id):
    """Same v2 calculation; persist only new rows and successors whose full context changed."""
    qc.ensure_versioned(conn)
    added=initial=0
    code=sha(Path(qc.__file__))
    for sid in sorted({k[0] for k in changed}):
        rows=conn.execute("SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND contaminante='pm25'",(SOURCE,sid)).fetchall()
        for e in qc.calculate(rows):
            if before.get((sid,e['timestamp']))==e['context_sha256']: continue
            key=(SOURCE,sid,e['timestamp'],'pm25')
            old=conn.execute('SELECT 1 FROM calidad_mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?',key).fetchone()
            if old is None:
                conn.execute('INSERT INTO calidad_mediciones VALUES (?,?,?,?,?,?,?,?,?)',(*key,*e['flags'],qc.VERSION));initial+=1
            cursor=conn.execute('''INSERT OR IGNORE INTO evaluaciones_calidad
                (fuente,sensor_id,fecha_utc,contaminante,version_reglas,es_cero,es_extremo,salto_abrupto,requiere_revision,
                 contexto_sha256,contexto_json,origen,registrada_utc,codigo_evaluador_sha256)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (*key,qc.VERSION,*e['flags'],e['context_sha256'],qc.encoded(e['context']),
                 'initial_current' if old is None else 'reevaluation',now(),code))
            added+=int(cursor.rowcount>0)
            assessment=conn.execute('''SELECT id,es_cero,es_extremo,salto_abrupto,requiere_revision FROM evaluaciones_calidad
                WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=? AND version_reglas=? AND contexto_sha256=?''',
                (*key,qc.VERSION,e['context_sha256'])).fetchone()
            if tuple(assessment[1:])!=e['flags']:raise ValueError('QC context/version collision')
            conn.execute('INSERT OR IGNORE INTO evaluaciones_calidad_ingestas VALUES (?,?)',(run_id,assessment[0]))
    return {'initial':initial,'assessments':added,'historical_reevaluations':added-initial}


def _import_copy(folder, db, fault=None):
    db=check_copy(db); bundle,candidates=verify_bundle(folder);batch=bundle['batch_id']
    with exclusive_lock(Path(str(db)+'.sync.lock')):
        with closing(CONNECT(db)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Initial integrity check failed')
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='archive_batches'").fetchone():
                old=conn.execute('SELECT report_json,manifest_sha256 FROM archive_batches WHERE batch_id=?',(batch,)).fetchone()
                if old:
                    if old[1]!=sha(Path(folder)/'manifest.json'):raise ValueError('Batch manifest changed')
                    for c in candidates:
                        row=conn.execute('SELECT valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?',
                                         (c['source'],c['sensor_id'],c['utc'],c['pollutant'])).fetchone()
                        if row!=(c['value'],c['unit']):raise ValueError('Previously imported candidate changed')
                    return dict(json.loads(old[0]),idempotent=True,identical=len(candidates),new_measurements=0,new_assessments=0,
                                quality={'initial':0,'assessments':0,'historical_reevaluations':0})
            previous=content(conn); intact(conn,previous)
            backup=db.parent/'backups'/('before_controlled_archive_'+uuid.uuid4().hex+'.db')
            backup.parent.mkdir(exist_ok=True)
            with closing(CONNECT(backup)) as target: conn.backup(target)
            with closing(CONNECT(backup.as_uri()+'?mode=ro',uri=True)) as target:
                if content(target)!=previous:raise ValueError('Backup mismatch')
                intact(target,previous)
            run_id=uuid.uuid4().hex
            conn.execute('BEGIN IMMEDIATE')
            try:
                ledger(conn)
                before={}
                for sid in {c['sensor_id'] for c in candidates}:
                    rows=conn.execute("SELECT fecha_utc,valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND contaminante='pm25'",(SOURCE,sid)).fetchall()
                    before.update({(sid,e['timestamp']):e['context_sha256'] for e in qc.calculate(rows)})
                changed=set();identical=0
                for i,c in enumerate(candidates):
                    key=(SOURCE,c['sensor_id'],c['utc'],'pm25')
                    old=conn.execute('SELECT valor,unidad FROM mediciones WHERE fuente=? AND sensor_id=? AND fecha_utc=? AND contaminante=?',key).fetchone()
                    if old:
                        if old!=(c['value'],c['unit']):raise ValueError('Candidate conflict; nothing committed')
                        identical+=1;continue
                    # Never count a cross-source publication as an independent observation.
                    if conn.execute('SELECT 1 FROM mediciones WHERE sensor_id=? AND fecha_utc=? AND contaminante=?',(c['sensor_id'],c['utc'],'pm25')).fetchone():
                        raise ValueError('Cross-source identity requires review')
                    conn.execute('INSERT INTO mediciones VALUES (?,?,?,?,?,?)',(*key,c['value'],c['unit']))
                    conn.execute('INSERT INTO archive_batch_keys VALUES (?,?,?,?,?)',(batch,*key))
                    changed.add((c['sensor_id'],c['utc']))
                    if fault: fault('after_insert',conn,i)
                if len(changed)!=len(candidates):
                    raise ValueError('Unowned identical candidates require provenance review; no partial batch committed')
                quality=scoped_quality(conn,before,changed,run_id)
                for item in bundle['descriptor']['archive_files']:
                    conn.execute('INSERT OR IGNORE INTO archivos_origen VALUES (?,?,?,?)',
                                 (item['sha256'],item['url'],str(Path(folder).resolve()/item['path']),item['downloaded_at_utc']))
                for c in candidates:
                    conn.execute('INSERT OR IGNORE INTO observaciones_archivo VALUES (?,?,?,?,?,?,?)',
                        (c['file_sha256'],c['row_number'],SOURCE,c['sensor_id'],c['utc'],c['value'],1))
                report={'batch_id':batch,'run_id':run_id,'new_measurements':len(changed),'identical':identical,
                        'new_assessments':quality['assessments'],'quality':quality,'backup':str(backup),
                        'backup_sha256':sha(backup),'idempotent':False}
                conn.execute('INSERT INTO ingestas VALUES (?,?,?,?,?)',(run_id,now(),now(),'success',canonical(report)))
                conn.execute('INSERT INTO archive_batches VALUES (?,?,?,?,?)',(batch,sha(Path(folder)/'manifest.json'),run_id,now(),canonical(report)))
                conn.execute('INSERT INTO archive_batch_events(batch_id,action,registered_utc,reason) VALUES (?,?,?,?)',(batch,'active',now(),'Isolated controlled rehearsal'))
                if fault:fault('before_commit',conn,None)
                intact(conn,previous)
                conn.commit()
                return report
            except BaseException:
                conn.rollback();raise


def import_copy(folder,db,fault=None):
    db=check_copy(db)
    directory=db.parent/'archive_audits';directory.mkdir(exist_ok=True)
    attempt=uuid.uuid4().hex;journal=directory/(attempt+'.jsonl')
    def event(value):
        with journal.open('a',encoding='utf-8') as out:
            out.write(canonical(dict(value,attempt_id=attempt,recorded_utc=now()))+'\n');out.flush();os.fsync(out.fileno())
    event({'state':'started','database':str(db),'bundle':str(Path(folder).resolve())})
    try:
        result=_import_copy(folder,db,fault)
    except BaseException as exc:
        event({'state':'failed','error_type':type(exc).__name__});raise
    event({'state':'success','result':result})
    return result


def set_visibility(db,batch,action,reason):
    db=check_copy(db)
    if action not in ('active','inactive') or not reason:raise ValueError('Explicit visibility action and reason required')
    with exclusive_lock(Path(str(db)+'.sync.lock')),closing(CONNECT(db)) as conn,conn:
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM archive_batches WHERE batch_id=?',(batch,)).fetchone():raise ValueError('Unknown batch')
        current=conn.execute('SELECT action FROM archive_batch_events WHERE batch_id=? ORDER BY id DESC LIMIT 1',(batch,)).fetchone()
        if current and current[0]==action:return False
        conn.execute('INSERT INTO archive_batch_events(batch_id,action,registered_utc,reason) VALUES (?,?,?,?)',(batch,action,now(),reason))
        if conn.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Invalid rollback ledger')
        return True


def visible_connection(path):
    """Opt-in read adapter. NOT installed in the running Flask app or scheduler."""
    from .visibility import connect_readonly
    return connect_readonly(path)
