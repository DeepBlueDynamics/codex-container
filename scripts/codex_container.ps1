<#
.SYNOPSIS
    Codex container helper - run OpenAI Codex CLI in Docker

.DESCRIPTION
    Launches Codex inside a reproducible Docker container with persistent home,
    workspace mounting, session management, and MCP server support.

.PARAMETER Install
    Build Docker image and install runner on PATH

.PARAMETER Login
    Authenticate with Codex (auto-triggered when needed)

.PARAMETER Run
    Start interactive Codex session (default action)

.PARAMETER Exec
    Non-interactive execution. Pass prompt as string or array.
    Example: -Exec "list python files"

.PARAMETER Shell
    Open bash shell inside container

.PARAMETER Serve
    Start HTTP gateway on port 4000 (or -GatewayPort)

.PARAMETER Monitor
    Watch directory for file changes and trigger Codex with MONITOR.md template

.PARAMETER UseWatchdog
    Use Python watchdog for event-driven monitoring (faster, more efficient than default FileSystemWatcher)

.PARAMETER ListSessions
    Show recent sessions with copyable resume commands, then exit

.PARAMETER SessionId
    Resume previous session using full UUID or last 5 characters
    Example: -SessionId b0b57

.PARAMETER Workspace
    Mount different directory (default: current directory)

.PARAMETER CodexHome
    Use different Codex home directory (default: ~/.codex-service)

.PARAMETER Tag
    Docker image tag (default: gnosis/codex-service:dev)

.PARAMETER Json
    Enable legacy JSON output mode

.PARAMETER JsonE
    Enable experimental JSON output mode

.PARAMETER Oss
    Use local Ollama instead of OpenAI

.PARAMETER OssModel
    Specify Ollama model (implies -Oss)

.PARAMETER SkipUpdate
    Don't update Codex CLI from npm

.PARAMETER NoAutoLogin
    Don't automatically trigger login if not authenticated

.EXAMPLE
    codex-container -Install
    Build image and install runner

.EXAMPLE
    codex-container -ListSessions
    Show recent sessions

.EXAMPLE
    codex-container -SessionId b0b57
    Resume session b0b57

.EXAMPLE
    codex-container -Exec "list python files"
    Run non-interactive command

.EXAMPLE
    codex-container -Monitor -WatchPath vhf_monitor
    Monitor directory for changes

.EXAMPLE
    codex-container -Monitor -WatchPath vhf_monitor -UseWatchdog
    Monitor directory using Python watchdog (event-driven, more efficient)

.LINK
    https://github.com/DeepBlueDynamics/codex-container
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [switch]$Install,
    [Alias('Build')]
    [switch]$Rebuild,
    [switch]$Login,
    [switch]$Run,
    [switch]$Serve,
    [switch]$Watch,
    [string]$WatchPath,
    [switch]$Monitor,
    [string]$MonitorPrompt = 'MONITOR.md',
    [switch]$UseWatchdog,
    [switch]$NewSession,
    [string[]]$Exec,
    [switch]$Shell,
    [switch]$Push,
    [string]$Tag = 'gnosis/codex-service:dev',
    [string]$Workspace,
    [string]$CodexHome,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$CodexArgs,
    [switch]$SkipUpdate,
    [switch]$NoAutoLogin,
    [switch]$Json,
    [switch]$JsonE,
    [switch]$Oss,
    [string]$OssModel,
    [int]$GatewayPort,
    [string]$GatewayHost,
    [int]$GatewayTimeoutMs,
    [string]$GatewayDefaultModel,
    [string[]]$GatewayExtraArgs,
    [string]$TranscriptionServiceUrl = 'http://host.docker.internal:8765',
    [string]$SessionId,
    [switch]$ListSessions
)

$ErrorActionPreference = 'Stop'

if ($OssModel) {
    $Oss = $true
}

function Resolve-WorkspacePath {
    param(
        [string]$Workspace,
        [string]$CodexRoot,
        [System.Management.Automation.PathInfo]$CurrentLocation
    )

    if ($Workspace) {
        if ([System.IO.Path]::IsPathRooted($Workspace)) {
            try {
                return (Resolve-Path -LiteralPath $Workspace).ProviderPath
            } catch {
                throw "Workspace path '$Workspace' could not be resolved"
            }
        }

        $candidatePaths = @(
            Join-Path $CurrentLocation.ProviderPath $Workspace,
            Join-Path $CodexRoot $Workspace
        )

        foreach ($candidate in $candidatePaths) {
            if (Test-Path $candidate) {
                return (Resolve-Path -LiteralPath $candidate).ProviderPath
            }
        }

        throw "Workspace path '$Workspace' could not be resolved relative to $($CurrentLocation.ProviderPath) or $CodexRoot"
    }

    return $CurrentLocation.ProviderPath
}

function Resolve-CodexHomePath {
    param(
        [string]$Override
    )

    $candidate = $Override

    if (-not $candidate -and $env:CODEX_CONTAINER_HOME) {
        $candidate = $env:CODEX_CONTAINER_HOME
    }

    if (-not $candidate) {
        $userProfile = [Environment]::GetFolderPath('UserProfile')
        if (-not $userProfile) {
            $userProfile = $HOME
        }
        if (-not $userProfile) {
            throw 'Unable to determine a user profile directory for Codex home.'
        }
        $candidate = Join-Path $userProfile '.codex-service'
    }

    try {
        return (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).ProviderPath
    } catch [System.Management.Automation.ItemNotFoundException] {
        return [System.IO.Path]::GetFullPath($candidate)
    }
}

