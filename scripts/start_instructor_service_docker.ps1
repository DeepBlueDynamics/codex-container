<#
.SYNOPSIS
    Start the GPU-enabled Instructor XL embedding service (Docker Compose).

.PARAMETER Build
    Rebuild the image before starting.

.PARAMETER Logs
    Follow logs after start.

.PARAMETER Stop
    Stop the service (docker-compose down).

.PARAMETER Restart
    Restart the service.

.EXAMPLE
    .\start_instructor_service_docker.ps1 -Build

.EXAMPLE
    .\start_instructor_service_docker.ps1 -Logs
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $ProjectRoot "docker-compose.instructor.yml"

if (-not (Test-Path $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}

Set-Location $ProjectRoot

if ($Stop) {
    Write-Host "Stopping instructor service..."
    docker-compose -f $ComposeFile down
    exit 0
}

if ($Restart) {
    Write-Host "Restarting instructor service..."
    docker-compose -f $ComposeFile restart
    if ($Logs) {
        docker-compose -f $ComposeFile logs -f
    }
    exit 0
}

# Ensure codex-network exists
if (-not (docker network inspect codex-network 2>$null)) {
    Write-Host "Creating codex-network..."
    docker network create codex-network 2>$null | Out-Null
}

if ($Build) {
    Write-Host "Building instructor service image..."
    docker-compose -f $ComposeFile build --no-cache
}

Write-Host "Starting instructor service..."
docker-compose -f $ComposeFile up -d

Write-Host "Instructor service running on http://localhost:8787"
Write-Host "  POST /embed  {`"texts`": [..], `"instruction`": `"...`"}"
Write-Host "  GET  /health"

if ($Logs) {
    docker-compose -f $ComposeFile logs -f
}
