"""Read-only Git integration audit. No fetch, checkout, index write or database access."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_railway_release import release_files, inspect
from scripts.audit_web_release import PATTERNS


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def classify(name):
    if name.startswith('docs/'):
        return 'documentation'
    if name.startswith(('tests/', 'scripts/')):
        return 'local-validation-tools'
    if name in ('.gitignore', '.dockerignore', 'Dockerfile', 'railway.json'):
        return 'delivery-configuration'
    return 'runtime-or-asset'


def main():
    names = release_files()
    records, findings = inspect(ROOT, names)
    rows, contacts = [], []
    for item in records:
        name = item['path']
        content = (ROOT / name).read_bytes()
        old = subprocess.run(['git', 'show', 'main:' + name], cwd=ROOT, capture_output=True)
        rows.append(item | dict(category=classify(name), bytes=len(content),
                               tracked_in_main=old.returncode == 0,
                               byte_identical_to_main=old.returncode == 0 and old.stdout == content))
        if re.search(rb'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', content):
            contacts.append(dict(path=name, kind='email-like text; inspect public license attribution'))
        if b'MSI_COREi5' in content or b'C:\\Users\\' in content:
            contacts.append(dict(path=name, kind='local-user-or-machine-reference; review before publishing'))
    # Inspect all locally reachable history; no contact with origin.
    history_findings, scanned = [], 0
    for record in git('rev-list', '--objects', '--all').decode().splitlines():
        object_id = record.split(' ', 1)[0]
        if git('cat-file', '-t', object_id).strip() != b'blob':
            continue
        scanned += 1
        content = git('cat-file', 'blob', object_id)
        if content.startswith(b'SQLite format 3\0'):
            history_findings.append(dict(blob=object_id, kind='SQLite header'))
        for label, pattern in PATTERNS.items():
            if re.search(pattern, content):
                history_findings.append(dict(blob=object_id, kind=label))
    folder = Path(tempfile.mkdtemp(prefix='tmp_aeris_integration_review_', dir=ROOT / 'reports'))
    # Prospective web contents only, not a worktree and not a branch change.
    for name in names:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    env = {k: v for k, v in os.environ.items() if k in ('SYSTEMROOT', 'SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP')}
    env['AERIS_ENV'] = 'local'
    tests = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                           cwd=folder, env=env, capture_output=True, text=True)
    (ROOT / 'reports/aeris_railway_isolated_release_tests.log').write_text(tests.stdout + tests.stderr, encoding='utf-8')
    result = dict(branch=git('branch', '--show-current').decode().strip(),
                  main=git('rev-parse', 'main').decode().strip(),
                  aeris_v2=git('rev-parse', 'aeris-v2').decode().strip(),
                  proposed_base=git('rev-parse', '77eb7ce').decode().strip(),
                  cached_main_is_ancestor=subprocess.run(['git', 'merge-base', '--is-ancestor', 'main', '77eb7ce'], cwd=ROOT).returncode == 0,
                  main_to_base=git('diff', '--name-status', 'main', '77eb7ce').decode().splitlines(),
                  file_count=len(rows), total_bytes=sum(r['bytes'] for r in rows),
                  largest_files=sorted(rows, key=lambda r: r['bytes'], reverse=True)[:5],
                  large_files_over_5MiB=[r['path'] for r in rows if r['bytes'] > 5 * 1024 * 1024],
                  sensitive_pattern_findings=findings, contact_review=contacts,
                  history_blobs_scanned=scanned, history_pattern_findings=history_findings,
                  history_scope='local reachable refs only; heuristic, not universal secret certification',
                  staged_files=git('diff', '--cached', '--name-only').decode().splitlines(),
                  isolated_release=str(folder.relative_to(ROOT)), isolated_test_returncode=tests.returncode,
                  files=rows, remote_contacted=False, git_mutations=False)
    (ROOT / 'reports/aeris_railway_integration_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('files', 'largest_files')}, indent=2))
    if findings or history_findings or tests.returncode:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
