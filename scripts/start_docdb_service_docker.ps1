<#
.SYNOPSIS
    Build/run/stop docdb + docdb-mcp (docker-compose.docdb.yml)
.PARAMETER Build
    Build images
.PARAMETER Run
    Run services (default if none specified)
.PARAMETER Stop
    Stop services
#>
param(
    [switch]$Build,
    [switch]$Run,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$composeFile = "docker-compose.docdb.yml"
if (-not (Test-Path $composeFile)) {
    Write-Host "Compose file not found: $composeFile"
    exit 1
}

if (-not $Build -and -not $Run -and -not $Stop) {
    $Run = $true
}

# ensure network
$networkExists = docker network ls --format "{{.Name}}" | Select-String -Pattern "^codex-network$" -Quiet
if (-not $networkExists) {
    docker network create codex-network | Out-Null
}

if ($Build) {
    docker-compose -f $composeFile build
    if (-not $Run) { exit 0 }
}

if ($Stop) {
    docker-compose -f $composeFile down
    if (-not $Run) { exit 0 }
}

if ($Run) {
    docker-compose -f $composeFile up -d
}
