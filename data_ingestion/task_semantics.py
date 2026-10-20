"""Read-only COM snapshots and one strict comparison of effective task properties."""
import copy
import json
import subprocess
from pathlib import Path


READ_COM = r"""
$ErrorActionPreference='Stop'
$service=New-Object -ComObject 'Schedule.Service'
$service.Connect()
$task=$service.GetFolder('\').GetTask('AERIS-OpenAQ-Hourly')
$planned=$service.NewTask(0)
$planned.XmlText=[IO.File]::ReadAllText($originalPath)
function Read-Definition($definition) {
 $p=$definition.Principal; $identity=$p.UserId
 if ($identity -like 'S-1-*') { $sid=$identity } else {
  $sid=([Security.Principal.NTAccount]$identity).Translate([Security.Principal.SecurityIdentifier]).Value
 }
 $settings=[ordered]@{}
 foreach ($name in @('Enabled','AllowDemandStart','AllowHardTerminate','StartWhenAvailable','RunOnlyIfNetworkAvailable','RunOnlyIfIdle','DisallowStartIfOnBatteries','StopIfGoingOnBatteries','WakeToRun','Hidden','MultipleInstances','ExecutionTimeLimit','RestartInterval','RestartCount','DeleteExpiredTaskAfter','Priority','Compatibility')) {
  $settings[$name]=$definition.Settings.$name
 }
 $idle=[ordered]@{}
 foreach ($name in @('IdleDuration','WaitTimeout','StopOnIdleEnd','RestartOnIdle')) {
  $idle[$name]=$definition.Settings.IdleSettings.$name
 }
 $actions=@()
 foreach ($a in $definition.Actions) {
  if ([int]$a.Type -ne 0) { throw 'Unexpected non-executable action' }
  $actions += [ordered]@{type=[int]$a.Type;id=$a.Id;path=$a.Path;arguments=$a.Arguments;working_directory=$a.WorkingDirectory}
 }
 $triggers=@()
 foreach ($t in $definition.Triggers) {
  if ([int]$t.Type -ne 1) { throw 'Unexpected non-time trigger' }
  $triggers += [ordered]@{type=[int]$t.Type;id=$t.Id;enabled=$t.Enabled;start_boundary=$t.StartBoundary;end_boundary=$t.EndBoundary;execution_time_limit=$t.ExecutionTimeLimit;random_delay=$t.RandomDelay;repetition_interval=$t.Repetition.Interval;repetition_duration=$t.Repetition.Duration;stop_at_duration_end=$t.Repetition.StopAtDurationEnd}
 }
 return [ordered]@{principal=[ordered]@{sid=$sid;group_id=$p.GroupId;logon_type=[int]$p.LogonType;run_level=[int]$p.RunLevel;id=$p.Id};actions_context=$definition.Actions.Context;actions=$actions;triggers=$triggers;settings=$settings;idle_settings=$idle;network_settings=[ordered]@{id=$definition.Settings.NetworkSettings.Id;name=$definition.Settings.NetworkSettings.Name}}
}
[ordered]@{
 captured_at_utc=[DateTime]::UtcNow.ToString('o')
 planned_effective=(Read-Definition $planned)
 registered_effective=(Read-Definition $task.Definition)
 runtime=[ordered]@{enabled=$task.Enabled;state=[int]$task.State;instances=$task.GetInstances(0).Count;last_run_time=$task.LastRunTime.ToString('o');last_task_result=[int]$task.LastTaskResult;missed_runs=$task.NumberOfMissedRuns;next_run_time=$task.NextRunTime.ToString('o')}
 current_user_sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
 time_zone=[ordered]@{id=(Get-TimeZone).Id;current_offset=(Get-Date).ToString('zzz')}
 execution_policy=[string](Get-ExecutionPolicy)
 registered_xml=$task.Xml
 task_mutations=0
} | ConvertTo-Json -Depth 15 -Compress
"""


def capture(xml_path):
    path = str(Path(xml_path).resolve()).replace("'", "''")
    command = "$originalPath='"+path+"';"+READ_COM
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                            capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Read-only COM capture failed; do not assume equivalence')
    return json.loads(result.stdout)


def _flatten(value, path=''):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(_flatten(item, path+'.'+key if path else key))
    elif isinstance(value, list):
        result[path+'.count'] = len(value)
        for i, item in enumerate(value):
            result.update(_flatten(item, path+'['+str(i)+']'))
    else:
        result[path] = value
    return result


def compare_semantic(expected, actual, *, expected_enabled):
    """Only global Enabled may intentionally change; all other effective values must match.

    Inputs must be COM-derived snapshots, never XML trees with guessed defaults.
    Missing/extra properties and different JSON types fail closed.
    """
    if type(expected_enabled) is not bool:
        raise ValueError('Expected enabled state must be an explicit boolean')
    target = copy.deepcopy(expected)
    if not isinstance(target.get('settings'), dict) or type(target['settings'].get('Enabled')) is not bool:
        raise ValueError('Incomplete effective settings snapshot')
    for section in ('principal','actions_context','actions','triggers','idle_settings','network_settings'):
        if section not in target:
            raise ValueError('Incomplete effective snapshot: '+section)
    target['settings']['Enabled'] = expected_enabled
    left, right = _flatten(target), _flatten(actual)
    missing = object()
    differences = []
    for name in sorted(left.keys() | right.keys()):
        before, after = left.get(name, missing), right.get(name, missing)
        if before is missing or after is missing or type(before) is not type(after) or before != after:
            differences.append({'parameter':name, 'expected_present':before is not missing,
                                'actual_present':after is not missing,
                                'expected':None if before is missing else before,
                                'actual':None if after is missing else after})
    return {'matches':not differences, 'compared_parameters':len(left.keys() | right.keys()),
            'expected_enabled':expected_enabled, 'differences':differences}


def compare_snapshot(snapshot, *, expected_enabled, reference=None):
    result = compare_semantic(snapshot['planned_effective'], snapshot['registered_effective'],
                              expected_enabled=expected_enabled)
    runtime = snapshot['runtime']
    for name, expected in {'enabled':expected_enabled,'state':3 if expected_enabled else 1,'instances':0}.items():
        actual = runtime.get(name)
        if type(actual) is not type(expected) or actual != expected:
            result['differences'].append({'parameter':'runtime.'+name,'expected':expected,'actual':actual})
    if reference is not None:
        fields = (('current_user_sid',), ('execution_policy',), ('time_zone','id'), ('time_zone','current_offset'))
        for path in fields:
            expected, actual = reference, snapshot
            try:
                for key in path:
                    expected, actual = expected[key], actual[key]
            except (KeyError, TypeError):
                raise ValueError('Incomplete effective context: '+'.'.join(path)) from None
            if type(actual) is not type(expected) or actual != expected:
                result['differences'].append({'parameter':'context.'+'.'.join(path),'expected':expected,'actual':actual})
        result['compared_context_parameters'] = len(fields)
    result['matches'] = not result['differences']
    return result
