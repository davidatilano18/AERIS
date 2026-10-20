[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Install,
    [string]$TaskName = 'AERIS-OpenAQ-Hourly',
    [ValidateRange(1,24)][int]$EveryHours = 1
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $projectRoot '.venv\Scripts\python.exe'
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = $runner
$commandArguments = '-B -m data_ingestion.scheduled_sync --db "' + (Join-Path $projectRoot 'data\aeris_air_quality.db') + '" --key-file "' + (Join-Path $projectRoot '.secrets\openaq_api_key.clixml') + '"'
$firstRun = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes(5)
if ($firstRun -le (Get-Date)) { $firstRun = $firstRun.AddHours(1) }
$plan = [ordered]@{
    task = $TaskName; user = $account; executable = $powershell; arguments = $commandArguments
    working_directory = $projectRoot; interval_hours = $EveryHours
    logon_type = 'Interactive'; run_level = 'Limited'; multiple_instances = 'IgnoreNew'
    execution_limit_minutes = 20; installed = $false
    first_run_local = $firstRun.ToString('o'); time_zone = (Get-TimeZone).Id
    execution_policy = [string](Get-ExecutionPolicy)
    limitation = 'Requiere sesion iniciada, equipo despierto, red y clave DPAPI del mismo usuario.'
}
if (-not $Install) { $plan | ConvertTo-Json; return }
if ($PSCmdlet.ShouldProcess($TaskName, 'Instalar tarea horaria de recopilacion real en SQLite')) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'La tarea ya existe; no se sobrescribe.' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.secrets\openaq_api_key.clixml'))) {
        throw 'Configure primero la clave DPAPI segun docs/automated_collection.md.'
    }
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $commandArguments -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $firstRun -RepetitionInterval (New-TimeSpan -Hours $EveryHours)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable -Disable
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'AERIS: OpenAQ real, aditivo, respaldo y QC; sin predicciones.' | Out-Null
    $plan.installed = $true
    $plan | ConvertTo-Json
}
