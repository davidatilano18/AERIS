"""Validate and optionally register only the approved, disabled AERIS task."""
import argparse
import csv
import io
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from data_ingestion.operations import ROOT
from data_ingestion.production_preflight import sha, snapshot
from data_ingestion.windows_credentials import load_key
from data_ingestion.task_semantics import capture, compare_snapshot

NAME = 'AERIS-OpenAQ-Hourly'
NS = {'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def ps(command):
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                            capture_output=True, text=True, check=False)
    require(result.returncode == 0, 'Read-only Windows configuration query failed')
    return result.stdout.strip()


def registered():
    return json.loads(ps("$ErrorActionPreference='Stop'; $service=New-Object -ComObject 'Schedule.Service'; "
        "$service.Connect(); try { $task=$service.GetFolder('\\').GetTask('AERIS-OpenAQ-Hourly') } "
        "catch { if ($_.Exception.HResult -in @(-2147024894,-2147024893)) { "
        "[pscustomobject]@{exists=$false} | ConvertTo-Json -Compress; exit 0 }; throw }; "
        "$identity=$task.Definition.Principal.UserId; "
        "if ($identity -like 'S-1-*') { $sid=$identity } else { "
        "$sid=([Security.Principal.NTAccount]$identity).Translate([Security.Principal.SecurityIdentifier]).Value }; "
        "[ordered]@{exists=$true;xml=$task.Xml;enabled=$task.Enabled;state=[int]$task.State;"
        "last_run_time=$task.LastRunTime.ToString('o');last_task_result=[int]$task.LastTaskResult;"
        "instances=$task.GetInstances(0).Count;principal_sid=$sid} | ConvertTo-Json -Compress"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-disabled', action='store_true')
    args = parser.parse_args()
    xml_path = ROOT/'reports/AERIS-OpenAQ-Hourly.xml'
    report_path = ROOT/'reports/disabled_task_installation.json'
    db = ROOT/'data/aeris_air_quality.db'
    holdout = ROOT/'models/releases/aeris-pm25-20261017-v1/holdout_plan.json'
    report = {'started_at_utc':datetime.now(timezone.utc).isoformat(), 'status':'preflight',
              'task':NAME, 'registration_attempted':False, 'task_started_by_this_process':False,
              'commands':{'disable':'schtasks.exe /Change /TN AERIS-OpenAQ-Hourly /DISABLE',
                          'enable_requires_new_authorization':'schtasks.exe /Change /TN AERIS-OpenAQ-Hourly /ENABLE',
                          'delete':'schtasks.exe /Delete /TN AERIS-OpenAQ-Hourly'}}
    try:
        identity = subprocess.run(['whoami','/user','/fo','csv','/nh'], check=True, capture_output=True, text=True)
        account, sid = next(csv.reader(io.StringIO(identity.stdout.strip())))
        report['windows_account'] = account
        report['windows_sid'] = sid
        report['execution_policy_before'] = ps('Get-ExecutionPolicy')
        tree = ET.fromstring(xml_path.read_bytes())
        def value(path):
            node = tree.find(path, NS)
            require(node is not None, 'Missing required task element: '+path)
            return node.text or ''
        expected_arguments = '-B -m data_ingestion.scheduled_sync --db "'+str(db)+'" --key-file "'+str(ROOT/'.secrets/openaq_api_key.clixml')+'"'
        checks = {
            't:Actions/t:Exec/t:Command':str(ROOT/'.venv/Scripts/python.exe'),
            't:Actions/t:Exec/t:Arguments':expected_arguments,
            't:Actions/t:Exec/t:WorkingDirectory':str(ROOT),
            't:Settings/t:Enabled':'false',
            't:Principals/t:Principal/t:UserId':sid,
            't:Principals/t:Principal/t:LogonType':'InteractiveToken',
            't:Principals/t:Principal/t:RunLevel':'LeastPrivilege',
            't:Triggers/t:TimeTrigger/t:Repetition/t:Interval':'PT1H',
            't:Triggers/t:TimeTrigger/t:Enabled':'true',
            't:Settings/t:MultipleInstancesPolicy':'IgnoreNew',
            't:Settings/t:ExecutionTimeLimit':'PT20M'}
        for path, expected in checks.items():
            require(value(path) == expected, 'Unexpected task configuration: '+path)
        require(len(tree.findall('t:Actions/*',NS)) == 1 and len(tree.findall('t:Triggers/*',NS)) == 1
                and len(tree.findall('t:Principals/*',NS)) == 1, 'Unexpected additional actions/triggers/principals')
        start = datetime.fromisoformat(value('t:Triggers/t:TimeTrigger/t:StartBoundary'))
        require(start.minute == 5 and start.second == 0, 'Trigger not aligned to HH:05')
        require((ROOT/'.venv/Scripts/python.exe').is_file(), 'Missing project Python')
        key = load_key(ROOT/'.secrets/openaq_api_key.clixml')
        raw = xml_path.read_bytes()
        require(key.encode('utf8') not in raw and key.encode('utf-16-le') not in raw, 'Credential in task XML')
        require(not any('password' in element.tag.lower() for element in tree.iter()), 'Password element in XML')
        del key
        report['credential_check'] = 'DPAPI decryptable by approved identity; no API key/password in task XML'
        report['planned_xml_sha256'] = sha(xml_path)
        report['planned_start_boundary_local'] = start.isoformat()
        report['before'] = snapshot(db)
        require(report['before']['integrity_check'] == ['ok'] and report['before']['foreign_key_violations'] == 0,
                'Initial SQLite integrity check failed')
        require(report['before']['tables']['mediciones']['rows'] == 12467, 'Unexpected measurement count')
        report['original_sha256_before'] = sha(db)
        report['protected_files_before'] = {'app.py':sha(ROOT/'app.py'), 'holdout':sha(holdout)}
        previous = registered()
        require(not previous['exists'], 'Task already exists; no overwrite authorized')
        report['preflight_verified'] = True
        if not args.install_disabled:
            report['status'] = 'ready_not_installed'
            return 0
        require(sha(xml_path) == report['planned_xml_sha256'], 'XML changed after validation')
        report['registration_attempted'] = True
        command = ['schtasks.exe','/Create','/TN',NAME,'/XML',str(xml_path)]
        report['installation_command'] = command
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        report['registration_exit_code'] = result.returncode
        require(result.returncode == 0, 'Windows refused task registration; no further action attempted')
        actual = registered()
        report['registered'] = {k:v for k,v in actual.items() if k != 'xml'}
        require(actual['exists'], 'Registered task not found')
        require(not actual['enabled'] and actual['state'] == 1 and actual['instances'] == 0,
                'Registered task is not disabled/inactive')
        require(actual['principal_sid'] == sid, 'Registered identity differs')
        require(actual['last_task_result'] == 0x41303 and datetime.fromisoformat(actual['last_run_time']).year < 2000,
                'Task may have executed; stop and inspect Windows history')
        report['effective_snapshot'] = capture(xml_path)
        report['semantic_comparison'] = compare_snapshot(report['effective_snapshot'], expected_enabled=False)
        require(report['semantic_comparison']['matches'], 'Registered effective settings differ; see semantic diff')
        exported = ROOT/'reports/AERIS-OpenAQ-Hourly.registered.xml'
        exported.write_bytes(actual['xml'].encode('utf-16'))
        report['registered_xml_path'] = str(exported)
        report['configuration_matches_planned_semantics'] = True
        report['after'] = snapshot(db)
        report['original_sha256_after'] = sha(db)
        report['protected_files_after'] = {'app.py':sha(ROOT/'app.py'), 'holdout':sha(holdout)}
        report['execution_policy_after'] = ps('Get-ExecutionPolicy')
        require(report['before'] == report['after'] and report['original_sha256_before'] == report['original_sha256_after'],
                'Original database changed')
        require(report['protected_files_before'] == report['protected_files_after'], 'Protected file changed')
        require(report['execution_policy_before'] == report['execution_policy_after'], 'ExecutionPolicy changed')
        report['status'] = 'installed_disabled_verified_never_run'
        return 0
    except Exception as exc:
        report['status'] = 'stopped_on_failed_check'
        report['error_type'] = type(exc).__name__
        # Only our fixed validation messages are retained; no external error payloads.
        if type(exc) is RuntimeError:
            report['reason'] = str(exc)
        return 1
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf8')
        print(json.dumps({'status':report['status'], 'report':str(report_path), 'reason':report.get('reason')}))


if __name__ == '__main__':
    raise SystemExit(main())
