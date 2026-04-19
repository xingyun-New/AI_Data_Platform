# One-click knowledge-graph rebuild wrapper.
#
# Usage:
#   .\scripts\rebuild_kg.ps1              # wipe + rebuild (interactive)
#   .\scripts\rebuild_kg.ps1 -Yes         # skip confirmation
#   .\scripts\rebuild_kg.ps1 -DryRun      # preview only
#   .\scripts\rebuild_kg.ps1 -Limit 5     # process at most 5 docs
#   .\scripts\rebuild_kg.ps1 -NoWipe      # keep existing rows (test union merge)
#   .\scripts\rebuild_kg.ps1 -AllowLlm    # allow LLM for docs without cached graph

[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$NoWipe,
    [switch]$AllowLlm,
    [int]$Limit,
    [string]$DocIds,
    [switch]$NoBackup
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Split-Path -Parent $scriptDir
Set-Location $backendRoot

Write-Host "=== KG Rebuild Script ===" -ForegroundColor Cyan
Write-Host "backend dir : $backendRoot"

$python = $null
try {
    $python = (Get-Command py -ErrorAction Stop).Source
    $pyArgs = @('-3')
} catch {
    try {
        $python = (Get-Command python -ErrorAction Stop).Source
        $pyArgs = @()
    } catch {
        if (Test-Path 'C:\Python313\python.exe') {
            $python = 'C:\Python313\python.exe'
            $pyArgs = @()
        } else {
            Write-Error 'No Python interpreter found. Install Python 3.11+ and retry.'
            exit 1
        }
    }
}
Write-Host "python      : $python $($pyArgs -join ' ')"

$libPath = Join-Path $backendRoot 'Lib\site-packages'
if (Test-Path $libPath) {
    $env:PYTHONPATH = "$libPath;$backendRoot"
    Write-Host "PYTHONPATH  : (includes backend/Lib/site-packages)"
} else {
    $env:PYTHONPATH = $backendRoot
    Write-Host "PYTHONPATH  : $backendRoot"
}

$dbPath = Join-Path $backendRoot 'ai_data_platform.db'
if ((Test-Path $dbPath) -and (-not $NoBackup) -and (-not $DryRun)) {
    $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupPath = "$dbPath.bak_$ts"
    Write-Host "backup      : $backupPath" -ForegroundColor Yellow
    Copy-Item $dbPath $backupPath
}

$pyScript = Join-Path $scriptDir 'rebuild_kg.py'
$scriptArgs = @($pyScript)
if ($Yes)      { $scriptArgs += '--yes' }
if ($DryRun)   { $scriptArgs += '--dry-run' }
if ($NoWipe)   { $scriptArgs += '--no-wipe' }
if ($AllowLlm) { $scriptArgs += '--allow-llm' }
if ($PSBoundParameters.ContainsKey('Limit'))  { $scriptArgs += '--limit'; $scriptArgs += $Limit }
if ($PSBoundParameters.ContainsKey('DocIds')) { $scriptArgs += '--doc-ids'; $scriptArgs += $DocIds }

Write-Host ''
& $python @pyArgs @scriptArgs
$code = $LASTEXITCODE
Write-Host ''
Write-Host "=== Exit code: $code ===" -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
exit $code
