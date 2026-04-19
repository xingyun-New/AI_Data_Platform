<#
.SYNOPSIS
    Deploy AI_Data_Platform to a remote Linux server via SSH + Docker.

.DESCRIPTION
    Pulls the project from GitHub into /var/opt/AI_Data_Platform (configurable),
    interactively generates .env on first deploy, then runs docker compose with
    the production override. Uses plink.exe / pscp.exe (PuTTY) for SSH.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy.ps1 `
        -ServerHost "172.24.122.176" -Username "mci-edpadmin" -Password "Mci1001"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]  [string] $ServerHost,
    [Parameter(Mandatory = $true)]  [string] $Username,
    [Parameter(Mandatory = $true)]  [string] $Password,
    [Parameter(Mandatory = $false)] [int]    $Port       = 22,
    [Parameter(Mandatory = $false)] [string] $RepoUrl    = 'https://github.com/xingyun-New/AI_Data_Platform.git',
    [Parameter(Mandatory = $false)] [string] $TargetDir  = '/var/opt/AI_Data_Platform',
    [Parameter(Mandatory = $false)] [string] $Branch     = 'main',
    [Parameter(Mandatory = $false)]
    [ValidateSet('auto','fresh','update')]
    [string] $Mode = 'auto'
)

$ErrorActionPreference = 'Stop'
$script:TotalSteps = 10

# ---------- Helpers ----------

function Write-Step {
    param([int]$Index, [string]$Message)
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Index, $script:TotalSteps, $Message) -ForegroundColor Cyan
}

function Write-Ok    { param([string]$m) Write-Host "    OK   - $m" -ForegroundColor Green }
function Write-Info  { param([string]$m) Write-Host "    INFO - $m" -ForegroundColor Gray }
function Write-Warn2 { param([string]$m) Write-Host "    WARN - $m" -ForegroundColor Yellow }
function Fail        { param([string]$m) Write-Host "    FAIL - $m" -ForegroundColor Red; exit 1 }

function Assert-LocalTool {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Fail "$Name not found on PATH. Install PuTTY: https://www.putty.org/ or 'winget install PuTTY.PuTTY'"
    }
    Write-Ok "$Name found at $($cmd.Source)"
}

function Invoke-Plink {
    <#
    Runs a single remote command via plink. Returns stdout. Throws on non-zero exit.
    #>
    param(
        [Parameter(Mandatory = $true)] [string] $Command,
        [switch] $AcceptHostKey,
        [switch] $AllowFail
    )

    $plinkArgs = @('-ssh','-batch','-pw', $Password, '-P', $Port, "$Username@$ServerHost", $Command)

    # git/docker write progress to stderr; under $ErrorActionPreference='Stop'
    # PowerShell treats native stderr writes as terminating errors even on
    # exit=0. Temporarily relax that inside this helper and rely on
    # $LASTEXITCODE to detect real failures.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($AcceptHostKey) {
            $output = 'y' | & plink.exe @plinkArgs 2>&1
        } else {
            $output = & plink.exe @plinkArgs 2>&1
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }

    if ($code -ne 0 -and -not $AllowFail) {
        Write-Host ($output | Out-String) -ForegroundColor DarkYellow
        Fail "Remote command failed (exit=$code): $Command"
    }
    return ($output | Out-String)
}

function Invoke-PlinkSudo {
    <#
    Runs a remote command with sudo -S, piping the SSH password as the sudo password.
    Assumes the login password and the sudo password are the same (common case).

    We intentionally avoid 'bash -c "..."' wrapping: plink.exe on Windows goes
    through CommandLineToArgvW which collapses inner double-quotes, so a command
    like `docker compose` ends up as two separate tokens and 'compose' is lost.
    Instead we feed the command straight into the remote login shell via the
    plink command-string, which is itself parsed by /bin/sh on the server.
    #>
    param([Parameter(Mandatory = $true)] [string] $Command)

    $wrapped = "echo '$Password' | sudo -S $Command 2>&1"
    return Invoke-Plink -Command $wrapped
}

function Push-File {
    param(
        [Parameter(Mandatory = $true)] [string] $LocalPath,
        [Parameter(Mandatory = $true)] [string] $RemotePath
    )
    $pscpArgs = @('-batch','-pw', $Password, '-P', $Port, $LocalPath, "${Username}@${ServerHost}:${RemotePath}")
    & pscp.exe @pscpArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "pscp failed: $LocalPath -> $RemotePath" }
}

# ---------- Step 1: banner ----------

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " AI_Data_Platform Deployment" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ("  Host      : {0}:{1}" -f $ServerHost, $Port)
Write-Host ("  User      : {0}" -f $Username)
Write-Host ("  Repo      : {0}" -f $RepoUrl)
Write-Host ("  Target    : {0}" -f $TargetDir)
Write-Host ("  Branch    : {0}" -f $Branch)
Write-Host ("  Mode      : {0}" -f $Mode)

# ---------- Step 2: verify local tools ----------

Write-Step 2 "Verify local tools (plink.exe, pscp.exe)"
Assert-LocalTool -Name 'plink.exe'
Assert-LocalTool -Name 'pscp.exe'

# ---------- Step 3: SSH connectivity + accept host key ----------

Write-Step 3 "Test SSH connectivity"
$greeting = Invoke-Plink -Command "echo __SSH_OK__ && uname -a" -AcceptHostKey
if ($greeting -notmatch '__SSH_OK__') {
    Fail "SSH connection test failed. Output was:`n$greeting"
}
Write-Ok ("SSH connected: " + ($greeting -split "`n" | Where-Object { $_ -match 'Linux' } | Select-Object -First 1))

