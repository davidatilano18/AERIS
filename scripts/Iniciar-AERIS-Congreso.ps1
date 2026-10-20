[CmdletBinding()]
param(
    [int]$Port = 5070,
    [string]$Manifest = 'C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-20261020\demo.json',
    [switch]$ConInternet,
    [switch]$SinNavegador
)
# Demostración local de solo lectura: verifica el hash del corte, no ingiere ni predice.
# Sin -ConInternet se bloquea todo recurso externo (mapa base incluido).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "No se encontró Python en $python" }
if (-not (Test-Path -LiteralPath $Manifest)) { throw "No se encontró el corte de demostración en $Manifest" }
# Chrome bloquea algunos puertos (p. ej. 5060/5061); 5070 es seguro.
if ($Port -in 5060, 5061, 6000, 6665, 6666, 6667, 6668, 6669, 6697, 10080) { throw "Puerto $Port bloqueado por los navegadores" }
$url = "http://127.0.0.1:$Port/inicio"
$arguments = @('-B', 'scripts\run_local_demo.py', '--manifest', $Manifest, '--port', $Port)
if (-not $ConInternet) { $arguments += '--offline' }
Write-Host "AERIS · demostración en $url  (Ctrl+C para detener)"
if (-not $SinNavegador) { Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 4; Start-Process $u } -ArgumentList $url | Out-Null }
Push-Location -LiteralPath $root
try { & $python @arguments } finally { Pop-Location }
