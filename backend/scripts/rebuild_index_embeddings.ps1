# One-click backfill wrapper for index-rerank embeddings.
#
# Usage:
#   .\scripts\rebuild_index_embeddings.ps1              # only-missing (interactive)
#   .\scripts\rebuild_index_embeddings.ps1 -Yes         # skip confirmation
#   .\scripts\rebuild_index_embeddings.ps1 -DryRun      # preview only
#   .\scripts\rebuild_index_embeddings.ps1 -All -Yes    # re-embed every doc
#   .\scripts\rebuild_index_embeddings.ps1 -Limit 5
#   .\scripts\rebuild_index_embeddings.ps1 -DocIds 1,2,3

[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$All,
    [int]$Limit,
    [string]$DocIds,
    [int]$BatchSize,
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

Write-Host "=== Index-Embedding Backfill ===" -ForegroundColor Cyan
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

$pyScript = Join-Path $scriptDir 'rebuild_index_embeddings.py'
$scriptArgs = @($pyScript)
if ($Yes)    { $scriptArgs += '--yes' }
if ($DryRun) { $scriptArgs += '--dry-run' }
if ($All)    { $scriptArgs += '--all' }
if ($PSBoundParameters.ContainsKey('Limit'))     { $scriptArgs += '--limit';      $scriptArgs += $Limit }
if ($PSBoundParameters.ContainsKey('DocIds'))    { $scriptArgs += '--doc-ids';    $scriptArgs += $DocIds }
if ($PSBoundParameters.ContainsKey('BatchSize')) { $scriptArgs += '--batch-size'; $scriptArgs += $BatchSize }

Write-Host ''
& $python @pyArgs @scriptArgs
$code = $LASTEXITCODE
Write-Host ''
Write-Host "=== Exit code: $code ===" -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Yellow' })
exit $code
