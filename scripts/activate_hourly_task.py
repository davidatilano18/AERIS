"""Enable only the existing approved task; never Run or register a task."""
import argparse
import json
from datetime import datetime

from data_ingestion import operations as ops
from data_ingestion.production_preflight import sha, snapshot
from data_ingestion.task_semantics import capture, compare_snapshot, compare_semantic
from scripts.install_disabled_task import ps


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-existing',action='store_true')
    args=parser.parse_args()
    root=ops.ROOT; xml=root/'reports/AERIS-OpenAQ-Hourly.xml'; db=root/'data/aeris_air_quality.db'
    path=root/'reports/hourly_task_activation.json'
    report={'status':'preflight','started_at_utc':ops.iso(ops.utcnow()),'scheduler_run_calls':0,
            'manual_sync_calls':0,'task_registration_calls':0,'enable_requested':False,
            'commands':{'disable':'schtasks.exe /Change /TN "AERIS-OpenAQ-Hourly" /DISABLE',
                        'last_execution':'schtasks.exe /Query /TN "AERIS-OpenAQ-Hourly" /V /FO LIST'}}
    enable_attempted=False
    try:
        approved=json.loads((root/'reports/supervisor_semantic_fix.json').read_text())
        reference=approved['effective_snapshot']
        installation=json.loads((root/'reports/disabled_task_installation.json').read_text())
        require(approved['status']=='APTO' and approved['tests']['successful'], 'Semantic audit not approved')
        for name,digest in approved['source_sha256'].items():
            require(sha(root/name)==digest, 'Tested verifier code changed: '+name)
        require(sha(xml)==installation['planned_xml_sha256'], 'Approved XML changed')
        before=capture(xml); report['before']=before
        report['before_comparison']=compare_snapshot(before,expected_enabled=False,reference=reference)
        report['approved_comparison']=compare_semantic(reference['registered_effective'],before['registered_effective'],expected_enabled=False)
        require(report['before_comparison']['matches'] and report['approved_comparison']['matches'], 'Pre-activation functional mismatch')
        require(before['runtime']['last_run_time']==reference['runtime']['last_run_time'] and before['runtime']['last_task_result']==0,
                'Unexpected run since approved verification')
        trigger=before['registered_effective']['triggers'][0]
        require(trigger['repetition_interval']=='PT1H' and datetime.fromisoformat(trigger['start_boundary']).minute==5,
                'Not the approved hourly HH:05 trigger')
        next_time=datetime.fromisoformat(before['runtime']['next_run_time'])
        require((next_time-datetime.now()).total_seconds()>60, 'Next scheduled run too close for immediate unchanged-database verification')
        report['database_before']=snapshot(db)
        report['database_sha256_before']=sha(db)
        require(report['database_before']['tables']['mediciones']['rows']==12479, 'Expected 12479 measurements')
        require(report['database_before']==approved['database'] and report['database_sha256_before']==approved['database_sha256_after'],
                'SQLite changed since verification')
        require(report['database_before']['integrity_check']==['ok'] and not report['database_before']['foreign_key_violations'], 'SQLite integrity failed')
        previous=json.loads((root/'reports/first_scheduler_run_20261018T032923Z_9bcea90a.json').read_text())
        report['protected_hashes_before']={name:sha(root/name) for name in previous['protected_files_after']}
        require(report['protected_hashes_before']==previous['protected_files_after'], 'Protected file changed')
        if not args.enable_existing:
            report['status']='verified_disabled_no_activation'; return 0
        enable_attempted=True; report['enable_requested']=True
        # The only task mutation in the successful path. No Run/Start/Register call.
        ps("$ErrorActionPreference='Stop'; $s=New-Object -ComObject 'Schedule.Service'; $s.Connect(); "
           "$t=$s.GetFolder('\\').GetTask('AERIS-OpenAQ-Hourly'); "
           "if ($t.Enabled -or $t.State -ne 1 -or $t.GetInstances(0).Count -ne 0) { throw 'Task state changed' }; "
           "$t.Enabled=$true")
        after=capture(xml); report['after']=after
        report['after_comparison']=compare_snapshot(after,expected_enabled=True,reference=before)
        report['before_after_comparison']=compare_semantic(before['registered_effective'],after['registered_effective'],expected_enabled=True)
        require(report['after_comparison']['matches'] and report['before_after_comparison']['matches'], 'Post-activation functional mismatch')
        require(after['runtime']['last_run_time']==before['runtime']['last_run_time'] and after['runtime']['last_task_result']==before['runtime']['last_task_result'],
                'Unexpected immediate execution during activation')
        report['database_after']=snapshot(db); report['database_sha256_after']=sha(db)
        require(report['database_after']==report['database_before'] and report['database_sha256_after']==report['database_sha256_before'], 'SQLite changed immediately after activation')
        require(sha(xml)==installation['planned_xml_sha256'], 'Original XML changed')
        report['protected_hashes_after']={name:sha(root/name) for name in report['protected_hashes_before']}
        require(report['protected_hashes_after']==report['protected_hashes_before'], 'Protected file changed')
        try:
            report['available_event_history']=json.loads(ps(
                "$ErrorActionPreference='Stop'; try { $l=Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'; "
                "if ($l.IsEnabled) { $events=@(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational';StartTime=(Get-Date).AddHours(-24)} "
                "-MaxEvents 200 -ErrorAction SilentlyContinue | Where-Object { $_.ToXml().Contains('AERIS-OpenAQ-Hourly') } | Select-Object -First 10 TimeCreated,Id,LevelDisplayName); "
                "[ordered]@{available=$true;log_enabled=$true;events=$events;scope='last 24 hours, up to 200 recent log events filtered to AERIS'} | ConvertTo-Json -Depth 5 -Compress "
                "} else { [ordered]@{available=$false;log_enabled=$false;reason='Operational event log is disabled; it was not enabled'} | ConvertTo-Json -Compress } "
                "} catch { [ordered]@{available=$false;reason='Event history not accessible; COM last execution retained'} | ConvertTo-Json -Compress }"))
        except Exception:
            report['available_event_history']={'available':False,'reason':'Read-only event query failed; COM execution history retained'}
        report['status']='enabled_hourly_verified_no_execution_requested'
        report['next_run_local']=after['runtime']['next_run_time']
        report['catchup_notice']='StartWhenAvailable=true: Windows may recover missed executions outside HH:05. No immediate run was requested.'
        return 0
    except Exception as exc:
        report['status']='stopped_on_failed_check';report['error_type']=type(exc).__name__
        if type(exc) is RuntimeError: report['reason']=str(exc)
        if enable_attempted or report.get('before',{}).get('runtime',{}).get('enabled'):
            try:
                ps("$ErrorActionPreference='Stop'; $s=New-Object -ComObject 'Schedule.Service'; $s.Connect(); $s.GetFolder('\\').GetTask('AERIS-OpenAQ-Hourly').Enabled=$false")
                report['disabled_after_failure']=not capture(xml)['runtime']['enabled']
            except Exception:
                report['disable_failed_requires_attention']=True
        return 1
    finally:
        report['finished_at_utc']=ops.iso(ops.utcnow())
        path.write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf8')
        print(json.dumps({'status':report['status'],'report':str(path),'next_run_local':report.get('next_run_local'),'reason':report.get('reason')}))


if __name__=='__main__':raise SystemExit(main())