function New-CodexContext {
    param(
        [string]$Tag,
        [string]$Workspace,
        [string]$ScriptRoot,
        [string]$CodexHomeOverride
    )

    $scriptDir = if ($ScriptRoot) { $ScriptRoot } else { throw "ScriptRoot is required" }
    $codexRoot = Resolve-Path (Join-Path $scriptDir '..')
    $currentLocation = Get-Location
    $dockerfilePath = Join-Path $codexRoot 'Dockerfile'

    if (-not (Test-Path $dockerfilePath)) {
        throw "Dockerfile not found at $dockerfilePath. Build artifacts may be missing."
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'docker command not found. Install Docker Desktop or CLI and ensure it is on PATH.'
    }

    $workspacePath = Resolve-WorkspacePath -Workspace $Workspace -CodexRoot $codexRoot -CurrentLocation $currentLocation

    $codexHome = Resolve-CodexHomePath -Override $CodexHomeOverride
    if (-not (Test-Path $codexHome)) {
        New-Item -ItemType Directory -Path $codexHome -Force | Out-Null
    }

    # Create whisper cache directory in codex home
    $whisperCache = Join-Path $codexHome 'whisper-cache'
    if (-not (Test-Path $whisperCache)) {
        New-Item -ItemType Directory -Path $whisperCache -Force | Out-Null
    }

    $runArgs = @(
        'run',
        '--rm',
        '-it',
        '--user', '0:0',
        '--network', 'codex-network',
        '--add-host', 'host.docker.internal:host-gateway',
        '-v', ("${codexHome}:/opt/codex-home"),
        '-v', ("${whisperCache}:/opt/whisper-cache"),
        '-e', 'HOME=/opt/codex-home',
        '-e', 'XDG_CONFIG_HOME=/opt/codex-home',
        '-e', 'HF_HOME=/opt/whisper-cache'
    )

    # Pass ANTHROPIC_API_KEY if set in host environment
    if ($env:ANTHROPIC_API_KEY) {
        Write-Host "  Passing ANTHROPIC_API_KEY to container ($($env:ANTHROPIC_API_KEY.Length) chars)" -ForegroundColor DarkGray
        $runArgs += @('-e', "ANTHROPIC_API_KEY=$($env:ANTHROPIC_API_KEY)")
    } else {
        Write-Host "  ANTHROPIC_API_KEY not set in PowerShell environment" -ForegroundColor DarkGray
    }

    if ($workspacePath) {
        # Docker's --mount parser on Windows prefers forward slashes. Convert drive roots like I:\\ to I:/.
        $normalized = $workspacePath.Replace('\\', '/')
        # Ensure drive letters have trailing slash (handles both I: and I:/ cases)
        if ($normalized -match '^[A-Za-z]:/?$') {
            $normalized = $normalized.TrimEnd('/') + '/'
        }
        $runArgs += @('-v', ("${normalized}:/workspace"), '-w', '/workspace')
    }

    return [PSCustomObject]@{
        Tag = $Tag
        CodexRoot = $codexRoot
        CodexHome = $codexHome
        WorkspacePath = $workspacePath
        CurrentLocation = $currentLocation.ProviderPath
        RunArgs = $runArgs
        NewSession = $false  # Will be set by caller if needed
    }
}

function Invoke-DockerBuild {
    param(
        $Context,
        [switch]$PushImage
    )

    $dockerfilePath = Join-Path $Context.CodexRoot 'Dockerfile'

    Write-Host 'Checking Docker daemon...' -ForegroundColor DarkGray
    docker info --format '{{.ID}}' 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker daemon not reachable. Start Docker Desktop (or the Docker service) and retry.'
    }

    Write-Host "Building Codex service image" -ForegroundColor Cyan
    Write-Host "  Dockerfile: $dockerfilePath" -ForegroundColor DarkGray
    Write-Host "  Tag:        $($Context.Tag)" -ForegroundColor DarkGray

    $logDir = Join-Path $Context.CodexHome 'logs'
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logFile = Join-Path $logDir "build-$timestamp.log"
    if (-not (Test-Path $logFile)) {
        New-Item -ItemType File -Path $logFile -Force | Out-Null
    }
    Write-Host "  Log file:   $logFile" -ForegroundColor DarkGray

    $buildArgs = @(
        'build',
        '-f', (Resolve-Path $dockerfilePath),
        '-t', $Context.Tag,
        (Resolve-Path $Context.CodexRoot)
    )

    $buildCommand = "docker $($buildArgs -join ' ')"
    Write-Host "[build] $buildCommand" -ForegroundColor DarkGray
    Add-Content -Path $logFile -Value "[build] $buildCommand" -Encoding UTF8

    docker @buildArgs 2>&1 | Tee-Object -FilePath $logFile -Append
    $buildExitCode = $LASTEXITCODE

    if ($buildExitCode -ne 0) {
        throw "docker build failed with exit code $buildExitCode. See $logFile for details."
    }

    if ($PushImage) {
        Write-Host "Pushing image $($Context.Tag)" -ForegroundColor Cyan
        $pushCommand = "docker push $($Context.Tag)"
        Write-Host "[build] $pushCommand" -ForegroundColor DarkGray
        Add-Content -Path $logFile -Value "[build] $pushCommand" -Encoding UTF8
        docker push $Context.Tag 2>&1 | Tee-Object -FilePath $logFile -Append
        $pushExitCode = $LASTEXITCODE
        if ($pushExitCode -ne 0) {
            throw "docker push failed with exit code $pushExitCode. See $logFile for details."
        }
    }

    Write-Host 'Build complete.' -ForegroundColor Green
    Write-Host "Build log saved to $logFile" -ForegroundColor DarkGray
}

function Test-DockerImageExists {
    param(
        [string]$Tag
    )

    try {
        $null = docker image inspect $Tag 2>$null
        return $true
    } catch {
        return $false
    }
}

function Ensure-DockerImage {
    param(
        [string]$Tag
    )

    if (-not (Test-DockerImageExists -Tag $Tag)) {
        Write-Host "Docker image '$Tag' not found locally." -ForegroundColor Yellow
        Write-Host "Run .\\scripts\\codex_container.ps1 -Install to build it first." -ForegroundColor Yellow
        return $false
    }

    return $true
}

