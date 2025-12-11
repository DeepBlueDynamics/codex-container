<#
.SYNOPSIS
    Build/run/stop mcphost service container (standardized switches).

.PARAMETER Build
    Rebuild the image.

.PARAMETER Run
    Run the container (default if no action given).

.PARAMETER Stop
    Stop/remove the container.

.PARAMETER Tag
    Docker image tag (default: gnosis/mcphost:dev).

.PARAMETER Config
    Path to mcphost config (default: scripts/mcphost_config.yml).

.PARAMETER Name
    Container name (default: gnosis-mcphost).
#>
param(
    [switch]$Build,
    [switch]$Run,
    [switch]$Stop,
    [string]$Tag = "gnosis/mcphost:dev",
    [string]$Config = "scripts/mcphost_config.yml",
    [string]$Name = "gnosis-mcphost"
)

$ErrorActionPreference = "Stop"

# default action: Run if none specified
if (-not $Build -and -not $Run -and -not $Stop) {
    $Run = $true
}

if ($Build) {
    docker build -f Dockerfile.mcphost -t $Tag `
      --build-arg MCPSRC=github.com/mark3labs/mcphost `
      --build-arg GO_VERSION=1.24 `
      --no-cache `
      .
    if (-not $Run) { exit 0 }
}

if ($Stop) {
    docker rm -f $Name 2>$null | Out-Null
    if (-not $Run) { exit 0 }
}

if ($Run) {
    if (-not (Test-Path $Config)) {
        Write-Host "Config file not found: $Config"
        exit 1
    }
    # ensure network
    $networkExists = docker network ls --format "{{.Name}}" | Select-String -Pattern "^codex-network$" -Quiet
    if (-not $networkExists) {
        docker network create codex-network | Out-Null
    }
    $cfgPath = Resolve-Path $Config
    docker rm -f $Name 2>$null | Out-Null
    docker run -d `
        --name $Name `
        --network codex-network `
        -v "${cfgPath}:/mcphost/config.yml:ro" `
        $Tag | Out-Null
}
