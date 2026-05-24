#Requires -Version 7.0
<#
.SYNOPSIS
    scripts/smoke.ps1 — project release gate Rule 5 smoke gate (PowerShell variant).

.DESCRIPTION
    Native PowerShell 7+ wrapper for the v3.5 smoke gate. Functionally equivalent to
    scripts/smoke.sh — same two-stage layout, same exit-code contract, same banner-with-tier.

    Use this wrapper when:
    - You are on Windows and do not have Git Bash installed.
    - You hit Bash/WSL interop failures launching Windows native binaries (node.exe,
      python.exe, etc.) and need a wrapper that does not transit a POSIX shell.
    - Your CI runner is a Windows agent and you prefer a native PowerShell step over
      calling bash.

    The bash wrapper is still the canonical reference. This script is intentionally a
    parallel implementation, not a "preferred" replacement; both wrappers should produce
    equivalent output for the same product state.

.PARAMETER ApiOnly
    Alias --api-only. Runs only Stage 1 (surface boot). Stage 2 is reported SKIPPED.
    The script still EXITS NON-ZERO — Rule 5 demands full end-to-end smoke for "complete" PRs.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1
    pwsh -File scripts/smoke.ps1 --api-only
#>

$ErrorActionPreference = 'Continue'
# Load-bearing: strict CI runners may pre-set $PSDefaultParameterValues['*:ErrorAction']='Stop',
# which would override the preference above for individual cmdlets (e.g. Write-Error on the
# Stage 1 SKIPPED status line) and abort before the SUMMARY block prints. Drop any inherited
# *:ErrorAction default so this wrapper runs through to the SUMMARY contract per Rule 5.
if ($PSDefaultParameterValues -and $PSDefaultParameterValues.ContainsKey('*:ErrorAction')) { $PSDefaultParameterValues.Remove('*:ErrorAction') | Out-Null }

# --- Arg parsing (mirror bash --api-only / --skip-stage2 / --help / --detect-language) ----
$apiOnly = $false
$detectOnly = $false
foreach ($arg in $args) {
    switch ($arg) {
        '--api-only'        { $apiOnly = $true }
        '--skip-stage2'     { $apiOnly = $true }
        '--detect-language' { $detectOnly = $true }
        '--help'       {
            # Print the comment-based help section then exit.
            Get-Help $MyInvocation.MyCommand.Path -Detailed
            exit 0
        }
        '-h'           {
            Get-Help $MyInvocation.MyCommand.Path -Detailed
            exit 0
        }
        default        {
            Write-Error "smoke.ps1: unknown argument: $arg"
            exit 2
        }
    }
}

# --- Python binary detection (parallels smoke.sh #13 ladder) ----------------------------
$pythonBin = $null
foreach ($candidate in @('python', 'python.exe', 'python3')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $pythonBin = $candidate
        break
    }
}
if (-not $pythonBin) {
    Write-Error "smoke.ps1: neither python, python.exe, nor python3 is available on PATH"
    Write-Error "smoke.ps1: install Python 3.10+ and re-run"
    exit 127
}

# --- Repo root + cd ---------------------------------------------------------------------
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