# ---------- Step 4: verify remote deps ----------

Write-Step 4 "Verify remote dependencies (git / docker / docker compose)"
$depCheck = Invoke-Plink -Command "command -v git >/dev/null 2>&1 && echo GIT_OK; command -v docker >/dev/null 2>&1 && echo DOCKER_OK; docker compose version >/dev/null 2>&1 && echo COMPOSE_OK"
if ($depCheck -notmatch 'GIT_OK')     { Fail "git not installed on remote. Install: sudo apt-get install -y git" }
if ($depCheck -notmatch 'DOCKER_OK')  { Fail "docker not installed on remote. Install: https://docs.docker.com/engine/install/" }
if ($depCheck -notmatch 'COMPOSE_OK') { Fail "docker compose v2 plugin not installed on remote. Install: sudo apt-get install -y docker-compose-plugin" }
Write-Ok "git, docker, docker compose all present"

# Whether current user is in the docker group (informational only)
$dockerGroup = Invoke-Plink -Command "id -nG | tr ' ' '\n' | grep -x docker >/dev/null && echo IN_GROUP || echo NOT_IN_GROUP"
if ($dockerGroup -match 'NOT_IN_GROUP') {
    Write-Warn2 "User '$Username' is NOT in the 'docker' group. Docker commands will use sudo."
    $script:DockerNeedsSudo = $true
} else {
    $script:DockerNeedsSudo = $false
}

function Invoke-Docker {
    param([string]$ArgString)
    if ($script:DockerNeedsSudo) {
        return Invoke-PlinkSudo -Command ("docker " + $ArgString)
    } else {
        return Invoke-Plink -Command ("docker " + $ArgString)
    }
}

# ---------- Step 5: ensure TargetDir exists ----------

Write-Step 5 "Ensure target directory $TargetDir"
$existsCheck = Invoke-Plink -Command "test -d '$TargetDir' && echo EXISTS || echo MISSING"

if ($existsCheck -match 'MISSING') {
    Write-Info "Creating $TargetDir (requires sudo)"
    Invoke-PlinkSudo -Command "mkdir -p '$TargetDir' && chown -R '$Username':'$Username' '$TargetDir'" | Out-Null
    Write-Ok "Created and chowned to $Username"
} else {
    # Make sure we own it
    $ownerCheck = Invoke-Plink -Command "stat -c '%U' '$TargetDir'"
    if ($ownerCheck.Trim() -ne $Username) {
        Write-Info "Fixing ownership of $TargetDir"
        Invoke-PlinkSudo -Command "chown -R '$Username':'$Username' '$TargetDir'" | Out-Null
    }
    Write-Ok "Target directory ready"
}

# ---------- Step 6: clone or update ----------

Write-Step 6 "Fetch source code"

# resolve effective mode
$gitCheck = Invoke-Plink -Command "test -d '$TargetDir/.git' && echo HAS_GIT || echo NO_GIT"
$effectiveMode = $Mode
if ($effectiveMode -eq 'auto') {
    if ($gitCheck -match 'HAS_GIT') { $effectiveMode = 'update' } else { $effectiveMode = 'fresh' }
    Write-Info "auto mode resolved to '$effectiveMode'"
}

