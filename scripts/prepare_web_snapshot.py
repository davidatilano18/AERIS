"""Create a sanitized derivative via Backup API; source is always opened mode=ro.

This is a web dataset, never a replacement or audit archive for production.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def public_url(value):
    parts = urlsplit(value)
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        return '[withheld]'
    # Preserve distinct response identities when pagination/filter queries differ.
    # The opaque fragment is not the original query and is never used for fetching.
    identity = 'withheld-' + hashlib.sha256(value.encode()).hexdigest()
    return urlunsplit((parts.scheme, parts.hostname, parts.path, '', identity))


def prepare(source, directory):
    source, directory = Path(source).resolve(), Path(directory).resolve()
    if not source.is_file():
        raise ValueError('Source must exist')
    if directory == source.parent or directory == ROOT / 'static' or ROOT / 'static' in directory.parents:
        raise ValueError('Snapshot must be separate from production and static assets')
    # New directory only: no overwritten snapshot and no automatic cleanup on failure.
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / 'aeris.db'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        original.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy)
            tables = {r[0] for r in copy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            science = {'mediciones', 'calidad_mediciones', 'evaluaciones_calidad',
                       'archive_batches', 'archive_batch_keys', 'archive_batch_events'} & tables
            before = {t: copy.execute('SELECT * FROM "' + t + '"').fetchall() for t in science}
            redactions = []
            # Operational reports can contain machine paths. Keep identifiers, states,
            # timestamps, hashes, science tables and source linkage; withhold report payloads.
            with copy:
                for table in sorted(tables):
                    columns = {r[1] for r in copy.execute('PRAGMA table_info("' + table + '")')}
                    for column in columns & {'ruta_local', 'reporte_json'}:
                        copy.execute('UPDATE "' + table + '" SET "' + column + '"=?',
                                     ('{}' if column.endswith('_json') else '[withheld]',))
                        redactions.append(table + '.' + column)
                    if 'url' in columns:
                        for (url,) in copy.execute('SELECT DISTINCT url FROM "' + table + '"').fetchall():
                            copy.execute('UPDATE "' + table + '" SET url=? WHERE url=?', (public_url(url), url))
                        redactions.append(table + '.url:query-and-userinfo')
            if any(before[t] != copy.execute('SELECT * FROM "' + t + '"').fetchall() for t in science):
                raise RuntimeError('Scientific or ledger data changed')
            if copy.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or copy.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Invalid snapshot')
            counts = {t: copy.execute('SELECT COUNT(*) FROM "' + t + '"').fetchone()[0] for t in tables}
            # Remove obsolete payloads from free pages of the derivative only.
            copy.execute('VACUUM')
    manifest = dict(format='aeris-web-snapshot-v1', created_utc=datetime.now(timezone.utc).isoformat(),
                    sha256=sha(target), rows=counts, redactions=redactions,
                    purpose='read-only web derivative; not a forensic backup',
                    requires_private_review=True)
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.source, args.output_dir)
    print(json.dumps(result, indent=2))
