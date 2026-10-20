"""One authorized Scheduler launch; disable on failure, never retry ingestion."""
import io
import argparse
import json
import sqlite3
import time
import unittest
import uuid
from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from pathlib import Path

from data_ingestion import operations as ops
from data_ingestion.controlled_run import compare_original
from data_ingestion.production_preflight import sha, snapshot
from data_ingestion.quality_versioned import verify_current
from data_ingestion.rehearse_versioned_quality import dashboard_probe
from scripts.install_disabled_task import ps, registered
from data_ingestion.task_semantics import capture, compare_semantic, compare_snapshot


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def disable():
    ps("$ErrorActionPreference='Stop'; $s=New-Object -ComObject 'Schedule.Service'; $s.Connect(); "
       "$t=$s.GetFolder('\\').GetTask('AERIS-OpenAQ-Hourly'); $t.Enabled=$false")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true', help='Read-only verification; never activate or run')
    args = parser.parse_args(argv)
    if args.verify_only:
        from scripts.verify_scheduled_configuration import main as verify_only
        return verify_only()
    root = ops.ROOT; db = root/'data/aeris_air_quality.db'
    identifier = ops.utcnow().strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    destination = root/'reports'/('first_scheduler_run_'+identifier+'.json')
    audit = {'status':'preflight', 'task':'AERIS-OpenAQ-Hourly', 'started_at_utc':ops.iso(ops.utcnow()),
             'scheduler_run_calls':0, 'direct_python_sync_calls':0, 'predictions_enabled':False,
             'catchup_note':'Windows may recover missed runs outside HH:05; this supervision requires first trigger still in future.'}
    enabled = False
    backup = root/'data/backups'/('aeris_before_first_scheduler_'+identifier+'.db')
    try:
        evidence = json.loads((root/'reports/task_semantic_com_evidence.json').read_text(encoding='utf-8-sig'))
        current = registered()
        require(current['exists'] and not current['enabled'] and current['instances'] == 0 and current['state'] == 1,
                'Task is not disabled and inactive; stop before activation')
        require(current['last_task_result'] == 0x41303, 'Task has already run; authorization was for first run')
        before_com = capture(root/'reports/AERIS-OpenAQ-Hourly.xml')
        audit['preflight_effective_snapshot'] = before_com
        audit['preflight_semantic_comparison'] = compare_snapshot(before_com, expected_enabled=False, reference=evidence)
        audit['preflight_previous_audit_comparison'] = compare_semantic(
            evidence['registered_effective'], before_com['registered_effective'], expected_enabled=False)
        require(audit['preflight_semantic_comparison']['matches'] and
                audit['preflight_previous_audit_comparison']['matches'], 'Task effective configuration differs from semantic audit')
        start = datetime.fromisoformat(evidence['registered_effective']['triggers'][0]['start_boundary'])
        margin = (start-datetime.now()).total_seconds()
        audit['seconds_until_first_scheduled_trigger'] = margin
        require(margin >= 25*60, 'Concurrency risk: scheduled/catch-up trigger is too near or already due; request instructions')
        require(evidence['runtime']['missed_runs'] == 0, 'Missed runs could queue a second execution')
        require(not Path(str(db)+'.sync.stop').exists(), 'Persistent stop signal present; do not clear implicitly')
        audit['execution_policy_before'] = ps('Get-ExecutionPolicy')
        audit['protected_files_before'] = {'app.py':sha(root/'app.py'), **{
            str(p.relative_to(root)):sha(p) for p in (root/'models/releases/aeris-pm25-20261017-v1').rglob('*') if p.is_file()}}
        with ops.exclusive_lock(Path(str(db)+'.sync.lock')):
            baseline = snapshot(db)
            require(baseline['integrity_check'] == ['ok'] and baseline['foreign_key_violations'] == 0,
                    'Initial SQLite integrity failed')
            require(baseline['tables']['mediciones']['rows'] == 12467 and baseline['tables']['calidad_mediciones']['rows'] == 12467,
                    'Unexpected original row counts')
            ops.copy_database(db, backup)
            require(snapshot(backup) == baseline, 'Fresh backup differs from original')
            audit['before'] = baseline
            audit['verified_pre_enable_backup'] = {'path':str(backup), 'sha256':sha(backup)}
            old_dashboard, audit['dashboard_before'] = dashboard_probe(db)
        audit['preflight_verified'] = True
        # Single Scheduler Run, well before the first scheduled trigger. No Python ingestion call.
        # This same COM block rechecks runtime immediately before enabling and launch.
        enabled = True  # Any uncertain result from activation requires disabling in finally.
        launch = json.loads(ps("$ErrorActionPreference='Stop'; $s=New-Object -ComObject 'Schedule.Service'; $s.Connect(); "
            "$t=$s.GetFolder('\\').GetTask('AERIS-OpenAQ-Hourly'); "
            "if ($t.Enabled -or $t.State -ne 1 -or $t.GetInstances(0).Count -ne 0 -or $t.NumberOfMissedRuns -ne 0) { throw 'Concurrency guard failed' }; "
            "if ([datetime]$t.Definition.Triggers.Item(1).StartBoundary -lt (Get-Date).AddMinutes(25)) { throw 'Trigger too near' }; "
            "try { $t.Enabled=$true; $run=$t.Run($null); "
            "[ordered]@{instance_guid=$run.InstanceGuid;enabled=$t.Enabled;started_local=(Get-Date).ToString('o')} | ConvertTo-Json -Compress } "
            "catch { $t.Enabled=$false; throw }"))
        audit['scheduler_run_calls'] = 1
        audit['launch'] = launch
        print('Scheduler launched one supervised instance; no direct ingestion call.', flush=True)
        deadline = time.monotonic()+21*60
        while True:
            current = registered()
            if current['instances'] == 0 and current['state'] in (1, 3) and current['last_task_result'] != 0x41303:
                break
            require(time.monotonic() < deadline, 'Supervision deadline exceeded; disable without retry')
            require(datetime.now() < start-timedelta(minutes=3), 'Next scheduled trigger too near; disable without retry')
            time.sleep(3)
        audit['task_after_run'] = {k:v for k,v in current.items() if k != 'xml'}
        require(current['last_task_result'] == 0, 'Scheduler returned nonzero; disable and retain evidence')
        require(current['enabled'] and current['instances'] == 0, 'Unexpected task state after run')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as conn:
            before_ingestas = baseline['tables']['ingestas']['rows']
            require(conn.execute('SELECT COUNT(*) FROM ingestas').fetchone()[0] == before_ingestas+1,
                    'Unexpected number of ingestion runs; disable immediately')
            run_id, status, serialized = conn.execute('SELECT id,estado,reporte_json FROM ingestas ORDER BY inicio_utc DESC LIMIT 1').fetchone()
            require(status == 'success', 'Ingestion not fully successful; disable without retry')
            sync = json.loads(serialized)
            audit['synchronization'] = sync
            scheduler_reports = []
            for path in (root/'data/sync_runtime/scheduler').glob('*.json'):
                if path.name == 'last_success.json':
                    continue
                item = json.loads(path.read_text(encoding='utf8'))
                if item.get('synchronization', {}).get('run_id') == run_id:
                    scheduler_reports.append((path, item))
            require(len(scheduler_reports) == 1, 'Missing or duplicate controlled scheduler audit')
            audit['controlled_scheduler_audit'] = str(scheduler_reports[0][0])
            controlled = scheduler_reports[0][1]
            audit['controlled_scheduler_backup'] = controlled['backup']
            require(controlled['backup']['verified'] and sha(controlled['backup']['path']) == controlled['backup']['sha256'],
                    'Controlled backup hash invalid')
            require(snapshot(controlled['backup']['path']) == baseline, 'Immediate backup differs from pre-enable baseline')
            audit['original_rows'] = compare_original(conn, backup)
            with closing(sqlite3.connect(backup.as_uri()+'?mode=ro', uri=True)) as old:
                for table in ('evaluaciones_calidad','reglas_calidad_versionadas','evaluaciones_calidad_ingestas'):
                    originals = set(old.execute('SELECT * FROM '+table))
                    require(originals.issubset(set(conn.execute('SELECT * FROM '+table))), 'Historical ledger changed')
            audit['verified_current_quality'] = {str(sid):verify_current(conn, sid) for sid in ops.ACTIVE}
            audit['pending_quality'] = conn.execute('SELECT COUNT(*) FROM mediciones LEFT JOIN calidad_mediciones USING(fuente,sensor_id,fecha_utc,contaminante) WHERE calidad_mediciones.sensor_id IS NULL').fetchone()[0]
            require(audit['pending_quality'] == 0, 'Unassessed measurements')
            audit['duplicate_utc_groups'] = conn.execute('SELECT COUNT(*) FROM (SELECT 1 FROM mediciones GROUP BY fuente,sensor_id,julianday(fecha_utc),contaminante HAVING COUNT(*)>1)').fetchone()[0]
            require(audit['duplicate_utc_groups'] == 0, 'Duplicate UTC records')
            receipts = conn.execute('SELECT DISTINCT r.sha256,r.ruta_local,r.url FROM respuestas_api r JOIN observaciones_api o ON o.respuesta_sha256=r.sha256 WHERE o.ingesta_id=?', (run_id,)).fetchall()
            require(bool(receipts), 'No authenticated API receipts')
            for digest, path, url in receipts:
                require(sha(path) == digest and url.startswith(ops.API+'/'), 'Invalid response provenance')
            audit['verified_response_receipts'] = len(receipts)
            audit['latest_observations'] = []
            for sid in ops.ACTIVE:
                latest = conn.execute("SELECT MAX(fecha_utc) FROM mediciones WHERE fuente='OpenAQ' AND sensor_id=? AND contaminante='pm25'", (sid,)).fetchone()[0]
                age = (ops.utcnow()-ops.parse_utc(latest)).total_seconds()/3600 if latest else None
                audit['latest_observations'].append({'sensor_id':sid,'latest_utc':latest,'age_hours':age,'within_two_hours':age is not None and 0 <= age <= 2})
        audit['after'] = snapshot(db)
        require(audit['after']['integrity_check'] == ['ok'] and audit['after']['foreign_key_violations'] == 0, 'Final SQLite integrity failed')
        updated, audit['dashboard_after'] = dashboard_probe(db)
        require(all(updated.get(k) == v for k,v in old_dashboard.items()), 'Dashboard changed historical quality')
        require(all(v == 200 for v in audit['dashboard_after']['http_statuses'].values()), 'Dashboard endpoint regression')
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            tests = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.discover(str(root/'tests')))
        audit['tests'] = {'run':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors),'successful':tests.wasSuccessful()}
        require(tests.wasSuccessful(), 'Automated tests failed')
        audit['protected_files_after'] = {name:sha(root/name) for name in audit['protected_files_before']}
        require(audit['protected_files_before'] == audit['protected_files_after'], 'Protected file changed')
        audit['execution_policy_after'] = ps('Get-ExecutionPolicy')
        require(audit['execution_policy_after'] == audit['execution_policy_before'], 'ExecutionPolicy changed')
        require(datetime.now() < start-timedelta(minutes=3), 'Verification finished too near next trigger')
        final = registered()
        require(final['enabled'] and final['instances'] == 0 and final['last_run_time'] == current['last_run_time'], 'Unexpected second execution')
        # Persist both effective snapshots and the detailed diff BEFORE a possible failure.
        after_com = capture(root/'reports/AERIS-OpenAQ-Hourly.xml')
        audit['final_effective_snapshot'] = after_com
        audit['final_semantic_comparison'] = compare_snapshot(after_com, expected_enabled=True, reference=before_com)
        audit['before_after_semantic_comparison'] = compare_semantic(
            before_com['registered_effective'], after_com['registered_effective'], expected_enabled=True)
        require(audit['final_semantic_comparison']['matches'] and
                audit['before_after_semantic_comparison']['matches'], 'Effective task configuration differs; see persisted semantic diff')
        audit['final_task'] = {k:v for k,v in final.items() if k != 'xml'}
        audit['status'] = 'verified_success_task_enabled_hourly'
        print('Supervised Scheduler run verified; task remains enabled hourly.', flush=True)
        return 0
    except BaseException as exc:
        audit['status'] = 'stopped_no_retry'
        audit['error_type'] = type(exc).__name__
        if type(exc) is RuntimeError:
            audit['reason'] = str(exc)
        if enabled:
            try:
                disable()
                audit['disabled_after_failure'] = not registered()['enabled']
            except BaseException:
                audit['disable_failed_requires_immediate_manual_attention'] = True
        return 1
    finally:
        audit['finished_at_utc'] = ops.iso(ops.utcnow())
        destination.write_text(json.dumps(audit, indent=2, ensure_ascii=True), encoding='utf8')
        print(json.dumps({'status':audit['status'],'report':str(destination),'reason':audit.get('reason')}), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
