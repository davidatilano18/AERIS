[CmdletBinding()]
param(
    [switch]$Scheduled,
    [switch]$DryRun,
    [switch]$Offline,
    [switch]$RequestStop,
    [switch]$ClearStop,
    [string]$Database = '',
    [string]$KeyFile = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not $Database) { $Database = Join-Path $projectRoot 'data\aeris_air_quality.db' }
if (-not $KeyFile) { $KeyFile = Join-Path $projectRoot '.secrets\openaq_api_key.clixml' }
if ($Offline -and -not $DryRun) { throw 'Offline requiere DryRun.' }
if ($RequestStop -and $ClearStop) { throw 'Parada y reanudacion son excluyentes.' }
$arguments = @('-B', '-m', 'data_ingestion.operations', '--db', $Database)
if ($Scheduled) {
    if ($DryRun -or $Offline -or $RequestStop -or $ClearStop) { throw 'Scheduled no combina otros modos.' }
    $arguments = @('-B', '-m', 'data_ingestion.scheduled_sync', '--db', $Database, '--key-file', $KeyFile)
}
if ($DryRun) { $arguments += '--dry-run' }
if ($Offline) { $arguments += '--offline' }
if ($RequestStop) { $arguments += '--request-stop' }
if ($ClearStop) { $arguments += '--clear-stop' }
$previousKey = $env:OPENAQ_API_KEY
$pointer = [IntPtr]::Zero
Push-Location -LiteralPath $projectRoot
try {
    if (-not $Scheduled -and -not ($Offline -or $RequestStop -or $ClearStop) -and -not $env:OPENAQ_API_KEY) {
        if (-not (Test-Path -LiteralPath $KeyFile)) { throw 'Falta OPENAQ_API_KEY o el archivo DPAPI del mismo usuario.' }
        $secureKey = Import-Clixml -LiteralPath $KeyFile
        if ($secureKey -isnot [System.Security.SecureString]) { throw 'El archivo debe contener un SecureString.' }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $env:OPENAQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    & $python @arguments
    $runExitCode = $LASTEXITCODE
}
catch {
    $logDirectory = Join-Path $projectRoot 'data\sync_runtime\scheduler'
    [IO.Directory]::CreateDirectory($logDirectory) | Out-Null
    $failure = @{ status = 'wrapper_failure'; finished_at_utc = [DateTime]::UtcNow.ToString('o'); error_type = $_.Exception.GetType().Name }
    $failure | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory ('wrapper-' + [Guid]::NewGuid().ToString('N') + '.json')) -Encoding UTF8
    $runExitCode = 1
}
finally {
    $env:OPENAQ_API_KEY = $previousKey
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    Pop-Location
}
exit $runExitCode
