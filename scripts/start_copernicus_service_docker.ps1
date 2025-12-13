Param(
    [switch]$Run,
    [switch]$Stop,
    [switch]$Restart,
    [switch]$Logs,
    [switch]$Help
)

# Default action is Run
if (-not ($Run -or $Stop -or $Restart -or $Help)) { $Run = $true }

if ($Help) {
    Write-Host "Usage: ./scripts/start_copernicus_service_docker.ps1 [--Run] [--Stop] [--Restart] [--Logs]" -ForegroundColor Cyan
    Write-Host "Starts/stops Copernicus DEM tiler via docker-compose.copernicus.yml"
    exit 0
}

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.copernicus.yml"
$projectName = "codex-container"
if (-not (Test-Path $composeFile)) {
    Write-Error "Compose file not found: $composeFile"
    exit 1
}

# Ensure codex-network exists
$net = docker network ls --format "{{.Name}}" | Select-String -Pattern "^codex-network$"
if (-not $net) {
    docker network create codex-network | Out-Null
}

if ($Stop) {
    Write-Host "Stopping Copernicus tiler..."
    docker-compose -p $projectName -f $composeFile down
    exit 0
}

if ($Restart) {
    Write-Host "Restarting Copernicus tiler..."
    docker-compose -p $projectName -f $composeFile restart
}
elseif ($Run) {
    Write-Host "Starting Copernicus tiler..."
    docker-compose -p $projectName -f $composeFile up -d --build
}

if ($Logs) {
    Write-Host "Following logs (Ctrl+C to exit)..."
    docker-compose -p $projectName -f $composeFile logs -f
} else {
    Write-Host "Copernicus tiler expected on http://localhost:8081" -ForegroundColor Green
}
