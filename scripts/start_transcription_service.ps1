#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the persistent transcription service container.

.DESCRIPTION
    Starts a long-running Docker container that runs the transcription service daemon.
    The service keeps the Whisper model loaded in memory and processes transcription
    jobs via HTTP API.

.PARAMETER Port
    Port to expose the service on (default: 8765)

.PARAMETER Model
    Whisper model to load (default: large-v3)

.PARAMETER Rebuild
    Rebuild the codex-container image before starting service

.EXAMPLE
    .\start_transcription_service.ps1

.EXAMPLE
    .\start_transcription_service.ps1 -Port 9000 -Model medium

.EXAMPLE
    .\start_transcription_service.ps1 -Rebuild
#>

param(
    [int]$Port = 8765,
    [string]$Model = "large-v3",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " Transcription Service Startup" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Check if container already running
$ExistingContainer = docker ps -q --filter "name=codex-transcription-service" 2>$null
if ($ExistingContainer) {
    Write-Host "⚠️  Transcription service already running (container: $ExistingContainer)" -ForegroundColor Yellow
    Write-Host ""
    $Response = Read-Host "Stop and restart? (y/N)"
    if ($Response -eq "y" -or $Response -eq "Y") {
        Write-Host "Stopping existing container..." -ForegroundColor Yellow
        docker stop codex-transcription-service | Out-Null
        docker rm codex-transcription-service | Out-Null
        Write-Host "✅ Stopped" -ForegroundColor Green
    } else {
        Write-Host "Keeping existing container running" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Service URL: http://localhost:$Port" -ForegroundColor Green
        Write-Host "Health check: curl http://localhost:$Port/health" -ForegroundColor Cyan
        exit 0
    }
}

# Check for stopped container
$StoppedContainer = docker ps -aq --filter "name=codex-transcription-service" 2>$null
if ($StoppedContainer) {
    Write-Host "Removing stopped container..." -ForegroundColor Yellow
    docker rm codex-transcription-service | Out-Null
}

# Rebuild if requested
if ($Rebuild) {
    Write-Host "🔨 Rebuilding codex-container image..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        & "$ScriptDir\codex_container.ps1" -Install
        if ($LASTEXITCODE -ne 0) {
            throw "Container build failed"
        }
    } finally {
        Pop-Location
    }
    Write-Host "✅ Build complete" -ForegroundColor Green
    Write-Host ""
}

# Check if image exists
$ImageExists = docker images -q codex-container 2>$null
if (-not $ImageExists) {
    Write-Host "❌ codex-container image not found" -ForegroundColor Red
    Write-Host "   Run with -Rebuild to build the image first" -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting transcription service container..." -ForegroundColor Cyan
Write-Host "  Port: $Port" -ForegroundColor Gray
Write-Host "  Model: $Model" -ForegroundColor Gray
Write-Host ""

# Start container
try {
    $ContainerId = docker run -d `
        --name codex-transcription-service `
        --restart unless-stopped `
        -p "${Port}:8765" `
        -e "WHISPER_MODEL=$Model" `
        codex-container `
        python /opt/scripts/transcription_service_daemon.py

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start container"
    }

    Write-Host "✅ Service started" -ForegroundColor Green
    Write-Host "   Container ID: $ContainerId" -ForegroundColor Gray
    Write-Host ""

    # Wait a moment for startup
    Write-Host "Waiting for service to initialize..." -ForegroundColor Cyan
    Start-Sleep -Seconds 3

    # Show logs
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " Initial Service Logs" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    docker logs codex-transcription-service 2>&1 | Select-Object -Last 20
    Write-Host ""

    # Test health endpoint
    Write-Host "Testing health endpoint..." -ForegroundColor Cyan
    Start-Sleep -Seconds 2

    try {
        $HealthResponse = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 5
        Write-Host "✅ Health check passed" -ForegroundColor Green
        Write-Host ""
        Write-Host "Service Status:" -ForegroundColor Cyan
        Write-Host "  Model Loaded: $($HealthResponse.model_loaded)" -ForegroundColor Gray
        Write-Host "  Model Name: $($HealthResponse.model_name)" -ForegroundColor Gray
        Write-Host "  Queue Size: $($HealthResponse.queue.queued)" -ForegroundColor Gray
    } catch {
        Write-Host "⚠️  Health check not ready yet (service may still be loading model)" -ForegroundColor Yellow
        Write-Host "   This is normal if the model hasn't been downloaded before" -ForegroundColor Gray
    }

    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " Service Ready" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Service URL: http://localhost:$Port" -ForegroundColor Green
    Write-Host ""
    Write-Host "Endpoints:" -ForegroundColor Cyan
    Write-Host "  POST /transcribe      - Upload WAV file" -ForegroundColor Gray
    Write-Host "  GET  /status/{job_id} - Check job status" -ForegroundColor Gray
    Write-Host "  GET  /download/{job_id} - Download transcript" -ForegroundColor Gray
    Write-Host "  GET  /health          - Service health" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Management:" -ForegroundColor Cyan
    Write-Host "  docker logs -f codex-transcription-service  - View logs" -ForegroundColor Gray
    Write-Host "  docker stop codex-transcription-service     - Stop service" -ForegroundColor Gray
    Write-Host "  docker restart codex-transcription-service  - Restart service" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Note: The first transcription may take longer if the model needs to download (~3GB)" -ForegroundColor Yellow
    Write-Host ""

} catch {
    Write-Host "❌ Failed to start service: $_" -ForegroundColor Red

    # Show logs if container exists
    $ContainerExists = docker ps -aq --filter "name=codex-transcription-service" 2>$null
    if ($ContainerExists) {
        Write-Host ""
        Write-Host "Container logs:" -ForegroundColor Yellow
        docker logs codex-transcription-service 2>&1
    }

    exit 1
}
