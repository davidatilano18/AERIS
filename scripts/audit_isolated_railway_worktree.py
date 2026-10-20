"""Review exact unstaged release and complete prospective diff, without git add."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_web_release import PATTERNS


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args])


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = ROOT / 'reports/tmp_aeris_railway_integration'
    manifest = json.loads((ROOT / 'reports/aeris_railway_release_manifest.json').read_text())
    selected = {row['path']: row['sha256'] for row in manifest['files']}
    assert len(selected) == 60
    before = json.loads((ROOT / 'reports/aeris_railway_worktree_preservation_before.json').read_text())
    assert all(digest(ROOT / name) == value for name, value in before['files'].items())
    assert digest(ROOT / '.git/index') == before['index_sha256']
    assert git(ROOT, 'branch', '--show-current').decode().strip() == before['branch']
    assert git(ROOT, 'rev-parse', 'HEAD').decode().strip() == before['head']
    assert not git(target, 'diff', '--cached', '--name-only').strip()
    assert git(target, 'rev-parse', 'HEAD').decode().strip() == '77eb7cea8f147cf5a44707efceb9d85961cebd9e'
    assert all(digest(target / name) == value for name, value in selected.items())
    untracked = set(git(target, 'ls-files', '--others', '--exclude-standard', '-z').decode().strip('\0').split('\0'))
    assert untracked <= set(selected), sorted(untracked - set(selected))
    baseline = {}
    for row in git(ROOT, 'ls-tree', '-r', 'origin/main').decode().splitlines():
        metadata, name = row.split('\t', 1)
        mode, kind, object_id = metadata.split()
        baseline[name] = dict(mode=mode, kind=kind, object=object_id)
    current = set(git(target, 'ls-files', '-z').decode().strip('\0').split('\0')) | untracked
    changes, sensitive, modes, patch, normalized_unchanged = [], [], [], [], []
    temp = Path(tempfile.mkdtemp(prefix='tmp_aeris_worktree_diff_', dir=ROOT / 'reports'))
    for index, name in enumerate(sorted(set(baseline) | current)):
        path = target / name
        new = path.read_bytes() if name in current and path.is_file() else None
        old = git(ROOT, 'cat-file', 'blob', baseline[name]['object']) if name in baseline else None
        if new is not None:
            assert not path.is_symlink(), name
            if new.startswith(b'SQLite format 3\0') or path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
                sensitive.append(dict(path=name, kind='SQLite'))
            for label, pattern in PATTERNS.items():
                if re.search(pattern, new):
                    sensitive.append(dict(path=name, kind=label))
            modes.append(dict(path=name, type='regular', expected_git_mode='100644',
                              previous_git_mode=baseline.get(name, {}).get('mode')))
        if old == new:
            continue
        if old is not None and new is not None:
            # Windows checkout may materialize CRLF while Git stores LF. Compare
            # through Git's clean filters, without -w or changing either index.
            normalized = subprocess.check_output(
                ['git', '-C', str(target), 'hash-object', '--path=' + name, '--stdin'],
                input=new, stderr=subprocess.DEVNULL).decode().strip()
            if normalized == baseline[name]['object']:
                normalized_unchanged.append(name)
                continue
        status = 'A' if old is None else 'D' if new is None else 'M'
        if status in ('A', 'M'):
            assert name in selected, name
        else:
            assert name == 'STATIC', name
        binary = b'\0' in (old or b'') or b'\0' in (new or b'')
        changes.append(dict(path=name, status=status, binary=binary,
                            before_bytes=len(old or b''), after_bytes=len(new or b'')))
        left, right = temp / f'{index}-before', temp / f'{index}-after'
        left.write_bytes(old or b'')
        right.write_bytes(new or b'')
        diff = subprocess.run(['git', 'diff', '--no-index', '--binary', '--no-ext-diff', '--', str(left), str(right)],
                              capture_output=True)
        assert diff.returncode in (0, 1), diff.stderr.decode(errors='replace')
        text = diff.stdout.decode('utf-8', errors='replace')
        text = text.replace(str(left).replace('\\', '/'), name).replace(str(right).replace('\\', '/'), name)
        patch.append(f'\n### {status}: {name} (binary={binary})\n' + text)
    (ROOT / 'reports/aeris_railway_worktree_full_diff.txt').write_text(''.join(patch), encoding='utf-8')
    result = dict(branch=git(target, 'branch', '--show-current').decode().strip(),
                  head=git(target, 'rev-parse', 'HEAD').decode().strip(),
                  origin_main=git(ROOT, 'rev-parse', 'origin/main').decode().strip(),
                  selected_files=len(selected), verified_hashes=len(selected),
                  differences=changes, counts={s: sum(c['status'] == s for c in changes) for s in ('A', 'M', 'D')},
                  prospective_tree_files=len(current), file_modes=modes,
                  sensitive_findings=sensitive, original_files_preserved=len(before['files']),
                  original_branch_head_and_index_unchanged=True, staged_files=[],
                  unselected_untracked=[], tests=json.loads((ROOT / 'reports/aeris_railway_worktree_test_result.json').read_text()),
                  unchanged_after_git_clean_filters=normalized_unchanged,
                  scope='Full prospective worktree versus freshly fetched origin/main, including untracked files; no staging')
    (ROOT / 'reports/aeris_railway_worktree_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('differences', 'file_modes', 'tests')}, indent=2))
    if sensitive or result['tests']['returncode']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