# --- Language detection / runner dispatch (issue #5) ------------------------------------
function Detect-Language {
    $configPath = Join-Path $repoRoot 'smoke.config.json'
    if (Test-Path $configPath) {
        try {
            $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
            if ($cfg -and $cfg.language) {
                return @($cfg.language)
            }
        } catch {
            Write-Error "smoke.ps1: smoke.config.json is not valid JSON: $($_.Exception.Message)"
            exit 3
        }
        return @()
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    if (Test-Path (Join-Path $repoRoot 'package.json'))   { [void]$candidates.Add('node') }
    if (Test-Path (Join-Path $repoRoot 'pyproject.toml')) { [void]$candidates.Add('python') }
    if (Test-Path (Join-Path $repoRoot 'setup.py'))       { [void]$candidates.Add('python') }
    if (Test-Path (Join-Path $repoRoot 'go.mod'))         { [void]$candidates.Add('shell') }
    if (Test-Path (Join-Path $repoRoot 'Cargo.toml'))     { [void]$candidates.Add('shell') }
    return @($candidates | Sort-Object -Unique)
}

$languageCandidates = @(Detect-Language)
$smokeLanguage = ''
if ($languageCandidates.Count -eq 1) {
    $smokeLanguage = $languageCandidates[0]
} elseif ($languageCandidates.Count -gt 1) {
    Write-Error "smoke.ps1: ambiguous language detection: candidates=($($languageCandidates -join ' '))"
    Write-Error 'smoke.ps1: create smoke.config.json at the repo root with an explicit "language" field.'
    Write-Error 'smoke.ps1: see v3.5/scripts/smoke.config.json.example for the format.'
    exit 3
}

if ($detectOnly) {
    if ($smokeLanguage) { Write-Output $smokeLanguage }
    exit 0
}

# --- Status accumulator -----------------------------------------------------------------
$smokeStatus = 0
$stage1Result = 'NOT RUN'
$stage2Result = 'NOT RUN'
$stage2Reason = ''

Write-Output ('=' * 73)
Write-Output 'project release gate Rule 5 smoke (PowerShell)'
Write-Output "Repo root: $repoRoot"
Write-Output "Started:   $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
Write-Output ('=' * 73)

# --- Stage 1: application/surface boot smoke -------------------------------------------
Write-Output ''
Write-Output '--- Stage 1: application/surface boot smoke ---'
$stage1Path = Join-Path 'tests' 'test_e2e_smoke.py'
if (Test-Path $stage1Path) {
    & $pythonBin -m pytest $stage1Path -v --tb=short -x
    if ($LASTEXITCODE -eq 0) {
        $stage1Result = 'PASS'
        Write-Output 'Stage 1 PASS'
    } else {
        $stage1Result = 'FAIL'
        $smokeStatus = 1
        Write-Error 'Stage 1 FAIL — application surface does not boot. Halting before Stage 2.'
    }
} else {
    $stage1Result = 'SKIPPED'
    $stage2Reason = 'tests/test_e2e_smoke.py not present'
    $smokeStatus = 1
    Write-Error 'Stage 1 SKIPPED — no tests/test_e2e_smoke.py found.'
    Write-Error 'Add a surface-boot test (FastAPI client, Django setup, CLI parser, etc.)'
    Write-Error 'and re-run. Rule 5 requires a deterministic Stage 1 surface check.'
}

# --- Stage 2: production-pipeline smoke -------------------------------------------------
if ($apiOnly) {
    $stage2Result = 'SKIPPED'
    $stage2Reason = '--api-only flag set by caller'
    $smokeStatus = 1
    Write-Output ''
    Write-Output '--- Stage 2: SKIPPED (--api-only) ---'
    Write-Output 'NOTE: Rule 5 (v3.5) requires end-to-end production-path verification.'
    Write-Output '      --api-only is acceptable for docs-only PRs but smoke EXITS NON-ZERO'
    Write-Output '      so the caller must explicitly disclose the skip in PR body SMOKE: line.'
}
elseif ($stage1Result -ne 'PASS') {
    $stage2Result = 'SKIPPED'
    $stage2Reason = 'Stage 1 failed — Stage 2 cannot run on a broken stack'
    Write-Output ''
    Write-Output '--- Stage 2: SKIPPED (Stage 1 failed) ---'
}
else {
    $runner = $null
    $runCmd = @()
    switch ($smokeLanguage) {
        'python' {
            $runner = Join-Path 'scripts' 'smoke_pipeline.py'
            $runCmd = @($pythonBin, $runner)
        }
        'node' {
            $runner = Join-Path 'scripts' 'smoke_pipeline.mjs'
            if (Get-Command 'node' -ErrorAction SilentlyContinue) {
                $runCmd = @('node', $runner)
            } else {
                $stage2Result = 'SKIPPED'
                $stage2Reason = 'node binary not on PATH (language=node)'
                $smokeStatus = 1
            }
        }
        'shell' {
            $runner = Join-Path 'scripts' 'smoke_pipeline.sh'
            if (Get-Command 'bash' -ErrorAction SilentlyContinue) {
                $runCmd = @('bash', $runner)
            } else {
                $stage2Result = 'SKIPPED'
                $stage2Reason = 'bash binary not on PATH (language=shell — install Git Bash or WSL)'
                $smokeStatus = 1
            }
        }
        '' {
            $stage2Result = 'SKIPPED'
            $stage2Reason = 'no language detected; create smoke.config.json with a "language" field'
            $smokeStatus = 1
        }
        default {
            $stage2Result = 'SKIPPED'
            $stage2Reason = "unknown language: $smokeLanguage"
            $smokeStatus = 1
        }
    }

    if ($runCmd.Count -gt 0) {
        if (-not (Test-Path $runner)) {
            $stage2Result = 'SKIPPED'
            $stage2Reason = "$runner not present (copy ${runner}.template and fill placeholders)"
            $smokeStatus = 1
            Write-Output ''
            Write-Error "--- Stage 2: SKIPPED (no $runner) ---"
            Write-Error "Copy $runner.template to $runner and fill in the placeholders for your repo."
        } else {
            Write-Output ''
            Write-Output "--- Stage 2: production-pipeline smoke (language=$smokeLanguage) ---"
            $exe = $runCmd[0]
            $exeArgs = @($runCmd | Select-Object -Skip 1)
            & $exe @exeArgs
            if ($LASTEXITCODE -eq 0) {
                $stage2Result = 'PASS'
                Write-Output 'Stage 2 PASS'
            } else {
                $stage2Result = 'FAIL'
                $stage2Reason = "see $runner output above"
                $smokeStatus = 1
                Write-Error 'Stage 2 FAIL'
            }
        }
    } else {
        Write-Output ''
        Write-Error "--- Stage 2: SKIPPED ($stage2Reason) ---"
    }
}

# --- Summary ----------------------------------------------------------------------------
$reasonSuffix = if ($stage2Reason) { " ($stage2Reason)" } else { '' }
Write-Output ''
Write-Output ('=' * 73)
Write-Output 'SMOKE SUMMARY'
Write-Output "  Stage 1 (surface boot):        $stage1Result"
Write-Output "  Stage 2 (production pipeline): $stage2Result$reasonSuffix"
Write-Output "  Overall exit code:             $smokeStatus"
Write-Output "  Finished:                      $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
Write-Output ('=' * 73)

exit $smokeStatus
