"""Opt-in Linux acceptance test. Requires Docker and an already prepared derivative.

Builds/runs a private loopback-only container. Never prepares or mounts production.
"""
import argparse
import hashlib
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(['docker', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def wait_ready():
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18000/health/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('Container did not become ready')


def main(directory):
    directory = directory.resolve()
    db = directory / 'aeris.db'
    original = ROOT / 'data' / 'aeris_air_quality.db'
    if not db.is_file() or db.samefile(original):
        raise ValueError('Only a separate prepared snapshot is accepted')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    if manifest.get('format') != 'aeris-web-snapshot-v1' or manifest.get('sha256') != digest:
        raise ValueError('Invalid derivative manifest')
    name = 'aeris-beta-test-' + uuid.uuid4().hex[:12]
    run('build', '-t', 'aeris-web:3.1', '.')
    try:
        run('run', '-d', '--name', name, '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--memory=512m', '--cpus=1', '--pids-limit=64',
            '--tmpfs', '/tmp:rw,size=64m,mode=1777', '-p', '127.0.0.1:18000:8000',
            '--mount', 'type=bind,src=' + str(directory) + ',dst=/dataset,readonly',
            '-e', 'AERIS_DB_PATH=/dataset/aeris.db', '-e', 'AERIS_DATASET_MANIFEST=/dataset/manifest.json',
            '-e', 'AERIS_TRUSTED_HOSTS=localhost,127.0.0.1', 'aeris-web:3.1')
        wait_ready()
        for route in ('/', '/v2', '/v2/datos', '/api/overview', '/api/export.csv',
                      '/api/v2/public', '/api/v2/comparison?station=1352676'):
            with urllib.request.urlopen('http://127.0.0.1:18000' + route, timeout=30) as response:
                assert response.status == 200
        # Direct rw connection bypasses application URI: the mount must still deny writes.
        code = "import sqlite3; c=sqlite3.connect('/dataset/aeris.db'); c.execute('DELETE FROM mediciones')"
        write = subprocess.run(['docker', 'exec', name, 'python', '-c', code], capture_output=True, text=True)
        if write.returncode == 0 or 'readonly' not in write.stderr.lower():
            raise RuntimeError('Read-only mount contract failed')
        run('restart', name)
        wait_ready()
        assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
        print(json.dumps(dict(gunicorn_linux=True, routes=True, restart=True,
                              persistence=True, read_only_mount=True)))
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path, required=True)
    main(parser.parse_args().dataset_dir)
