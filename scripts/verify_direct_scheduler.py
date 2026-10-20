"""Exercise native Python entry twice on a disposable SQLite, replaying real receipts."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from data_ingestion import operations as ops
from data_ingestion.production_preflight import sha, snapshot, credential_scan
from data_ingestion.windows_credentials import load_key


def main():
    root = ops.ROOT
    db = root/'data/aeris_air_quality.db'
    keyfile = root/'.secrets/openaq_api_key.clixml'
    audit = root/'reports/controlled_sync_audit_20261018T005210Z.json'
    protected_files = [db, root/'app.py', root/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json']
    before = {str(p.relative_to(root)): sha(p) for p in protected_files}
    report = {'mode':'native_python_entry_recorded_real_responses_temporary_copy',
              'network_requests':0, 'tasks_registered':0, 'originals_before':before,
              'credential_scan':credential_scan(root, load_key(keyfile)), 'runs':[]}
    assert not report['credential_scan']['exact_credential_matches']
    with tempfile.TemporaryDirectory(prefix='aeris-direct-python-') as folder:
        target = Path(folder)/'simulation.db'
        ops.copy_database(db, target)
        baseline = snapshot(target)
        environment = {k:v for k,v in os.environ.items() if k != 'OPENAQ_API_KEY' and not k.startswith('VSCODE')}
        command = [sys.executable, '-B', '-m', 'data_ingestion.scheduled_sync', '--db', str(target),
                   '--key-file', str(keyfile), '--replay-audit', str(audit)]
        for _ in range(2):
            completed = subprocess.run(command, cwd=root, env=environment, capture_output=True, timeout=180)
            assert completed.returncode == 0, 'Native entry failed; inspect temporary audit'
            latest = json.loads((target.parent/'sync_runtime/scheduler/last_success.json').read_text())
            report['runs'].append(latest)
        after = snapshot(target)
        tables = ('mediciones','calidad_mediciones','evaluaciones_calidad','reglas_calidad_versionadas')
        report['protected_tables_unchanged'] = all(baseline['tables'][t] == after['tables'][t] for t in tables)
        report['integrity_check'] = after['integrity_check']
        report['foreign_key_violations'] = after['foreign_key_violations']
        assert report['protected_tables_unchanged']
        for run in report['runs']:
            assert run['backup']['verified']
            assert all(r['new_measurements'] == 0 and r['conflicting_candidates'] == 0
                       and r['versioned_quality']['new_versioned_assessments'] == 0
                       for r in run['synchronization']['results'])
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        suite = unittest.defaultTestLoader.discover(str(root/'tests'))
        tests = unittest.TextTestRunner(stream=stream).run(suite)
    report['tests'] = {'run':tests.testsRun, 'failures':len(tests.failures), 'errors':len(tests.errors),
                       'successful':tests.wasSuccessful()}
    report['originals_after'] = {str(p.relative_to(root)): sha(p) for p in protected_files}
    report['protected_files_unchanged'] = report['originals_after'] == before
    report['finished_at_utc'] = ops.iso(ops.utcnow())
    assert report['protected_files_unchanged'] and tests.wasSuccessful()
    destination = root/'reports/direct_scheduler_readiness.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf8')
    print(json.dumps({'report':str(destination), 'tests':report['tests'],
                      'protected_files_unchanged':report['protected_files_unchanged'],
                      'statuses':[r['status'] for r in report['runs']]}))


if __name__ == '__main__': main()
