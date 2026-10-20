"""Railway-only entry: verify an uploaded snapshot, restrict permissions, drop root.

No downloads, database writes, migrations or background jobs. Local Docker CMD is
unchanged. Requires a previously uploaded file under /dataset/<release>/aeris.db.
"""
import ctypes
import hashlib
import os
import re
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path

UID = GID = 10001


def snapshot_path(value, mount=Path('/dataset')):
    path = Path(value)
    # The root entry may change permissions only on these explicit upload paths.
    if not path.is_absolute() or path.name != 'aeris.db' or path.parent.parent != mount:
        raise ValueError('Expected /dataset/<release>/aeris.db')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', path.parent.name):
        raise ValueError('Invalid release name')
    for item in (mount, path.parent, path):
        if item.is_symlink():
            raise ValueError('Snapshot symlinks are forbidden')
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Snapshot must be an existing regular unlinked copy')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Not a regular snapshot')
    return path


def verify(path, expected):
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('A SHA-256 snapshot identity is required')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        raise ValueError('Snapshot hash mismatch')
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(path) + suffix).exists():
            raise ValueError('Snapshot must be closed and self-contained')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Invalid SQLite snapshot')
        if con.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Invalid foreign keys')
        sources = {r[0] for r in con.execute('SELECT DISTINCT fuente FROM mediciones')}
        if not sources or not sources <= {'OpenAQ', 'OpenAQ-Archive'}:
            raise ValueError('Unexpected observation source')
    # The central policy also validates any controlled batch ledger.
    from data_ingestion.visibility import connect_readonly
    with closing(connect_readonly(path)) as con:
        con.execute('SELECT COUNT(*) FROM mediciones').fetchone()
    return actual


def restrict_and_drop(path, mount=Path('/dataset')):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RuntimeError('Railway volume preparation requires Linux root entry')
    # Root owns both file and parent. 0444 alone is insufficient if web owns the
    # file (could chmod it) or parent (could unlink/replace it).
    for item, mode in ((mount, 0o755), (path.parent, 0o555), (path, 0o444)):
        os.chown(item, 0, 0)
        os.chmod(item, mode)
    os.setgroups([])
    os.setgid(GID)
    os.setuid(UID)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError('Cannot set no_new_privs')
    if os.geteuid() != UID or os.access(path, os.W_OK) or os.access(path.parent, os.W_OK) or os.access(mount, os.W_OK):
        raise RuntimeError('Snapshot permissions do not isolate the web user')


def main():
    if os.environ.get('AERIS_ENV') != 'beta' or os.environ.get('OPENAQ_API_KEY'):
        raise ValueError('Railway requires beta without ingestion credentials')
    path = snapshot_path(os.environ.get('AERIS_DB_PATH', ''))
    expected = os.environ.get('AERIS_SNAPSHOT_SHA256', '')
    verify(path, expected)
    restrict_and_drop(path)
    # Read again as the final identity, prior to importing the web application.
    verify(path, expected)
    os.environ['AERIS_DEPLOYMENT_PROFILE'] = 'railway'
    print('railway_snapshot_verified web_uid=10001 access=read-only', flush=True)
    os.execvp('gunicorn', ['gunicorn', '--config', 'gunicorn.conf.py', 'wsgi:application'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('railway_start_failed type=' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
