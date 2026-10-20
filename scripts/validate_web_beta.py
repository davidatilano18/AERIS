"""Offline web smoke test against a new sanitized snapshot. No sync or HTTP listener."""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_web_snapshot import prepare, sha


def main():
    source = ROOT / 'data' / 'aeris_air_quality.db'
    before = sha(source)
    directory = Path(tempfile.mkdtemp(prefix='tmp_aeris_web_beta_', dir=ROOT / 'reports'))
    snapshot = directory / 'dataset'
    manifest = prepare(source, snapshot)
    os.environ.update(AERIS_ENV='beta', AERIS_DB_PATH=str(snapshot / 'aeris.db'),
                      AERIS_DATASET_MANIFEST=str(snapshot / 'manifest.json'),
                      AERIS_TRUSTED_HOSTS='localhost,127.0.0.1')
    if os.environ.get('OPENAQ_API_KEY'):
        raise RuntimeError('Remove ingestion credential from this test process first')
    import wsgi
    client = wsgi.application.test_client()
    routes = ['/', '/v2', '/v2/datos', '/api/overview', '/api/measurements',
              '/api/comparison', '/api/export.csv', '/api/v2/observations',
              '/api/v2/stations', '/api/v2/public', '/api/v2/comparison?station=1352676',
              '/health/live', '/health/ready', '/static/v2/css/dashboard.css',
              '/static/v2/js/public.js', '/logo.png']
    statuses = {route: client.get(route).status_code for route in routes}
    if any(status != 200 for status in statuses.values()):
        raise RuntimeError('Route smoke test failed: ' + str(statuses))
    with closing(sqlite3.connect((snapshot / 'aeris.db').as_uri() + '?mode=ro', uri=True)) as con:
        integrity = con.execute('PRAGMA integrity_check').fetchall()
        fk = con.execute('PRAGMA foreign_key_check').fetchall()
    # Main is ro even if the operating-system user owns the derivative file.
    from data_ingestion.visibility import connect_readonly
    with closing(connect_readonly(snapshot / 'aeris.db')) as con:
        try:
            con.execute('DELETE FROM mediciones')
        except sqlite3.OperationalError:
            denied = True
        else:
            raise RuntimeError('Write unexpectedly permitted')
    result = dict(snapshot=str(snapshot.relative_to(ROOT)), rows=manifest['rows'],
                  routes=statuses, integrity=integrity, foreign_keys=fk,
                  write_denied=denied, snapshot_unchanged=manifest['sha256'] == sha(snapshot / 'aeris.db'),
                  production_sha_before=before, production_sha_after=sha(source),
                  production_unchanged=before == sha(source),
                  linux_test='not run: Docker unavailable; WSL not installed',
                  scope='Flask WSGI client on Windows; no network or ingestion')
    (ROOT / 'reports' / 'aeris_web_beta_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
