#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Dump transcription system logs for debugging
.DESCRIPTION
    Finds the running codex-container and dumps relevant logs for transcription debugging
#>

param(
    [string]$OutputFile = "transcription_debug.log"
)

$ErrorActionPreference = 'Stop'

Write-Host "Finding running codex containers..." -ForegroundColor Cyan

# Find all containers running the gnosis/codex-service image
$containers = docker ps --filter "ancestor=gnosis/codex-service:dev" --format "{{.ID}}|{{.Names}}|{{.CreatedAt}}"

if (-not $containers) {
    Write-Host "No running codex-container found!" -ForegroundColor Red
    exit 1
}

# Parse and select the most recent container
$containerList = @()
foreach ($line in $containers -split "`n") {
    if ($line) {
        $parts = $line -split '\|'
        $containerList += [PSCustomObject]@{
            ID = $parts[0]
            Name = $parts[1]
            Created = $parts[2]
        }
    }
}

if ($containerList.Count -gt 1) {
    Write-Host "Found $($containerList.Count) containers, using most recent:" -ForegroundColor Yellow
    foreach ($c in $containerList) {
        Write-Host "  - $($c.Name) ($($c.ID))" -ForegroundColor DarkGray
    }
}

$container = $containerList[0]
Write-Host "Using container: $($container.Name) ($($container.ID))" -ForegroundColor Green

$outputPath = Join-Path $PWD $OutputFile
Write-Host "Writing logs to: $outputPath" -ForegroundColor Cyan

# Create log file with header
@"
================================================================================
TRANSCRIPTION SYSTEM DEBUG LOG
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Container: $($container.Name) ($($container.ID))
================================================================================

"@ | Set-Content -Path $outputPath -Encoding UTF8

# Function to append section
function Add-Section {
    param([string]$Title, [scriptblock]$Command)

    Write-Host "Collecting: $Title" -ForegroundColor DarkGray

    @"

================================================================================
$Title
================================================================================
"@ | Add-Content -Path $outputPath -Encoding UTF8

    try {
        & $Command | Add-Content -Path $outputPath -Encoding UTF8
    } catch {
        "ERROR: $($_.Exception.Message)" | Add-Content -Path $outputPath -Encoding UTF8
    }
}

# Collect all relevant logs
Add-Section "FULL CONTAINER LOGS" {
    docker logs $container.ID 2>&1
}

Add-Section "DAEMON STARTUP" {
    docker logs $container.ID 2>&1 | Select-String -Pattern "TRANSCRIPTION DAEMON|daemon|Queue file"
}

Add-Section "MCP TOOL CALLS" {
    docker logs $container.ID 2>&1 | Select-String -Pattern "MCP TOOL CALLED|transcribe-wav|Queuing job"
}

Add-Section "QUEUE STATUS" {
    docker logs $container.ID 2>&1 | Select-String -Pattern "Queue|Found.*job|Processing:"
}

Add-Section "MCP SOURCE FILE CHECK" {
    docker exec $container.ID grep -n "Queuing job" /opt/mcp-source/transcribe-wav.py 2>&1
}

Add-Section "MCP INSTALLED FILE CHECK" {
    docker exec $container.ID grep -n "Queuing job" /opt/codex-home/mcp/transcribe-wav.py 2>&1
}

Add-Section "MCP SOURCE FILE - FIRST 50 LINES" {
    docker exec $container.ID head -50 /opt/mcp-source/transcribe-wav.py 2>&1
}

Add-Section "MCP INSTALLED FILE - FIRST 50 LINES" {
    docker exec $container.ID head -50 /opt/codex-home/mcp/transcribe-wav.py 2>&1
}

Add-Section "DAEMON FILE CHECK" {
    docker exec $container.ID grep -n "TRANSCRIPTION DAEMON STARTED" /usr/local/bin/transcription_daemon.py 2>&1
}

Add-Section "QUEUE FILE STATUS" {
    docker exec $container.ID ls -la /opt/codex-home/transcription_queue.json 2>&1
}

Add-Section "QUEUE FILE CONTENTS" {
    docker exec $container.ID cat /opt/codex-home/transcription_queue.json 2>&1
}

Add-Section "TRANSCRIPT FILES IN WORKSPACE" {
    docker exec $container.ID find /workspace -name "*.transcribing.txt" -o -name "*.txt" -o -name "*.failed.txt" 2>&1
}

Add-Section "RUNNING PROCESSES" {
    docker exec $container.ID ps aux 2>&1
}

Write-Host ""
Write-Host "Log file written: $outputPath" -ForegroundColor Green
Write-Host "Lines: $((Get-Content $outputPath).Count)" -ForegroundColor DarkGray
