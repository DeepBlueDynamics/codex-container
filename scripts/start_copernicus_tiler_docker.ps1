Param(
  [switch]$Build,
  [switch]$Run,
  [switch]$Stop,
  [switch]$Restart,
  [switch]$Logs,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

# Default action is Run
if (-not ($Build -or $Run -or $Stop -or $Restart -or $Logs -or $Help)) { $Run = $true }

if ($Help) {
  Write-Host "Usage: ./scripts/start_copernicus_tiler_docker.ps1 [--Build] [--Run] [--Stop] [--Restart] [--Logs]" -ForegroundColor Cyan
  Write-Host "Starts/stops Copernicus DEM tiler via docker-compose.copernicus.yml"
  Write-Host "  --Build   : Build the image only"
  Write-Host "  --Run     : Start the service (default)"
  Write-Host "  --Stop    : Stop the service"
  Write-Host "  --Restart : Restart the service"
  Write-Host "  --Logs    : Follow container logs"
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
  Write-Host "Creating codex-network..." -ForegroundColor Yellow
  docker network create codex-network | Out-Null
}

if ($Build) {
  Write-Host "Building Copernicus tiler image..." -ForegroundColor Cyan
  docker-compose -p $projectName -f $composeFile build
  exit 0
}

if ($Stop) {
  Write-Host "Stopping Copernicus tiler..." -ForegroundColor Yellow
  docker-compose -p $projectName -f $composeFile down
  exit 0
}

if ($Restart) {
  Write-Host "Restarting Copernicus tiler..." -ForegroundColor Cyan
  docker-compose -p $projectName -f $composeFile restart
}
elseif ($Run) {
  Write-Host "Starting Copernicus tiler..." -ForegroundColor Cyan
  docker-compose -p $projectName -f $composeFile up -d --build
}

if ($Logs) {
  Write-Host "Following logs (Ctrl+C to exit)..." -ForegroundColor Cyan
  docker-compose -p $projectName -f $composeFile logs -f
} else {
  Write-Host "Copernicus tiler running at http://localhost:8081" -ForegroundColor Green
}
