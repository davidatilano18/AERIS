"""Prepare and audit a real, sanitized demo derivative. No network or Git writes."""
import hashlib
import json
import re
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_web_snapshot import prepare, sha, public_url
from scripts.audit_web_release import PATTERNS
from data_ingestion.visibility import connect_readonly
from railway_start import verify


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def fingerprint(rows):
    encoded = sorted(json.dumps(tuple(row), ensure_ascii=False, allow_nan=False,
                                default=lambda value: value.hex()) for row in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def main():
    source = ROOT / 'data/aeris_air_quality.db'
    start_hash = sha(source)
    expected = {}
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        integrity = con.execute('PRAGMA integrity_check').fetchall()
        fk = con.execute('PRAGMA foreign_key_check').fetchall()
        if integrity != [('ok',)] or fk:
            raise RuntimeError('Production read-only integrity check failed')
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            columns = [r[1] for r in con.execute('PRAGMA table_info(' + quoted(table) + ')')]
            rows = con.execute('SELECT * FROM ' + quoted(table)).fetchall()
            normalized = []
            for row in rows:
                values = list(row)
                for index, column in enumerate(columns):
                    if column == 'ruta_local':
                        values[index] = '[withheld]'
                    elif column == 'reporte_json':
                        values[index] = '{}'
                    elif column == 'url':
                        values[index] = public_url(values[index])
                normalized.append(values)
            expected[table] = dict(rows=len(rows), expected_sha256=fingerprint(normalized),
                                   original_sha256=fingerprint(rows))
    directory = ROOT / 'reports/beta_snapshots' / ('demo-20261022-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    # Fail before creating any derivative if its path would not be ignored.
    ignored = subprocess.run(['git', 'check-ignore', str((directory / 'aeris.db').relative_to(ROOT))],
                             cwd=ROOT, capture_output=True)
    if ignored.returncode != 0:
        raise RuntimeError('Snapshot output must be excluded from Git')
    manifest = prepare(source, directory)
    db = directory / 'aeris.db'
    if sha(source) != start_hash:
        raise RuntimeError('Source changed concurrently; retain derivative but do not approve it against old fingerprints')
    findings, comparisons, scanned = [], {}, 0
    patterns = PATTERNS | {
        'credential-field-value': rb'''(?i)(?:api[_-]?key|x-api-key|authorization|password|passwd|access[_-]?token|secret)["'\s:=]+[A-Za-z0-9_+/=.-]{12,}''',
        'local-windows-user-path': rb'(?i)[a-z]:[\\/]Users[\\/]',
    }
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        for table in tables:
            columns = [r[1] for r in con.execute('PRAGMA table_info(' + quoted(table) + ')')]
            rows = con.execute('SELECT * FROM ' + quoted(table)).fetchall()
            comparisons[table] = fingerprint(rows) == expected[table]['expected_sha256']
            for row in rows:
                for column, value in zip(columns, row):
                    if not isinstance(value, str):
                        continue
                    scanned += 1
                    content = value.encode()
                    for label, pattern in patterns.items():
                        if re.search(pattern, content):
                            findings.append(dict(table=table, column=column, kind=label))
                    if column == 'url':
                        url = urlsplit(value)
                        if url.query or url.username or url.password:
                            findings.append(dict(table=table, column=column, kind='URL retains query/credentials'))
                    if column.lower() in ('api_key', 'password', 'secret', 'access_token') and value:
                        findings.append(dict(table=table, column=column, kind='Nonempty credential column'))
        copy_integrity = con.execute('PRAGMA integrity_check').fetchall()
        copy_fk = con.execute('PRAGMA foreign_key_check').fetchall()
        latest = con.execute("SELECT MAX(fecha_utc) FROM mediciones WHERE lower(contaminante)='pm25'").fetchone()[0]
        by_source = con.execute('SELECT fuente,COUNT(*) FROM mediciones GROUP BY fuente').fetchall()
        by_station = con.execute('SELECT fuente,sensor_id,COUNT(*),MAX(fecha_utc) FROM mediciones GROUP BY fuente,sensor_id ORDER BY fuente,sensor_id').fetchall()
    if not all(comparisons.values()) or findings or copy_integrity != [('ok',)] or copy_fk:
        report = dict(approved=False, findings=findings, comparisons=comparisons)
        (directory / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise RuntimeError('Derivative audit failed; no upload authorized')
    verify(db, manifest['sha256'])
    with closing(connect_readonly(db)) as con:
        try:
            con.execute('UPDATE mediciones SET valor=valor WHERE 0')
        except sqlite3.OperationalError:
            sql_readonly = True
        else:
            raise RuntimeError('Reader accepted a write')
    db.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    with closing(sqlite3.connect(db)) as con:
        try:
            con.execute('UPDATE mediciones SET valor=valor WHERE 0')
        except sqlite3.OperationalError as exc:
            if 'readonly' not in str(exc).lower():
                raise
            physical_readonly = True
        else:
            con.rollback()
            raise RuntimeError('Physical readonly attribute not enforced')
    assert sha(db) == manifest['sha256']
    assert sha(source) == start_hash
    latest_dt = datetime.fromisoformat(latest.replace('Z', '+00:00'))
    created = datetime.fromisoformat(manifest['created_utc'])
    report = dict(approved_local=True, uploaded=False, source='data/aeris_air_quality.db',
                  source_bytes=source.stat().st_size, source_integrity=integrity, source_foreign_keys=fk,
                  source_sha_before=start_hash, source_sha_after=sha(source),
                  snapshot=str(db.relative_to(ROOT)), snapshot_bytes=db.stat().st_size,
                  snapshot_MB=db.stat().st_size/1_000_000, snapshot_MiB=db.stat().st_size/1_048_576,
                  created_utc=manifest['created_utc'], latest_pm25_utc=latest,
                  age_hours_at_creation=(created-latest_dt).total_seconds()/3600,
                  sha256=manifest['sha256'], rows=manifest['rows'], rows_by_source=by_source,
                  rows_by_station=by_station, table_comparisons=comparisons,
                  unchanged_tables=[t for t in tables if expected[t]['original_sha256']==expected[t]['expected_sha256']],
                  redactions=manifest['redactions'], integrity=copy_integrity, foreign_keys=copy_fk,
                  text_cells_scanned=scanned, sensitive_findings=findings,
                  sql_readonly=sql_readonly, windows_readonly_verified=physical_readonly,
                  remote_path='/dataset/demo-20261022/aeris.db',
                  caveat='Pattern scan is not universal secret certification; Linux UID/directory permissions remain pending')
    (directory / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (ROOT / 'reports/aeris_railway_demo_snapshot.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
