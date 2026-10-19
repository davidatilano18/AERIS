"""Run explicitly via Railway SSH BEFORE creating any public domain.

Read checks and a rolled-back SQL write probe on the derivative only. No sync.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

from railway_start import snapshot_path, verify, UID, GID


def main():
    if sys.platform != 'linux':
        raise RuntimeError('Actual Linux acceptance is required')
    path = snapshot_path(os.environ['AERIS_DB_PATH'])
    digest = verify(path, os.environ['AERIS_SNAPSHOT_SHA256'])
    port = int(os.environ.get('PORT', '8000'))
    routes = ('/', '/v2', '/v2/datos', '/api/overview', '/api/measurements',
              '/api/comparison', '/api/export.csv', '/api/v2/observations',
              '/api/v2/observations?source=OpenAQ-Archive&period=all',
              '/api/v2/stations', '/api/v2/public', '/api/v2/comparison?station=1352676',
              '/health/live', '/health/ready', '/static/v2/js/public.js',
              '/static/v2/css/public.css', '/logo.png')
    statuses = {}
    for route in routes:
        with urllib.request.urlopen(f'http://localhost:{port}' + route, timeout=60) as response:
            statuses[route] = response.status
            response.read()
    # Test with web identity even if an administrative SSH shell is root.
    def web_identity():
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(GID)
            os.setuid(UID)
    probe = '''import os,sqlite3,sys
p=sys.argv[1]
assert os.geteuid()==10001
assert not os.access(p,os.W_OK) and not os.access(os.path.dirname(p),os.W_OK)
c=sqlite3.connect(p)
try:
 c.execute('UPDATE mediciones SET valor=valor WHERE 0')
except sqlite3.OperationalError as exc:
 assert 'readonly' in str(exc).lower()
else:
 c.rollback()
 raise RuntimeError('Filesystem allowed a SQL write')
finally:
 c.close()
'''
    subprocess.run([sys.executable, '-B', '-c', probe, str(path)],
                   preexec_fn=web_identity, check=True, timeout=20)
    workers = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            cmd = (process / 'cmdline').read_bytes()
            if b'gunicorn' not in cmd:
                continue
            status = (process / 'status').read_text()
            uids = next(x for x in status.splitlines() if x.startswith('Uid:')).split()[1:]
            if any(int(x) != UID for x in uids):
                raise RuntimeError('Gunicorn retained privileged identity')
            workers.append(process.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    if not workers:
        raise RuntimeError('No Gunicorn processes verified')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Derivative changed during checks')
    print(json.dumps(dict(linux=True, gunicorn_nonroot=True, process_count=len(workers),
                          statuses=statuses, filesystem_write_denied=True,
                          snapshot_sha256=digest, snapshot_unchanged=True), indent=2))


if __name__ == '__main__':
    main()
