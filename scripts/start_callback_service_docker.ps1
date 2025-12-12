Param(
    [switch]$Run,
    [switch]$Stop,
    [switch]$Restart,
    [switch]$Logs,
    [switch]$Help
)

if (-not ($Run -or $Stop -or $Restart -or $Help)) { $Run = $true }

if ($Help) {
    Write-Host "Usage: ./scripts/start_callback_service_docker.ps1 [--Run] [--Stop] [--Restart] [--Logs]"
    Write-Host "Starts/stops the callback logger (gnosis-callback) via docker-compose.callback.yml"
    exit 0
}

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.callback.yml"
if (-not (Test-Path $composeFile)) {
    Write-Error "Compose file not found: $composeFile"
    exit 1
}

$net = docker network ls --format "{{.Name}}" | Select-String -Pattern "^codex-network$"
if (-not $net) {
    docker network create codex-network | Out-Null
}

if ($Stop) {
    Write-Host "Stopping callback service..."
    docker-compose -f $composeFile down
    exit 0
}

if ($Restart) {
    Write-Host "Restarting callback service..."
    docker-compose -f $composeFile restart
}
elseif ($Run) {
    Write-Host "Starting callback service..."
    docker-compose -f $composeFile up -d
}

if ($Logs) {
    Write-Host "Following logs (Ctrl+C to exit)..."
    docker-compose -f $composeFile logs -f
} else {
    Write-Host "Callback service listening on http://localhost:8088 (container: gnosis-callback)"
}
