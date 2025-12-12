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
    Write-Host "Usage: ./scripts/start_opensearch_service_docker.ps1 [--Run] [--Stop] [--Restart] [--Logs]"
    Write-Host "Starts/stops OpenSearch single-node (security disabled) via docker-compose.opensearch.yml"
    exit 0
}

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.opensearch.yml"
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
    Write-Host "Stopping OpenSearch..."
    docker-compose -f $composeFile down
    exit 0
}

if ($Restart) {
    Write-Host "Restarting OpenSearch..."
    docker-compose -f $composeFile restart
}
elseif ($Run) {
    Write-Host "Starting OpenSearch..."
    docker-compose -f $composeFile up -d
}

if ($Logs) {
    Write-Host "Following logs (Ctrl+C to exit)..."
    docker-compose -f $composeFile logs -f
} else {
    Write-Host "OpenSearch running on http://localhost:9200 (no auth, security disabled)"
}