function New-DockerRunArgs {
    param(
        $Context,
        [switch]$ExposeLoginPort,
        [string[]]$AdditionalArgs,
        [string[]]$AdditionalEnv
    )

    $args = @()
    $args += $Context.RunArgs
    if ($ExposeLoginPort) {
        $args += @('-p', '1455:1455')
    }
    if ($Oss) {
        $args += @(
            '-e', 'OLLAMA_HOST=http://host.docker.internal:11434',
            '-e', 'OSS_SERVER_URL=http://host.docker.internal:11434',
            '-e', 'ENABLE_OSS_BRIDGE=1'
        )
    }
    if ($TranscriptionServiceUrl) {
        $args += @('-e', "TRANSCRIPTION_SERVICE_URL=$TranscriptionServiceUrl")
    }
    if ($AdditionalEnv) {
        foreach ($envPair in $AdditionalEnv) {
            $args += @('-e', $envPair)
        }
    }
    if ($AdditionalArgs) {
        $args += $AdditionalArgs
    }
    $args += $Context.Tag
    $args += '/usr/local/bin/codex_entry.sh'
    return $args
}

function Invoke-CodexContainer {
    param(
        $Context,
        [string[]]$CommandArgs,
        [switch]$ExposeLoginPort,
        [string[]]$AdditionalArgs,
        [string[]]$AdditionalEnv
    )

    $runArgs = New-DockerRunArgs -Context $Context -ExposeLoginPort:$ExposeLoginPort -AdditionalArgs $AdditionalArgs -AdditionalEnv $AdditionalEnv
    if ($CommandArgs) {
        $runArgs += $CommandArgs
    }

    Write-Host "DEBUG Invoke-CodexContainer: runArgs count = $($runArgs.Count)" -ForegroundColor Magenta
    $codexStartIdx = $runArgs.IndexOf('codex')
    if ($codexStartIdx -ge 0) {
        Write-Host "DEBUG: codex command starts at index $codexStartIdx" -ForegroundColor Magenta
        for ($i = $codexStartIdx; $i -lt [Math]::Min($codexStartIdx + 5, $runArgs.Count); $i++) {
            Write-Host "DEBUG: runArgs[$i] = '$($runArgs[$i])'" -ForegroundColor Magenta
        }
    }

    if ($env:CODEX_CONTAINER_TRACE) {
        Write-Host "docker $($runArgs -join ' ')" -ForegroundColor DarkGray
    }

    docker @runArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "docker run exited with code $exitCode"
    }
}

function ConvertTo-ShellScript {
    param(
        [string[]]$Commands
    )

    return ($Commands -join '; ')
}

