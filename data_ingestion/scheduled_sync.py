"""Recurring controlled entry point. Registration is deliberately external."""
import argparse
import json
import os
import sqlite3
import uuid
from contextlib import closing, nullcontext
from pathlib import Path
from unittest.mock import patch

from . import operations as ops
from . import retention
from .controlled_run import CriticalConnection, CriticalFailure, require, compare_original
from .production_preflight import snapshot, sha


def run(db, **kwargs):
    db = Path(db).resolve()
    require(db.is_file(), 'Database must already exist')
    audit = {'started_at_utc': ops.iso(ops.utcnow()), 'database': str(db),
             'status': 'checking', 'flow': 'operations.run -> store_sensor -> quality_versioned.evaluate'}
    directory = db.parent / 'sync_runtime' / 'scheduler'
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / (uuid.uuid4().hex + '.json')
    real_connect, real_copy = sqlite3.connect, ops.copy_database
    baseline = None

    def preserve(conn):
        require(baseline is not None, 'Verified backup required before writes')
        compare_original(conn, baseline)
        with closing(real_connect(baseline.as_uri() + '?mode=ro', uri=True)) as previous:
            for table in ('evaluaciones_calidad', 'reglas_calidad_versionadas', 'evaluaciones_calidad_ingestas'):
                if previous.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                    require(set(previous.execute('SELECT * FROM ' + table)).issubset(
                        set(conn.execute('SELECT * FROM ' + table))), 'Historical ledger changed: ' + table)
        require(not conn.execute('PRAGMA foreign_key_check').fetchall(), 'Foreign key violation')

    class GuardedConnection(CriticalConnection):
        def commit(self):
            try:
                preserve(self)
                return super().commit()
            except BaseException:
                self.rollback()
                raise

        def __exit__(self, kind, value, traceback):
            if kind is None:
                try:
                    preserve(self)
                except BaseException:
                    self.rollback()
                    raise
            return super().__exit__(kind, value, traceback)

    def connect(path, *args, **options):
        if str(path) == str(db):
            options['factory'] = GuardedConnection
        return real_connect(path, *args, **options)

    def verified_copy(source, destination):
        nonlocal baseline
        real_copy(source, destination)
        require(snapshot(source) == snapshot(destination), 'Backup contents differ')
        baseline = Path(destination).resolve()
        audit['backup'] = {'path': str(baseline), 'sha256': sha(baseline), 'verified': True}

    try:
        with ops.exclusive_lock(Path(str(db) + '.sync.lock')):
            before = snapshot(db)
            require(before['integrity_check'] == ['ok'] and before['foreign_key_violations'] == 0,
                    'Initial SQLite integrity failed')
            audit['before'] = before
            with patch.object(ops, 'exclusive_lock', lambda _: nullcontext()), \
                    patch.object(ops, 'copy_database', verified_copy), \
                    patch.object(sqlite3, 'connect', connect):
                result = ops.run(db, list(ops.ACTIVE), **kwargs)
            with closing(real_connect(db.as_uri() + '?mode=ro', uri=True)) as conn:
                preserve(conn)
            audit['after'] = snapshot(db)
            require(audit['after']['integrity_check'] == ['ok'], 'Final integrity failed')
            audit.update(status=result['status'], synchronization=result)
            if result['status'] == 'success':
                # Still under the lock; the verified baseline of this run is always kept.
                # A retention failure is recorded but never turns a success into a failure.
                try:
                    audit['retention'] = retention.prune(db.parent / 'backups', apply=True,
                                                         protect=[baseline] if baseline else ())
                except Exception as exc:
                    audit['retention'] = {'applied': False, 'error_type': type(exc).__name__}
            return audit
    except BaseException as exc:
        # Exception text can contain HTTP/authentication details; do not persist it.
        audit.update(status='critical_failure', error_type=type(exc).__name__)
        raise
    finally:
        audit['finished_at_utc'] = ops.iso(ops.utcnow())
        report_path.write_text(json.dumps(audit, ensure_ascii=True, indent=2), encoding='utf8')
        # Unique per-run files are authoritative; a failed attempt cannot erase last success.
        if audit['status'] == 'success':
            latest = directory / 'last_success.json'
            temporary = directory / ('last_success.' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(audit, ensure_ascii=True, indent=2), encoding='utf8')
            temporary.replace(latest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--replay-audit', type=Path, help='Offline recorded replay; never allowed on production SQLite')
    args = parser.parse_args(argv)
    if Path(str(args.db.resolve()) + '.sync.stop').exists():
        print('Synchronization paused'); return 0
    try:
        from .windows_credentials import load_key
        key = load_key(args.key_file)
        options = {}
        if args.replay_audit:
            production = ops.ROOT / 'data/aeris_air_quality.db'
            require(args.db.resolve() != production.resolve() and not os.path.samefile(args.db, production),
                    'Recorded replay forbidden on original database')
            from .controlled_run import CachedClient
            audit = json.loads(args.replay_audit.read_text(encoding='utf8'))
            cache = CachedClient(None)
            for item in audit['retained_api_responses']:
                path = Path(item['local_path'])
                require(sha(path) == item['sha256'], 'Recorded response hash mismatch')
                cache.payloads[(item['path'], json.dumps(item['params'], sort_keys=True))] = json.loads(path.read_text(encoding='utf8'))
            cache.frozen = True
            windows = {(r['window_from_utc'], r['window_to_utc_exclusive']) for r in audit['synchronization']['results']}
            require(len(windows) == 1, 'Replay requires a common verified window')
            start, end = next(iter(windows))
            options = {'client': cache, 'start': ops.parse_utc(start), 'end': ops.parse_utc(end)}
        result = run(args.db, key=key, **options)
        return 0 if result['status'] == 'success' else 1
    except BaseException as exc:
        directory = args.db.resolve().parent / 'sync_runtime/scheduler'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ('entry-' + uuid.uuid4().hex + '.json')).write_text(json.dumps({
            'status': 'entry_failure', 'error_type': type(exc).__name__,
            'finished_at_utc': ops.iso(ops.utcnow())}), encoding='utf8')
        print('Controlled synchronization failed; inspect scheduler audit'); return 1


if __name__ == '__main__':
    raise SystemExit(main())
