<#
.SYNOPSIS
    Validates orchestration index files and cross-references.
.DESCRIPTION
    Checks all files listed in ORCHESTRATION_INDEX.md exist and validates
    cross-references in core docs are not broken. Reports missing or orphaned files.
.OUTPUTS
    JSON summary of validation results. Exit 0 if healthy, non-zero if issues found.
#>

param(
    [switch]$Json,
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

# Result structure
$result = @{
    timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    orchestrationIndex = "core/ORCHESTRATION_INDEX.md"
    totalFiles = 0
    existingFiles = 0
    missingFiles = @()
    brokenCrossRefs = @()
    orphanedFiles = @()
    healthy = $true
}

# Parse ORCHESTRATION_INDEX.md for file references
$indexPath = Join-Path $RepoRoot "core\ORCHESTRATION_INDEX.md"
if (-not (Test-Path $indexPath)) {
    $result.healthy = $false
    $result.missingFiles += "core/ORCHESTRATION_INDEX.md (index itself missing)"
    if ($Json) {
        $result | ConvertTo-Json -Depth 3
    } else {
        Write-Host "ERROR: ORCHESTRATION_INDEX.md not found at $indexPath" -ForegroundColor Red
    }
    exit 1
}

$indexContent = Get-Content $indexPath -Raw
$filePattern = [regex]'`([^`]+\.md)`'
$matches = $filePattern.Matches($indexContent)

$indexedFiles = @()
foreach ($match in $matches) {
    $filePath = $match.Groups[1].Value
    $indexedFiles += $filePath
    $result.totalFiles++
    
    $fullPath = Join-Path $RepoRoot $filePath
    if (Test-Path $fullPath) {
        $result.existingFiles++
    } else {
        $result.missingFiles += $filePath
        $result.healthy = $false
    }
}

# Check cross-references within core docs
$coreDocsPath = Join-Path $RepoRoot "core"
$allMdFiles = Get-ChildItem -Path $coreDocsPath -Recurse -Filter "*.md" -ErrorAction SilentlyContinue

foreach ($file in $allMdFiles) {
    $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $content) { continue }
    
    # Find markdown links [text](path.md) and [text](../path.md)
    $linkPattern = [regex]'\[([^\]]+)\]\(([^)]+\.md)\)'
    $links = $linkPattern.Matches($content)
    
    foreach ($link in $links) {
        $linkPath = $link.Groups[2].Value
        # Skip external links
        if ($linkPath -match "^https?://") { continue }
        
        # Resolve relative path
        $baseDir = Split-Path $file.FullName -Parent
        $resolvedPath = Join-Path $baseDir $linkPath
        $resolvedPath = [System.IO.Path]::GetFullPath($resolvedPath)
        
        if (-not (Test-Path $resolvedPath)) {
            $relativePath = $file.FullName.Replace($RepoRoot, "").TrimStart("\", "/")
            $result.brokenCrossRefs += @{
                source = $relativePath
                target = $linkPath
            }
            $result.healthy = $false
        }
    }
}

# Find orphaned files (in core/ but not in index)
$indexedSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($f in $indexedFiles) { [void]$indexedSet.Add($f) }

foreach ($file in $allMdFiles) {
    $relativePath = $file.FullName.Replace($RepoRoot, "").TrimStart("\", "/").Replace("\", "/")
    # Exclude files that are expected to not be indexed
    $excludePatterns = @("core/INDEX.md", "core/README.md", "core/CHANGELOG.md")
    $isExcluded = $false
    foreach ($pattern in $excludePatterns) {
        if ($relativePath -eq $pattern) { $isExcluded = $true; break }
    }
    if (-not $isExcluded -and -not $indexedSet.Contains($relativePath)) {
        # Check if it's a sub-path match
        $found = $false
        foreach ($indexed in $indexedFiles) {
            if ($relativePath -eq $indexed) { $found = $true; break }
        }
        if (-not $found) {
            $result.orphanedFiles += $relativePath
        }
    }
}

# Output results
if ($Json) {
    $result | ConvertTo-Json -Depth 3
} else {
    Write-Host "=== Orchestration Validation Report ===" -ForegroundColor Cyan
    Write-Host "Timestamp: $($result.timestamp)"
    Write-Host "Index: $($result.orchestrationIndex)"
    Write-Host ""
    Write-Host "Files in index: $($result.totalFiles)"
    Write-Host "Files found: $($result.existingFiles)" -ForegroundColor Green
    
    if ($result.missingFiles.Count -gt 0) {
        Write-Host "Missing files: $($result.missingFiles.Count)" -ForegroundColor Red
        foreach ($f in $result.missingFiles) {
            Write-Host "  - $f" -ForegroundColor Red
        }
    }
    
    if ($result.brokenCrossRefs.Count -gt 0) {
        Write-Host "Broken cross-references: $($result.brokenCrossRefs.Count)" -ForegroundColor Yellow
        foreach ($ref in $result.brokenCrossRefs) {
            Write-Host "  - $($ref.source) -> $($ref.target)" -ForegroundColor Yellow
        }
    }
    
    if ($result.orphanedFiles.Count -gt 0) {
        Write-Host "Orphaned files (not in index): $($result.orphanedFiles.Count)" -ForegroundColor Yellow
        foreach ($f in $result.orphanedFiles) {
            Write-Host "  - $f" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    if ($result.healthy) {
        Write-Host "Status: HEALTHY" -ForegroundColor Green
    } else {
        Write-Host "Status: ISSUES FOUND" -ForegroundColor Red
    }
}

# Exit code
if ($result.healthy) {
    exit 0
} else {
    exit 1
}