function Install-RunnerOnPath {
    param(
        $Context
    )

    $binDir = Join-Path $Context.CodexHome 'bin'
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null

    # Direct invocation - no wrapper needed when using -Command
    $repoScript = Join-Path $Context.CodexRoot 'scripts/codex_container.ps1'
    $escapedRepoScript = $repoScript.Replace("'", "''")

    $shimPath = Join-Path $binDir 'codex-container.cmd'
    $shimContent = @"
@echo off
PowerShell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "& '$escapedRepoScript' @args"
"@
    Set-Content -Path $shimPath -Value $shimContent -Encoding ASCII

    $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
    $pathEntries = @()
    if ($userPath) {
        $pathEntries = $userPath -split ';'
    }
    $hasEntry = $false
    foreach ($entry in $pathEntries) {
        if ($entry.TrimEnd('\') -ieq $binDir.TrimEnd('\')) {
            $hasEntry = $true
            break
        }
    }
    if (-not $hasEntry) {
        $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
        [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
        Write-Host "Added $binDir to user PATH" -ForegroundColor DarkGray
    }
    if (-not (($env:PATH -split ';') | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') })) {
        $env:PATH = if ($env:PATH) { "$env:PATH;$binDir" } else { $binDir }
    }

    Write-Host "Launcher installed to $shimPath" -ForegroundColor DarkGray
    Write-Host "Invokes: $repoScript" -ForegroundColor DarkGray
}

$script:CodexUpdateCompleted = $false

function Ensure-CodexCli {
    param(
        $Context,
        [switch]$Force,
        [switch]$Silent
    )

    if ($SkipUpdate -and -not $Force) {
        return
    }

    if ($script:CodexUpdateCompleted -and -not $Force) {
        return
    }

$updateScript = "set -euo pipefail; export PATH=`"`$PATH:/usr/local/share/npm-global/bin`"; echo `"Ensuring Codex CLI is up to date...`"; if npm install -g @openai/codex@latest --prefer-online >/tmp/codex-install.log 2>&1; then echo `"Codex CLI updated.`"; else echo `"Failed to install Codex CLI; see /tmp/codex-install.log.`"; cat /tmp/codex-install.log; exit 1; fi; cat /tmp/codex-install.log"

    if ($Silent) {
        Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash', '-c', $updateScript) | Out-Null
    } else {
        Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash', '-c', $updateScript)
    }
    $script:CodexUpdateCompleted = $true
}

function Invoke-CodexLogin {
    param(
        $Context
    )

    Ensure-CodexCli -Context $Context

    $loginHostPath = Join-Path $Context.CodexRoot 'scripts/codex_login.sh'
    if (-not (Test-Path $loginHostPath)) {
        throw "Expected login helper script missing at $loginHostPath."
    }

    Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash', '-c', 'sed -i "s/\r$//" /workspace/scripts/codex_login.sh && /bin/bash /workspace/scripts/codex_login.sh') -ExposeLoginPort
}

function Invoke-CodexRun {
    param(
        $Context,
        [string[]]$Arguments,
        [switch]$Silent
    )

    Ensure-CodexCli -Context $Context -Silent:$Silent

    $cmd = @('codex')
    if ($Oss -and -not ($Arguments -contains '--oss')) {
        $cmd += '--oss'
    }
    if ($OssModel) {
        $hasOssModel = $false
        if ($Arguments) {
            for ($i = 0; $i -lt $Arguments.Count; $i++) {
                $arg = $Arguments[$i]
                if ($arg -eq '--model' -or $arg -like '--model=*') {
                    $hasOssModel = $true
                    break
                }
            }
        }
        if (-not $hasOssModel) {
            $cmd += @('--model', $OssModel)
        }
    }
    if ($Arguments) {
        $cmd += $Arguments
    }

    Invoke-CodexContainer -Context $Context -CommandArgs $cmd
}

function Invoke-CodexExec {
    param(
        $Context,
        [string[]]$Arguments
    )

    Write-Host "DEBUG Invoke-CodexExec: Received $($Arguments.Count) arguments" -ForegroundColor Cyan
    for ($i = 0; $i -lt [Math]::Min($Arguments.Count, 3); $i++) {
        Write-Host "DEBUG Invoke-CodexExec: Arguments[$i] = '$($Arguments[$i].Substring(0, [Math]::Min(50, $Arguments[$i].Length)))...'" -ForegroundColor Cyan
    }

    if (-not $Arguments) {
        throw 'Exec requires at least one argument to forward to codex.'
    }
    $cmdArguments = if ($Arguments[0] -eq 'exec') {
        $Arguments
    } else {
        @('exec') + $Arguments
    }

    $injectedFlags = @()
    if (-not ($cmdArguments -contains '--skip-git-repo-check')) {
        $injectedFlags += '--skip-git-repo-check'
    }

    if ($JsonE -and -not ($cmdArguments -contains '--experimental-json')) {
        $injectedFlags += '--experimental-json'
    } elseif ($Json -and -not ($cmdArguments -contains '--json')) {
        $injectedFlags += '--json'
    }

    if ($Oss -and -not ($cmdArguments -contains '--oss')) {
        $injectedFlags += '--oss'
    }

    if ($OssModel) {
        $hasOssModel = $false
        for ($i = 0; $i -lt $cmdArguments.Length; $i++) {
            $arg = $cmdArguments[$i]
            if ($arg -eq '--model' -or $arg -like '--model=*') {
                $hasOssModel = $true
                break
            }
        }
        if (-not $hasOssModel) {
            $injectedFlags += '--model'
            $injectedFlags += $OssModel
        }
    }

    if ($injectedFlags.Count -gt 0) {
        $first = $cmdArguments[0]
        $rest = @()
        if ($cmdArguments.Length -gt 1) {
            $rest = $cmdArguments[1..($cmdArguments.Length - 1)]
        }
        $cmdArguments = @($first) + $injectedFlags + $rest
    }

    Invoke-CodexRun -Context $Context -Arguments $cmdArguments -Silent:($Json -or $JsonE)
}

function Invoke-CodexShell {
    param(
        $Context
    )

    Ensure-CodexCli -Context $Context
    Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash')
}

function Invoke-CodexServe {
    param(
        $Context,
        [int]$Port,
        [string]$BindHost,
        [int]$TimeoutMs,
        [string]$DefaultModel,
        [string[]]$ExtraArgs
    )

    Ensure-CodexCli -Context $Context

    if (-not $Port) {
        $Port = 4000
    }
    if (-not $BindHost) {
        $BindHost = '127.0.0.1'
    }

    $publish = if ($BindHost) { "${BindHost}:${Port}:${Port}" } else { "${Port}:${Port}" }

    $envVars = @("CODEX_GATEWAY_PORT=$Port", 'CODEX_GATEWAY_BIND=0.0.0.0')
    if ($TimeoutMs) {
        $envVars += "CODEX_GATEWAY_TIMEOUT_MS=$TimeoutMs"
    }
    if ($DefaultModel) {
        $envVars += "CODEX_GATEWAY_DEFAULT_MODEL=$DefaultModel"
    }
    if ($ExtraArgs) {
        $joined = [string]::Join(' ', $ExtraArgs)
        if ($joined.Trim().Length -gt 0) {
            $envVars += "CODEX_GATEWAY_EXTRA_ARGS=$joined"
        }
    }

    Invoke-CodexContainer -Context $Context -CommandArgs @('node', '/usr/local/bin/codex_gateway.js') -AdditionalArgs @('-p', $publish) -AdditionalEnv $envVars
}

function Invoke-CodexMonitor {
    param(
        $Context,
        [string]$WatchPath,
        [string]$PromptFile,
        [switch]$JsonOutput,
        [string[]]$CodexArgs,
        [switch]$UseWatchdog
    )

    Write-Host "DEBUG: Invoke-CodexMonitor called" -ForegroundColor Yellow
    Write-Host "DEBUG: WatchPath = '$WatchPath'" -ForegroundColor Yellow
    Write-Host "DEBUG: PromptFile = '$PromptFile'" -ForegroundColor Yellow
    Write-Host "DEBUG: UseWatchdog = $UseWatchdog" -ForegroundColor Yellow

    if (-not $WatchPath) {
        $WatchPath = $Context.WorkspacePath
    }

    if (-not (Test-Path $WatchPath)) {
        throw "Monitor watch path '$WatchPath' could not be resolved."
    }

    $resolvedWatch = (Resolve-Path -LiteralPath $WatchPath).ProviderPath

    # Auto-detect prompt file if not specified
    if (-not $PromptFile) {
        # First check for MONITOR.md
        $defaultPrompt = Join-Path $resolvedWatch 'MONITOR.md'
        if (Test-Path $defaultPrompt) {
            $PromptFile = 'MONITOR.md'
        } else {
            # Look for MONITOR_*.md pattern
            $monitorFiles = Get-ChildItem -Path $resolvedWatch -Filter 'MONITOR_*.md' -File -ErrorAction SilentlyContinue
            if ($monitorFiles -and $monitorFiles.Count -gt 0) {
                $PromptFile = $monitorFiles[0].Name
                Write-Host "Auto-detected prompt file: $PromptFile" -ForegroundColor Cyan
            } else {
                $PromptFile = 'MONITOR.md'  # Fallback, will error later if missing
            }
        }
    }
    $promptPath = Join-Path $resolvedWatch $PromptFile

    # Use Python watchdog monitor running inside container
    if ($UseWatchdog) {
        Write-Host "🐍 Using Python watchdog monitor (event-driven, running in container)" -ForegroundColor Cyan

        # Calculate relative path from workspace to watch directory
        $watchRelative = $resolvedWatch.Substring($Context.WorkspacePath.Length).TrimStart('\', '/')
        $containerWatchPath = if ($watchRelative) { "/workspace/$($watchRelative.Replace('\', '/'))" } else { "/workspace" }

        Write-Host "   Watch path (host): $resolvedWatch" -ForegroundColor DarkGray
        Write-Host "   Watch path (container): $containerWatchPath" -ForegroundColor DarkGray
        Write-Host "   Prompt file: $PromptFile" -ForegroundColor DarkGray

        # Build monitor command to run inside container
        $monitorCmd = @(
            "python3", "/opt/scripts/monitor.py",
            "--watch-path", $containerWatchPath,
            "--workspace", "/workspace",
            "--codex-script", "codex",
            "--monitor-prompt-file", $PromptFile
        )

        if ($Context.NewSession) {
            $monitorCmd += "--new-session"
        }

        if ($JsonOutput) {
            $jsonMode = if ($Context.JsonE) { "experimental" } else { "legacy" }
            $monitorCmd += @("--json-mode", $jsonMode)
        }

        # Launch container with monitor running inside
        Write-Host "Starting monitor in container..." -ForegroundColor Cyan
        Invoke-CodexContainer -Context $Context -CommandArgs $monitorCmd
        return
    }

    # Fall back to PowerShell FileSystemWatcher monitor
    Write-Host "📁 Using PowerShell FileSystemWatcher monitor (polling-based)" -ForegroundColor Cyan

    $logPath = Join-Path $resolvedWatch 'codex-monitor.log'
    $sessionStatePath = Join-Path $resolvedWatch '.codex-monitor-session'

    function Write-MonitorLog {
        param([string]$Message)
        $timestamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        $line = "[$timestamp] $Message"
        Add-Content -LiteralPath $logPath -Value $line
    }

    function Get-MonitorSession {
        if (Test-Path $sessionStatePath) {
            try {
                $sessionId = Get-Content $sessionStatePath -Raw -ErrorAction SilentlyContinue
                return $sessionId.Trim()
            } catch {
                return $null
            }
        }
        return $null
    }

    function Set-MonitorSession {
        param([string]$SessionId)
        if ($SessionId) {
            Set-Content -Path $sessionStatePath -Value $SessionId -NoNewline
        }
    }

    function Get-MonitorRelativePath {
        param([string]$BasePath, [string]$TargetPath)
        if (-not $TargetPath) { return '' }
        try {
            $baseWithSlash = if ($BasePath.TrimEnd() -match '[\\/]$') { $BasePath } else { $BasePath + [System.IO.Path]::DirectorySeparatorChar }
            $baseUri = New-Object System.Uri($baseWithSlash)
            $targetUri = New-Object System.Uri($TargetPath)
            if ($baseUri.Scheme -ne $targetUri.Scheme) {
                return $TargetPath
            }
            $relativeUri = $baseUri.MakeRelativeUri($targetUri).ToString()
            $relative = [System.Uri]::UnescapeDataString($relativeUri).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
            if ([string]::IsNullOrEmpty($relative)) { return '.' }
            return $relative
        } catch {
            return $TargetPath
        }
    }

    function Format-MonitorPrompt {
        param([string]$Template, [hashtable]$Values)
        $result = $Template
        foreach ($key in $Values.Keys) {
            $token = "{{${key}}}"
            $value = $Values[$key]
            if ($null -eq $value) { $value = '' }
            $result = $result.Replace($token, $value)
        }
        return $result
    }

    function Get-LatestSession {
        param($Context)
        $sessionsDir = Join-Path $Context.CodexHome ".codex/sessions"
        if (-not (Test-Path $sessionsDir)) {
            return $null
        }

        $allSessions = Get-ChildItem -Path $sessionsDir -Recurse -Filter "rollout-*.jsonl" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($allSessions -and $allSessions.Name -match 'rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$') {
            return $Matches[1]
        }

        return $null
    }

    Write-Host "Monitoring $resolvedWatch" -ForegroundColor Cyan
    Write-Host "Prompt file: $promptPath" -ForegroundColor DarkGray
    Write-Host "Log file:    $logPath" -ForegroundColor DarkGray
    Write-Host 'Press Ctrl+C to stop.' -ForegroundColor DarkGray

    # Check for existing monitor session (unless -NewSession specified)
    $monitorSessionId = $null
    if (-not $Context.NewSession) {
        $monitorSessionId = Get-MonitorSession
    }

    if ($monitorSessionId) {
        Write-Host "Monitor resuming session: $monitorSessionId" -ForegroundColor Cyan
        Write-MonitorLog "Resuming session: $monitorSessionId"
    } else {
        if ($Context.NewSession) {
            Write-Host "Monitor starting fresh session (forced by -NewSession)" -ForegroundColor Cyan
            Write-MonitorLog "Starting fresh session (forced by -NewSession)"
            # Clear any existing session file
            if (Test-Path $sessionStatePath) {
                Remove-Item $sessionStatePath -Force
            }
        } else {
            Write-Host "Monitor starting new session" -ForegroundColor Cyan
            Write-MonitorLog "Starting new session"
        }
    }

    Write-MonitorLog "Started monitoring $resolvedWatch"

    $ignored = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $ignored.Add([System.IO.Path]::GetFileName($promptPath)) | Out-Null
    $ignored.Add('codex-monitor.log') | Out-Null

    $fsw = New-Object System.IO.FileSystemWatcher $resolvedWatch
    $fsw.IncludeSubdirectories = $false
    $fsw.EnableRaisingEvents = $true
    $fsw.NotifyFilter = [System.IO.NotifyFilters]::FileName -bor [System.IO.NotifyFilters]::LastWrite

    $sourceIds = @('CodexMonitorChanged','CodexMonitorCreated','CodexMonitorRenamed')
    Register-ObjectEvent -InputObject $fsw -EventName Changed -SourceIdentifier $sourceIds[0] | Out-Null
    Register-ObjectEvent -InputObject $fsw -EventName Created -SourceIdentifier $sourceIds[1] | Out-Null
    Register-ObjectEvent -InputObject $fsw -EventName Renamed -SourceIdentifier $sourceIds[2] | Out-Null

    $lastProcessed = @{}
    $lastWriteStamp = @{}

    try {
        while ($true) {
            $event = Wait-Event -SourceIdentifier * -Timeout 1
            if (-not $event) { continue }

            if (-not ($sourceIds -contains $event.SourceIdentifier)) {
                Remove-Event -EventIdentifier $event.EventIdentifier
                continue
            }

            try {
                $fullPath = $event.SourceEventArgs.FullPath
            } catch {
                Remove-Event -EventIdentifier $event.EventIdentifier
                continue
            }

            Remove-Event -EventIdentifier $event.EventIdentifier

            if (-not $fullPath) { continue }
            if (-not (Test-Path $fullPath)) {
                continue
            }

            $name = [System.IO.Path]::GetFileName($fullPath)
            if ($ignored.Contains($name)) {
                continue
            }

            try {
                $attributes = [System.IO.File]::GetAttributes($fullPath)
                if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                    continue
                }
            } catch {}

            $now = Get-Date
            $lastWrite = $null
            try {
                $lastWrite = [System.IO.File]::GetLastWriteTimeUtc($fullPath)
            } catch {}

            if ($lastProcessed.ContainsKey($fullPath)) {
                $delta = $now - $lastProcessed[$fullPath]
                if ($delta.TotalSeconds -lt 1) {
                    continue
                }
            }

            if ($lastWrite -ne $null) {
                if ($lastWriteStamp.ContainsKey($fullPath) -and $lastWriteStamp[$fullPath] -eq $lastWrite) {
                    continue
                }
                $lastWriteStamp[$fullPath] = $lastWrite
            }

            $lastProcessed[$fullPath] = $now

            # Always read full prompt template - agent needs full instructions every time
            if (-not (Test-Path $promptPath)) {
                $msg = "Prompt file missing; skipping event for ${fullPath}"
                Write-Host $msg -ForegroundColor Yellow
                Write-MonitorLog $msg
                continue
            }

            try {
                $promptText = Get-Content -LiteralPath $promptPath -Raw -ErrorAction Stop
            } catch {
                $msg = "Failed reading prompt file ${promptPath}: $($_.Exception.Message)"
                Write-Host $msg -ForegroundColor Red
                Write-MonitorLog $msg
                continue
            }

            $changeType = $event.SourceEventArgs.ChangeType.ToString()
            $oldFullPath = $null
            if ($event.SourceEventArgs -is [System.IO.RenamedEventArgs]) {
                $oldFullPath = $event.SourceEventArgs.OldFullPath
            }

            # Calculate relative path from the WATCH directory (for display)
            $relativePath = Get-MonitorRelativePath -BasePath $resolvedWatch -TargetPath $fullPath
            if ([string]::IsNullOrEmpty($relativePath)) { $relativePath = '.' }
            $directoryRelative = [System.IO.Path]::GetDirectoryName($relativePath)
            if ([string]::IsNullOrEmpty($directoryRelative)) { $directoryRelative = '.' }

            # Calculate relative path from the WORKSPACE root (for container paths)
            $relativeFromWorkspace = Get-MonitorRelativePath -BasePath $Context.WorkspacePath -TargetPath $fullPath
            if ([string]::IsNullOrEmpty($relativeFromWorkspace)) { $relativeFromWorkspace = '.' }
            
            $relativeForContainer = $relativeFromWorkspace.Replace([System.IO.Path]::DirectorySeparatorChar, '/')
            if ($relativeForContainer -eq '.') {
                $relativeForContainer = ''
            }
            $containerPath = if ($relativeForContainer) { "/workspace/$relativeForContainer" } else { '/workspace' }
            $containerDir = if ($relativeForContainer) {
                $dirPart = [System.IO.Path]::GetDirectoryName($relativeFromWorkspace)
                if ([string]::IsNullOrEmpty($dirPart)) { '/workspace' } else { "/workspace/" + ($dirPart.Replace([System.IO.Path]::DirectorySeparatorChar, '/')) }
            } else { '/workspace' }

            $oldRelativePath = if ($oldFullPath) { Get-MonitorRelativePath -BasePath $resolvedWatch -TargetPath $oldFullPath } else { '' }
            $oldDirectoryRelative = if ($oldRelativePath) { [System.IO.Path]::GetDirectoryName($oldRelativePath) } else { '' }
            if ([string]::IsNullOrEmpty($oldDirectoryRelative) -and $oldRelativePath) { $oldDirectoryRelative = '.' }

            $oldRelativeForContainer = $oldRelativePath.Replace([System.IO.Path]::DirectorySeparatorChar, '/')
            if ($oldRelativeForContainer -eq '.') { $oldRelativeForContainer = '' }
            $oldContainerPath = if ($oldRelativeForContainer) { "/workspace/$oldRelativeForContainer" } else { '' }
            $oldContainerDir = if ($oldRelativeForContainer) {
                $oldDirPart = [System.IO.Path]::GetDirectoryName($oldRelativePath)
                if ([string]::IsNullOrEmpty($oldDirPart)) { '/workspace' } else { "/workspace/" + ($oldDirPart.Replace([System.IO.Path]::DirectorySeparatorChar, '/')) }
            } else { '' }

            $values = @{
                'file' = [System.IO.Path]::GetFileName($fullPath)
                'filename' = [System.IO.Path]::GetFileName($fullPath)
                'directory' = $directoryRelative
                'dir' = $directoryRelative
                'full_path' = $fullPath
                'relative_path' = $relativePath
                'container_path' = $containerPath
                'container_dir' = $containerDir
                'extension' = [System.IO.Path]::GetExtension($fullPath)
                'action' = $changeType
                'timestamp' = (Get-Date).ToString('o')
                'watch_root' = $resolvedWatch
                'old_full_path' = $oldFullPath
                'old_relative_path' = $oldRelativePath
                'old_container_path' = $oldContainerPath
                'old_container_dir' = $oldContainerDir
                'old_file' = if ($oldFullPath) { [System.IO.Path]::GetFileName($oldFullPath) } else { '' }
                'old_filename' = if ($oldFullPath) { [System.IO.Path]::GetFileName($oldFullPath) } else { '' }
                'old_directory' = $oldDirectoryRelative
                'old_dir' = $oldDirectoryRelative
            }

            # Build payload - ALWAYS send full template with substitution
            # Agent needs the full instructions every time to remember to check for duplicates
            $payload = Format-MonitorPrompt -Template $promptText.TrimEnd() -Values $values

            # If monitoring a subdirectory, fix paths for correct container mapping
            if ($resolvedWatch -ne $Context.WorkspacePath) {
                # Calculate the relative path from workspace to watch directory
                $watchRelative = $resolvedWatch.Substring($Context.WorkspacePath.Length).TrimStart('\', '/')
                $watchRelativeForContainer = $watchRelative.Replace('\', '/')

                # Replace absolute Windows paths with correct container paths
                # Files in the watched subdir need the subdirectory in their container path
                $payload = $payload -replace [regex]::Escape($resolvedWatch.Replace('\', '/')), "/workspace/$watchRelativeForContainer"
                $payload = $payload -replace [regex]::Escape($resolvedWatch), "/workspace/$watchRelativeForContainer"
            }

            # Build command arguments array
            # IMPORTANT: Ensure payload is added as a single string element, not word-split
            $cmdArgs = @()
            # Add session resume if we have a persisted session
            if ($monitorSessionId) {
                $cmdArgs += 'resume'
                $cmdArgs += $monitorSessionId
            }
            if ($CodexArgs) {
                $cmdArgs += $CodexArgs
            }
            # Add the prompt payload as a single element (cast to ensure it's treated as one string)
            $cmdArgs += [string]$payload

            $logMessage = "Dispatching Codex run for ${fullPath}"
            Write-Host $logMessage -ForegroundColor DarkGray
            Write-MonitorLog $logMessage

            # Debug logging
            Write-Host "DEBUG: cmdArgs count = $($cmdArgs.Count)" -ForegroundColor Yellow
            Write-Host "DEBUG: cmdArgs[0] length = $($cmdArgs[0].Length)" -ForegroundColor Yellow
            if ($cmdArgs.Count -gt 1) {
                Write-Host "DEBUG: cmdArgs has multiple elements!" -ForegroundColor Red
                for ($i = 0; $i -lt [Math]::Min($cmdArgs.Count, 5); $i++) {
                    Write-Host "DEBUG: cmdArgs[$i] = '$($cmdArgs[$i])'" -ForegroundColor Yellow
                }
            } else {
                Write-Host "DEBUG: cmdArgs[0] first 100 chars = $($cmdArgs[0].Substring(0, [Math]::Min(100, $cmdArgs[0].Length)))" -ForegroundColor Yellow
            }

            try {
                Invoke-CodexExec -Context $Context -Arguments $cmdArgs

                # Capture and persist session ID for continuity
                if (-not $monitorSessionId) {
                    $latestSession = Get-LatestSession -Context $Context
                    if ($latestSession) {
                        $monitorSessionId = $latestSession
                        Set-MonitorSession -SessionId $monitorSessionId
                        Write-Host "Monitor persisted session: $monitorSessionId" -ForegroundColor Cyan
                        Write-MonitorLog "Persisted session: $monitorSessionId"
                    }
                }

                # Only mark as processed after successful completion
                $lastProcessed[$fullPath] = $now
                if ($lastWrite -ne $null) {
                    $lastWriteStamp[$fullPath] = $lastWrite
                }
                Write-MonitorLog "Codex run completed for ${fullPath}"
            } catch {
                $err = "Codex run failed for ${fullPath}: $($_.Exception.Message)"
                Write-Host $err -ForegroundColor Red
                Write-MonitorLog $err
                # Don't update lastProcessed on failure - allow retry
            }
        }
    } finally {
        foreach ($id in $sourceIds) {
            Unregister-Event -SourceIdentifier $id -ErrorAction SilentlyContinue
            Remove-Event -SourceIdentifier $id -ErrorAction SilentlyContinue
        }
        $fsw.Dispose()
        Write-MonitorLog "Stopped monitoring $resolvedWatch"
    }
}

function Test-CodexAuthenticated {
    param(
        $Context
    )

    $authPath = Join-Path $Context.CodexHome '.codex/auth.json'
    if (-not (Test-Path $authPath)) {
        return $false
    }

    try {
        $content = Get-Content -LiteralPath $authPath -Raw -ErrorAction Stop
        return ($content.Trim().Length -gt 0)
    } catch {
        return $false
    }
}

function Show-RecentSessions {
    param(
        $Context,
        [int]$Limit = 5
    )

    $sessionsDir = Join-Path $Context.CodexHome ".codex/sessions"

    if (-not (Test-Path $sessionsDir)) {
        return
    }

    # Find all rollout-*.jsonl files (sessions are stored as: sessions/2025/10/20/rollout-*.jsonl)
    $sessionFiles = Get-ChildItem -Path $sessionsDir -Recurse -Filter "rollout-*.jsonl" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Limit

    if ($sessionFiles.Count -eq 0) {
        return
    }

    Write-Host ""
    Write-Host "Recent Codex sessions:" -ForegroundColor Cyan
    Write-Host ""

    # Platform-appropriate command base
    $cmdBase = if ($IsWindows -or $env:OS -match "Windows") {
        "codex-container"
    } else {
        "./codex_container.sh"
    }

    foreach ($file in $sessionFiles) {
        # Extract session ID from filename: rollout-2025-10-20T14-58-30-019a0221-064c-7cd3-aad2-dffde6bbffba.jsonl
        if ($file.Name -match 'rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$') {
            $sessionId = $matches[1]
        } else {
            continue
        }

        # Get short ID (last 5 chars)
        $shortId = $sessionId.Substring($sessionId.Length - 5)

        $lastModified = $file.LastWriteTime
        $age = (Get-Date) - $lastModified

        # Format age nicely
        $ageStr = if ($age.TotalHours -lt 1) {
            "{0} min ago" -f [math]::Floor($age.TotalMinutes)
        } elseif ($age.TotalDays -lt 1) {
            "{0}h ago" -f [math]::Floor($age.TotalHours)
        } else {
            "{0}d ago" -f [math]::Floor($age.TotalDays)
        }

        # Try to get first user message from the jsonl file
        $preview = ""
        try {
            $firstLine = Get-Content $file.FullName -First 1 -ErrorAction SilentlyContinue
            if ($firstLine) {
                $json = $firstLine | ConvertFrom-Json -ErrorAction SilentlyContinue
                if ($json.role -eq "user" -and $json.content) {
                    $preview = $json.content
                    if ($preview.Length -gt 70) {
                        $preview = $preview.Substring(0, 67) + "..."
                    }
                }
            }
        } catch {
            # Ignore parse errors
        }

        Write-Host "  [$ageStr]" -ForegroundColor DarkGray -NoNewline
        Write-Host " ...$shortId" -ForegroundColor Yellow
        if ($preview) {
            Write-Host "    $preview" -ForegroundColor Gray
        }
        Write-Host "    $cmdBase -SessionId $shortId" -ForegroundColor Cyan
        Write-Host ""
    }
    Write-Host ""
}

function Ensure-CodexAuthentication {
    param(
        $Context,
        [switch]$Silent
    )

    if (Test-CodexAuthenticated -Context $Context) {
        return
    }

    if ($Silent) {
        throw 'Codex credentials not found. Re-run with -Login to authenticate.'
    }

    if ($NoAutoLogin) {
        throw 'Codex credentials not found. Re-run with -Login to authenticate.'
    }

    Write-Host 'No Codex credentials detected; starting login flow...' -ForegroundColor Yellow
    Invoke-CodexLogin -Context $Context

    if (-not (Test-CodexAuthenticated -Context $Context)) {
        throw 'Codex login did not complete successfully. Please retry with -Login.'
    }
}

$actions = @()
if ($Install) { $actions += 'Install' }
if ($Rebuild) { $actions += 'Install' }  # -Build/-Rebuild is alias for Install
if ($Login) { $actions += 'Login' }
if ($Shell) { $actions += 'Shell' }
if ($Exec) { $actions += 'Exec' }
if ($Run) { $actions += 'Run' }
if ($Serve) { $actions += 'Serve' }
if ($Monitor) { $actions += 'Monitor' }
if ($ListSessions) { $actions += 'ListSessions' }

if (-not $actions) {
    $actions = @('Run')
}

if ($actions.Count -gt 1) {
    throw "Specify only one primary action (choose one of -Install, -Build, -Login, -Run, -Exec, -Shell, -Serve, -Monitor, -ListSessions)."
}

$action = $actions[0]

$jsonOutput = $Json -or $JsonE

$jsonFlagsSpecified = @()
if ($Json) { $jsonFlagsSpecified += '-Json' }
if ($JsonE) { $jsonFlagsSpecified += '-JsonE' }
if ($jsonFlagsSpecified.Count -gt 1) {
    throw "Specify only one of $($jsonFlagsSpecified -join ', ')."
}

$context = New-CodexContext -Tag $Tag -Workspace $Workspace -ScriptRoot $PSScriptRoot -CodexHomeOverride $CodexHome

if (-not $jsonOutput) {
    Write-Host "Codex container context" -ForegroundColor Cyan
    Write-Host "  Image:      $Tag" -ForegroundColor DarkGray
    Write-Host "  Codex home: $($context.CodexHome)" -ForegroundColor DarkGray
    Write-Host "  Workspace:  $($context.WorkspacePath)" -ForegroundColor DarkGray
}

if ($action -ne 'Install') {
    if (-not (Ensure-DockerImage -Tag $context.Tag)) {
        return
    }
}

switch ($action) {
    'Install' {
        Invoke-DockerBuild -Context $context -PushImage:$Push
        Ensure-CodexCli -Context $context -Force
        Install-RunnerOnPath -Context $context
    }
    'Login' {
        Invoke-CodexLogin -Context $context
    }
    'Shell' {
        Invoke-CodexShell -Context $context
    }
    'Exec' {
        Ensure-CodexAuthentication -Context $context -Silent:($Json -or $JsonE)
        Invoke-CodexExec -Context $context -Arguments $Exec
    }
    'Serve' {
        Ensure-CodexAuthentication -Context $context
        Invoke-CodexServe -Context $context -Port $GatewayPort -BindHost $GatewayHost -TimeoutMs $GatewayTimeoutMs -DefaultModel $GatewayDefaultModel -ExtraArgs $GatewayExtraArgs
    }
    'Monitor' {
        $context.NewSession = $NewSession
        Ensure-CodexAuthentication -Context $context -Silent:($Json -or $JsonE)
        Invoke-CodexMonitor -Context $context -WatchPath $WatchPath -PromptFile $MonitorPrompt -JsonOutput:($Json -or $JsonE) -CodexArgs $CodexArgs -UseWatchdog:$UseWatchdog
    }
    'ListSessions' {
        Show-RecentSessions -Context $context -Limit 10
    }
    default { # Run
        Ensure-CodexAuthentication -Context $context -Silent:($Json -or $JsonE)

        # Handle SessionId parameter - resolve partial matches
        $resolvedSessionId = $null
        if ($SessionId) {
            $sessionsDir = Join-Path $context.CodexHome ".codex/sessions"
            if (Test-Path $sessionsDir) {
                $allSessions = Get-ChildItem -Path $sessionsDir -Recurse -Filter "rollout-*.jsonl" -File -ErrorAction SilentlyContinue
                $matchedSessions = @()
                foreach ($file in $allSessions) {
                    if ($file.Name -match 'rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$') {
                        $fullId = $Matches[1]
                        if ($fullId -like "*$SessionId") {
                            $matchedSessions += $fullId
                        }
                    }
                }

                if ($matchedSessions.Count -eq 0) {
                    Write-Host "Error: No session found matching '$SessionId'" -ForegroundColor Red
                    return
                } elseif ($matchedSessions.Count -gt 1) {
                    Write-Host "Error: Multiple sessions match '$SessionId':" -ForegroundColor Red
                    foreach ($m in $matchedSessions) {
                        Write-Host "  $m" -ForegroundColor Yellow
                    }
                    return
                } else {
                    $resolvedSessionId = $matchedSessions[0]
                    if (-not ($Json -or $JsonE)) {
                        Write-Host "Resuming session: $resolvedSessionId" -ForegroundColor Cyan
                    }
                }
            }
        }

        if (-not ($Json -or $JsonE) -and -not $SessionId) {
            Show-RecentSessions -Context $context -Limit 5
        }

        # Build arguments - add session ID if provided
        $runArgs = @()
        if ($resolvedSessionId) {
            $runArgs = @('resume', $resolvedSessionId)
        }
        if ($CodexArgs) {
            $runArgs += $CodexArgs
        }

        Invoke-CodexRun -Context $context -Arguments $runArgs -Silent:($Json -or $JsonE)
    }
}
