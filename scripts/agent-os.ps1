param(
    [ValidateSet("start", "shell", "status", "logs", "stop", "list", "clean")]
    [string]$Command = "start",
    [string]$Session = "default"
)

$ErrorActionPreference = "Stop"
$SessionArgumentProvided = $PSBoundParameters.ContainsKey("Session")
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $RepoRoot "engine\docker-compose.yml"
$EnvFile = Join-Path $RepoRoot "engine\.env"
$EnvExample = Join-Path $RepoRoot "engine\.env.example"
$SessionRoot = Join-Path $RepoRoot ".agent-os\sessions"
$ActiveSessionFile = Join-Path $RepoRoot ".agent-os\active-session"

function Ensure-AgentOsEnv {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "Created engine\.env from .env.example. Rotate secrets before shared use."
    }
}

function Assert-AgentOsSessionName {
    param([string]$Name)

    if ($Name -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$") {
        throw "Invalid session name '$Name'. Use letters, numbers, '.', '_', or '-', starting with a letter or number."
    }
}

function Get-AgentOsSessionDirectory {
    param([string]$Name)

    Join-Path $SessionRoot $Name
}

function Get-AgentOsSessionWorkspace {
    param([string]$Name)

    Join-Path (Get-AgentOsSessionDirectory $Name) "workspace"
}

function Get-ActiveAgentOsSession {
    if (Test-Path $ActiveSessionFile) {
        return (Get-Content $ActiveSessionFile -Raw).Trim()
    }

    "default"
}

function Resolve-RunningAgentOsSession {
    param([string]$RequestedName)

    $active = Get-ActiveAgentOsSession
    if ($RequestedName) {
        Assert-AgentOsSessionName $RequestedName
        if ($RequestedName -ne $active) {
            throw "Session '$RequestedName' is not active. Start it first with: scripts\agent-os.ps1 start $RequestedName"
        }
    }

    $active
}

function Use-AgentOsSession {
    param(
        [string]$Name,
        [switch]$Activate
    )

    Assert-AgentOsSessionName $Name
    $workspace = Get-AgentOsSessionWorkspace $Name

    if ($Activate) {
        New-Item -ItemType Directory -Path $workspace -Force | Out-Null
        New-Item -ItemType Directory -Path (Split-Path -Parent $ActiveSessionFile) -Force | Out-Null
        Set-Content -Path $ActiveSessionFile -Value $Name
    }

    $env:AGENT_OS_SESSION_NAME = $Name
    $env:AGENT_OS_SESSION_WORKSPACE = $workspace
}

function Write-AgentOsSessionStatus {
    $active = Get-ActiveAgentOsSession
    Write-Host "Active Agent OS session: $active"
    Write-Host "Session workspace: $(Get-AgentOsSessionWorkspace $active)"
}

switch ($Command) {
    "start" {
        Ensure-AgentOsEnv
        Use-AgentOsSession $Session -Activate
        docker compose -f $ComposeFile --profile agent-os up -d postgres redis nats searxng api
        docker compose -f $ComposeFile --profile agent-os up -d --force-recreate agent-os
        Write-Host "Agent OS session '$Session' is starting."
        Write-Host "Open it with: scripts\agent-os.ps1 shell"
    }
    "shell" {
        Ensure-AgentOsEnv
        $targetSession = if ($SessionArgumentProvided) { Resolve-RunningAgentOsSession $Session } else { Resolve-RunningAgentOsSession "" }
        Use-AgentOsSession $targetSession
        docker compose -f $ComposeFile --profile agent-os exec agent-os bash -lc 'cd "${AGENT33_WORKSPACE:-/agent-workspace}" && exec bash -l'
    }
    "status" {
        Ensure-AgentOsEnv
        Use-AgentOsSession (Get-ActiveAgentOsSession)
        Write-AgentOsSessionStatus
        docker compose -f $ComposeFile --profile agent-os ps
    }
    "logs" {
        Ensure-AgentOsEnv
        Use-AgentOsSession (Get-ActiveAgentOsSession)
        docker compose -f $ComposeFile --profile agent-os logs --tail=120 agent-os
    }
    "stop" {
        Ensure-AgentOsEnv
        Use-AgentOsSession (Get-ActiveAgentOsSession)
        docker compose -f $ComposeFile --profile agent-os down
    }
    "list" {
        New-Item -ItemType Directory -Path $SessionRoot -Force | Out-Null
        Write-AgentOsSessionStatus
        Write-Host ""
        Write-Host "Known sessions:"
        Get-ChildItem -Path $SessionRoot -Directory |
            Sort-Object Name |
            ForEach-Object { Write-Host "  $($_.Name)" }
    }
    "clean" {
        Assert-AgentOsSessionName $Session
        if ($Session -eq (Get-ActiveAgentOsSession)) {
            throw "Refusing to clean active session '$Session'. Stop Agent OS or start a different session first."
        }

        $sessionDirectory = Get-AgentOsSessionDirectory $Session
        if (-not (Test-Path $sessionDirectory)) {
            throw "No Agent OS session named '$Session' exists."
        }

        Remove-Item -Path $sessionDirectory -Recurse -Force
        Write-Host "Removed Agent OS session '$Session'."
    }
}
