<#
.SYNOPSIS
    Warmup and pin script to keep Ollama model hot in memory.

.DESCRIPTION
    Connects to Ollama at specified endpoint, sends a warmup request to load
    the model into memory, then periodically pings to keep it hot.

.PARAMETER OllamaUrl
    Base URL for Ollama API. Default: http://localhost:11435

.PARAMETER Model
    Model name to keep warm. Default: qwen2.5-coder:14b

.PARAMETER DurationMinutes
    How long to keep the model warm. Default: 35 (30+ minutes)

.PARAMETER PingIntervalMinutes
    Interval between pings. Default: 5

.EXAMPLE
    .\warmup-pin.ps1
    .\warmup-pin.ps1 -DurationMinutes 60 -PingIntervalMinutes 3
#>

param(
    [string]$OllamaUrl = "http://localhost:11435",
    [string]$Model = "qwen2.5-coder:14b",
    [int]$DurationMinutes = 35,
    [int]$PingIntervalMinutes = 5
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] [$Level] $Message"
}

function Test-OllamaConnection {
    try {
        $response = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -Method Get -TimeoutSec 10
        return $true
    } catch {
        return $false
    }
}

function Send-WarmupRequest {
    param([string]$Url, [string]$ModelName)
    
    $body = @{
        model = $ModelName
        prompt = "Hello"
        stream = $false
    } | ConvertTo-Json

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -Uri "$Url/api/generate" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 300
        $stopwatch.Stop()
        return @{
            Success = $true
            ResponseTimeMs = $stopwatch.ElapsedMilliseconds
            Response = $response
        }
    } catch {
        $stopwatch.Stop()
        return @{
            Success = $false
            ResponseTimeMs = $stopwatch.ElapsedMilliseconds
            Error = $_.Exception.Message
        }
    }
}

function Send-PingRequest {
    param([string]$Url, [string]$ModelName)
    
    $body = @{
        model = $ModelName
        prompt = "ping"
        stream = $false
    } | ConvertTo-Json

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -Uri "$Url/api/generate" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 120
        $stopwatch.Stop()
        return @{
            Success = $true
            ResponseTimeMs = $stopwatch.ElapsedMilliseconds
        }
    } catch {
        $stopwatch.Stop()
        return @{
            Success = $false
            ResponseTimeMs = $stopwatch.ElapsedMilliseconds
            Error = $_.Exception.Message
        }
    }
}

# Main execution
Write-Log "Starting warmup-pin script"
Write-Log "Ollama URL: $OllamaUrl"
Write-Log "Model: $Model"
Write-Log "Duration: $DurationMinutes minutes"
Write-Log "Ping Interval: $PingIntervalMinutes minutes"
Write-Log "---"

# Test connection
Write-Log "Testing Ollama connection..."
if (-not (Test-OllamaConnection)) {
    Write-Log "Failed to connect to Ollama at $OllamaUrl" "ERROR"
    exit 1
}
Write-Log "Connection successful"

# Send initial warmup
Write-Log "Sending warmup request to load model into memory..."
$warmupResult = Send-WarmupRequest -Url $OllamaUrl -ModelName $Model

if (-not $warmupResult.Success) {
    Write-Log "Warmup failed: $($warmupResult.Error)" "ERROR"
    exit 1
}
Write-Log "Warmup complete. Response time: $($warmupResult.ResponseTimeMs)ms"

# Calculate end time
$endTime = (Get-Date).AddMinutes($DurationMinutes)
$pingCount = 0
$failedPings = 0

Write-Log "Model loaded. Will keep warm until $(Get-Date $endTime -Format 'HH:mm:ss')"
Write-Log "---"

# Ping loop
while ((Get-Date) -lt $endTime) {
    $sleepSeconds = $PingIntervalMinutes * 60
    Write-Log "Sleeping $PingIntervalMinutes minutes until next ping..."
    Start-Sleep -Seconds $sleepSeconds
    
    if ((Get-Date) -ge $endTime) {
        break
    }
    
    $pingCount++
    Write-Log "Sending ping #$pingCount..."
    $pingResult = Send-PingRequest -Url $OllamaUrl -ModelName $Model
    
    if ($pingResult.Success) {
        Write-Log "Ping #$pingCount successful. Response time: $($pingResult.ResponseTimeMs)ms"
    } else {
        $failedPings++
        Write-Log "Ping #$pingCount failed: $($pingResult.Error)" "WARN"
    }
}

# Summary
Write-Log "---"
Write-Log "Session complete"
Write-Log "Total pings: $pingCount"
Write-Log "Failed pings: $failedPings"
Write-Log "Duration: $DurationMinutes minutes"

if ($failedPings -gt ($pingCount / 2)) {
    Write-Log "Too many failed pings. Model may not have stayed hot." "ERROR"
    exit 1
}

Write-Log "Model stayed hot for 30+ minutes. SUCCESS"
exit 0