if ($effectiveMode -eq 'fresh') {
    Write-Info "Fresh clone (wiping $TargetDir)"
    Invoke-Plink -Command "rm -rf '$TargetDir'/* '$TargetDir'/.[!.]* '$TargetDir'/..?* 2>/dev/null; true" | Out-Null
    Invoke-Plink -Command "git clone --branch '$Branch' '$RepoUrl' '$TargetDir'" | Out-Null
    Write-Ok "Cloned $RepoUrl ($Branch) into $TargetDir"
} else {
    Write-Info "Updating existing checkout"
    Invoke-Plink -Command "cd '$TargetDir' && git fetch --all --prune && git checkout '$Branch' && git reset --hard origin/'$Branch'" | Out-Null
    $headInfo = Invoke-Plink -Command "cd '$TargetDir' && git log -1 --oneline"
    Write-Ok ("HEAD is now at: " + $headInfo.Trim())
}

# ---------- Step 7 + 8: .env files ----------

Write-Step 7 "Backend .env and root compose .env"

$envBackendExists = Invoke-Plink -Command "test -f '$TargetDir/backend/.env' && echo YES || echo NO"
$envRootExists    = Invoke-Plink -Command "test -f '$TargetDir/.env' && echo YES || echo NO"

$shouldGenerateBackendEnv = ($envBackendExists -match 'NO') -or ($effectiveMode -eq 'fresh')
$shouldGenerateRootEnv    = ($envRootExists    -match 'NO') -or ($effectiveMode -eq 'fresh')

if ($shouldGenerateBackendEnv -or $shouldGenerateRootEnv) {
    $genEnvScript = Join-Path $PSScriptRoot 'gen_env.ps1'
    if (-not (Test-Path $genEnvScript)) { Fail "gen_env.ps1 not found next to deploy.ps1" }

    & $genEnvScript `
        -ServerHost  $ServerHost `
        -Username    $Username `
        -Password    $Password `
        -Port        $Port `
        -TargetDir   $TargetDir `
        -WriteBackend:$shouldGenerateBackendEnv `
        -WriteRoot:$shouldGenerateRootEnv
    if ($LASTEXITCODE -ne 0) { Fail "gen_env.ps1 failed" }
    Write-Ok ".env generation finished"
} else {
    Write-Ok "backend/.env and root .env already exist; update mode will NOT overwrite"
}

# ---------- Step 9: data dirs ----------

Write-Step 9 "Create data directories (volumes)"
Invoke-Plink -Command "mkdir -p '$TargetDir/data/raw' '$TargetDir/data/redacted' '$TargetDir/data/index'" | Out-Null
Write-Ok "data/raw, data/redacted, data/index ready"

# ---------- Step 10: docker compose up + health check ----------

Write-Step 10 "docker compose up -d --build (with prod override)"

$composeCmd = "docker compose --project-directory '$TargetDir' -f '$TargetDir/docker-compose.yml' -f '$TargetDir/docker-compose.prod.yml' up -d --build"
if ($script:DockerNeedsSudo) {
    Invoke-PlinkSudo -Command $composeCmd | Write-Host
} else {
    Invoke-Plink -Command $composeCmd | Write-Host
}

Start-Sleep -Seconds 5

Write-Host ""
Write-Host "Health check ..." -ForegroundColor Cyan

$ps = Invoke-Docker -ArgString "compose -f '$TargetDir/docker-compose.yml' -f '$TargetDir/docker-compose.prod.yml' --project-directory '$TargetDir' ps"
Write-Host $ps

$backendOk  = Invoke-Plink -Command "curl -sf -o /dev/null -w '%{http_code}' http://localhost:8000/docs || true"
$frontendOk = Invoke-Plink -Command "curl -sf -o /dev/null -w '%{http_code}' http://localhost:9000/ || true"

if ($backendOk.Trim()  -match '^(200|301|302|307|308)$') { Write-Ok ("backend  : http://{0}:8000/docs ({1})" -f $ServerHost, $backendOk.Trim()) }
else                                                     { Write-Warn2 ("backend  : HTTP {0} (check 'docker logs ai_data_platform_backend')" -f $backendOk.Trim()) }

if ($frontendOk.Trim() -match '^(200|301|302|307|308)$') { Write-Ok ("frontend : http://{0}:9000/ ({1})" -f $ServerHost, $frontendOk.Trim()) }
else                                                     { Write-Warn2 ("frontend : HTTP {0} (check 'docker logs ai_data_platform_frontend')" -f $frontendOk.Trim()) }

Write-Host ""
Write-Host "Deployment finished." -ForegroundColor Green
Write-Host ("  Access URL: http://{0}:9000/" -f $ServerHost)
Write-Host ("  API docs  : http://{0}:8000/docs" -f $ServerHost)
