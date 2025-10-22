#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the persistent transcription service container

.DESCRIPTION
    Builds and starts the GPU-enabled transcription service using docker-compose.
    The service keeps the Whisper large-v3 model loaded in memory for fast transcription.

.PARAMETER Build
    Rebuild the Docker image before starting

.PARAMETER Logs
    Show service logs after starting

.PARAMETER Stop
    Stop the transcription service

.PARAMETER Restart
    Restart the transcription service

.EXAMPLE
    ./start_transcription_service_docker.ps1
    Start the service (uses existing image)

.EXAMPLE
    ./start_transcription_service_docker.ps1 -Build
    Rebuild image and start service

.EXAMPLE
    ./start_transcription_service_docker.ps1 -Logs
    Start and follow logs

.EXAMPLE
    ./start_transcription_service_docker.ps1 -Stop
    Stop the service
#>
param(
    [switch]$Build,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$composeFile = Join-Path $projectRoot 'docker-compose.transcription.yml'

if (-not (Test-Path $composeFile)) {
    throw "docker-compose.transcription.yml not found at $composeFile"
}

Push-Location $projectRoot

try {
    if ($Stop) {
        Write-Host "Stopping transcription service..." -ForegroundColor Cyan
        docker-compose -f $composeFile down
        Write-Host "Transcription service stopped." -ForegroundColor Green
        return
    }

    if ($Restart) {
        Write-Host "Restarting transcription service..." -ForegroundColor Cyan
        docker-compose -f $composeFile restart
        Write-Host "Transcription service restarted." -ForegroundColor Green

        if ($Logs) {
            Write-Host "`nFollowing logs (Ctrl+C to exit)..." -ForegroundColor DarkGray
            docker-compose -f $composeFile logs -f
        }
        return
    }

    # Check if NVIDIA runtime is available
    $dockerInfo = docker info 2>&1 | Out-String
    if ($dockerInfo -notmatch 'nvidia') {
        Write-Host "WARNING: NVIDIA Docker runtime not detected. GPU acceleration may not work." -ForegroundColor Yellow
        Write-Host "To enable GPU support:" -ForegroundColor Yellow
        Write-Host "  1. Install nvidia-docker2" -ForegroundColor Yellow
        Write-Host "  2. Configure Docker to use nvidia runtime" -ForegroundColor Yellow
        Write-Host "`nContinuing with CPU-only mode..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }

    if ($Build) {
        Write-Host "Building transcription service image..." -ForegroundColor Cyan
        docker-compose -f $composeFile build --no-cache
        if ($LASTEXITCODE -ne 0) {
            throw "Build failed"
        }
        Write-Host "Build complete!" -ForegroundColor Green
    }

    Write-Host "Starting transcription service..." -ForegroundColor Cyan
    docker-compose -f $composeFile up -d

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start service"
    }

    Write-Host "`nTranscription service started!" -ForegroundColor Green
    Write-Host "  Container: gnosis-transcription-service" -ForegroundColor DarkGray
    Write-Host "  Endpoint:  http://localhost:8765" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Service endpoints:" -ForegroundColor Cyan
    Write-Host "  POST http://localhost:8765/transcribe   - Upload WAV file" -ForegroundColor Gray
    Write-Host "  GET  http://localhost:8765/status/{id}  - Check job status" -ForegroundColor Gray
    Write-Host "  GET  http://localhost:8765/download/{id} - Download transcript" -ForegroundColor Gray
    Write-Host "  GET  http://localhost:8765/health        - Health check" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Management commands:" -ForegroundColor Cyan
    Write-Host "  View logs:    docker-compose -f docker-compose.transcription.yml logs -f" -ForegroundColor Gray
    Write-Host "  Stop service: docker-compose -f docker-compose.transcription.yml down" -ForegroundColor Gray
    Write-Host "  Check status: docker ps | grep transcription" -ForegroundColor Gray

    if ($Logs) {
        Write-Host "`nFollowing logs (Ctrl+C to exit)..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 2
        docker-compose -f $composeFile logs -f
    } else {
        Write-Host "`nWaiting for service to be healthy..." -ForegroundColor DarkGray
        $maxWait = 60
        $waited = 0
        while ($waited -lt $maxWait) {
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:8765/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    Write-Host "Service is healthy!" -ForegroundColor Green
                    break
                }
            } catch {
                # Service not ready yet
            }
            Start-Sleep -Seconds 2
            $waited += 2
            Write-Host "." -NoNewline -ForegroundColor DarkGray
        }
        Write-Host ""

        if ($waited -ge $maxWait) {
            Write-Host "WARNING: Service health check timeout. Check logs with:" -ForegroundColor Yellow
            Write-Host "  docker-compose -f docker-compose.transcription.yml logs" -ForegroundColor Yellow
        }
    }

} finally {
    Pop-Location
}
