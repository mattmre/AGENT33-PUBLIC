# AGENT-33 one-shot installer (Windows PowerShell).
# Defaults to Docker Compose. Pass -Mode source for a Python venv install.
[CmdletBinding()]
param(
    [ValidateSet('docker', 'source')]
    [string]$Mode = 'docker',
    [int]$MaxWait = 120,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

$ComposeFile = 'engine/docker-compose.yml'
$ApiUrl = 'http://localhost:8000'
$HealthPath = '/healthz'
$RepoUrl = 'https://github.com/mattmre/AGENT33-PUBLIC.git'

function Show-Usage {
    @"
Usage: .\install.ps1 [-Mode docker|source] [-MaxWait <seconds>] [-Help]

Options:
  -Mode docker   (default) Bring up the full stack via Docker Compose.
  -Mode source   Set up engine\.venv with the dev extras for local hacking.
  -MaxWait <n>   Seconds to wait for the API healthcheck (default 120).
  -Help          Show this help text and exit.
"@ | Write-Host
}

if ($Help) {
    Show-Usage
    exit 0
}

function Write-Log { param([string]$Message) Write-Host "==> $Message" }
function Write-Err { param([string]$Message) Write-Host "ERROR: $Message" -ForegroundColor Red }

function Require-Command {
    param(
        [string]$Name,
        [string]$Hint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Err "'$Name' is not installed or not on PATH."
        Write-Err $Hint
        exit 1
    }
}

function Require-RepoRoot {
    if (-not (Test-Path 'engine/pyproject.toml') -or -not (Test-Path $ComposeFile)) {
        Write-Err "Run this script from the AGENT33-PUBLIC repo root."
        Write-Err "Expected files: engine/pyproject.toml and $ComposeFile"
        Write-Err "If you have not cloned yet:"
        Write-Err "  git clone $RepoUrl ; cd AGENT33-PUBLIC ; .\install.ps1"
        exit 1
    }
}

function Wait-ForHealth {
    param([string]$Url)
    Write-Log "Waiting up to $MaxWait s for $Url ..."
    $deadline = (Get-Date).AddSeconds($MaxWait)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                Write-Log "API is healthy at $Url"
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Err "API never became healthy at $Url within $MaxWait s."
    Write-Err "Check 'docker compose -f $ComposeFile logs api' for details."
    return $false
}

function Install-Docker {
    Require-Command -Name 'git' -Hint 'Install Git for Windows from https://git-scm.com/download/win'
    Require-Command -Name 'docker' -Hint 'Install Docker Desktop from https://www.docker.com/products/docker-desktop/'

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "'docker compose' v2 plugin is not available."
        Write-Err "Update Docker Desktop so it includes Compose v2."
        exit 1
    }

    Require-RepoRoot

    if (-not (Test-Path 'engine/.env')) {
        Write-Log "Creating engine/.env from engine/.env.example"
        Copy-Item 'engine/.env.example' 'engine/.env'
    } else {
        Write-Log "engine/.env already exists, leaving it alone"
    }

    Write-Log "Building and starting the stack: docker compose -f $ComposeFile up -d"
    & docker compose -f $ComposeFile up -d --build
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose failed (exit code $LASTEXITCODE)."
        exit $LASTEXITCODE
    }

    if (-not (Wait-ForHealth -Url "$ApiUrl$HealthPath")) {
        exit 1
    }

    @"

AGENT-33 is running.

  API:       $ApiUrl
  Frontend:  http://localhost:3000
  Health:    $ApiUrl$HealthPath

Next steps:
  - Try a request:  see QUICKSTART.md
  - Tail logs:      docker compose -f $ComposeFile logs -f api
  - Stop the stack: docker compose -f $ComposeFile down
"@ | Write-Host
}

function Install-Source {
    Require-Command -Name 'git' -Hint 'Install Git for Windows from https://git-scm.com/download/win'

    $py = Get-Command 'python' -ErrorAction SilentlyContinue
    if (-not $py) {
        $py = Get-Command 'python3' -ErrorAction SilentlyContinue
    }
    if (-not $py) {
        Write-Err "Python 3.11+ is required but was not found on PATH."
        Write-Err "Install from https://www.python.org/downloads/windows/"
        exit 1
    }

    $pyVer = & $py.Name -c "import sys; print('%d.%d' % sys.version_info[:2])"
    $parts = $pyVer.Split('.')
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
        Write-Err "Python 3.11+ is required (found $pyVer)."
        exit 1
    }

    if (-not (Get-Command 'node' -ErrorAction SilentlyContinue)) {
        Write-Log "Node.js was not found; the engine will install but the frontend will not."
        Write-Log "Install Node 20+ from https://nodejs.org/ to run the UI."
    }

    Require-RepoRoot

    Write-Log "Creating engine\.venv"
    Push-Location 'engine'
    try {
        & $py.Name -m venv .venv
        $venvPy = Join-Path (Get-Location) '.venv\Scripts\python.exe'
        & $venvPy -m pip install --upgrade pip
        & $venvPy -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) {
            Write-Err "pip install failed (exit code $LASTEXITCODE)."
            exit $LASTEXITCODE
        }

        if (-not (Test-Path '.env')) {
            Write-Log "Creating engine\.env from engine\.env.example"
            Copy-Item '.env.example' '.env'
        }
    } finally {
        Pop-Location
    }

    @"

Source install complete.

To run the engine:
  .\engine\.venv\Scripts\Activate.ps1
  cd engine
  uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000

To run the frontend (in a second PowerShell window):
  cd frontend
  npm install
  npm run dev

Infra services (Postgres, Redis, NATS, SearXNG) still come from Docker:
  docker compose -f $ComposeFile up -d postgres redis nats searxng
"@ | Write-Host
}

switch ($Mode) {
    'docker' { Install-Docker }
    'source' { Install-Source }
    default {
        Write-Err "Unknown mode: $Mode"
        Show-Usage
        exit 2
    }
}
