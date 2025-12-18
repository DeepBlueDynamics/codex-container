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

.PARAMETER OssServerUrl
    Override the OSS endpoint Codex should call when -Oss is set (set this to your hosted GPT-OSS cloud URL to avoid the localhost bridge)

.PARAMETER OllamaHost
    Convenience alias for Ollama host override; defaults to the same value as -OssServerUrl when only one is provided

.PARAMETER CodexModel
    Forward a cloud model ID to Codex without implying -Oss. Useful for providers like gpt-oss:120b-cloud.

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

.LINK
    https://github.com/DeepBlueDynamics/codex-container
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [switch]$Install,
    [Alias('Build')]
    [switch]$Rebuild,
    [switch]$NoCache,
    [switch]$Login,
    [switch]$Run,
    [switch]$Serve,
    [switch]$NewSession,
    [string[]]$Exec,
    [switch]$Shell,
    [switch]$Push,
    [string]$Tag = 'gnosis/codex-service:dev',
    [string]$Workspace,
    [string]$CodexHome,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$CodexArgs,
    [string]$OssServerUrl,
    [string]$OllamaHost,
    [string]$CodexModel,
    [switch]$SkipUpdate,
    [switch]$NoAutoLogin,
    [switch]$Json,
    [switch]$JsonE,
    [switch]$Oss,
    [string]$OssModel,
    [switch]$Speaker,
    [int]$SpeakerPort = 8777,
    [switch]$Danger,
    [int]$GatewayPort,
    [string]$GatewayHost,
    [int]$GatewayTimeoutMs,
    [string]$GatewayDefaultModel,
    [string[]]$GatewayExtraArgs,
    [string]$GatewaySessionDirs,
    [string]$GatewaySecureDir,
    [string]$GatewaySecureToken,
    [int]$GatewayLogLevel,
    [Alias('WatchPaths')]
    [string]$GatewayWatchPaths,
    [Alias('WatchPattern')]
    [string]$GatewayWatchPattern,
    [Alias('WatchPromptFile')]
    [string]$GatewayWatchPromptFile,
    [Alias('WatchDebounceMs')]
    [int]$GatewayWatchDebounceMs,
    [string]$TranscriptionServiceUrl = 'http://host.docker.internal:8765',
    [string]$SessionWebhookUrl,
    [string]$SessionWebhookAuthBearer,
    [string]$SessionWebhookHeadersJson,
    [string]$SessionId,
    [switch]$ListSessions,
    [int]$RecentLimit = 20,
    [int]$SinceDays = 3,
    [switch]$Privileged
)

$ErrorActionPreference = 'Stop'

if (-not $PSBoundParameters.ContainsKey('Danger')) {
    $Danger = $false
}

# When Danger mode is explicitly enabled, also enable Privileged unless explicitly set
if ($Danger -and -not $PSBoundParameters.ContainsKey('Privileged')) {
    $Privileged = $true
    Write-Host "Danger mode enabled - automatically enabling Privileged mode" -ForegroundColor Yellow
}

if ($OssModel) {
    $Oss = $true
}

if (-not $CodexModel) {
    if ($env:CODEX_CLOUD_MODEL) {
        $CodexModel = $env:CODEX_CLOUD_MODEL
    } elseif ($env:CODEX_DEFAULT_MODEL) {
        $CodexModel = $env:CODEX_DEFAULT_MODEL
    }
}

if (-not $OssServerUrl -and $env:OSS_SERVER_URL) {
    $OssServerUrl = $env:OSS_SERVER_URL
}

if (-not $OllamaHost -and $env:OLLAMA_HOST) {
    $OllamaHost = $env:OLLAMA_HOST
}

$script:ResolvedOssServerUrl = $OssServerUrl
$script:ResolvedOllamaHost = $OllamaHost
$DefaultSystemPromptFile = 'PROMPT.md'
$script:DefaultSystemPromptContainerPath = $null

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

function Build-GatewaySessionEnv {
    param(
        [string]$SessionDirs,
        [string]$SecureDir,
        [string]$SecureToken,
        [string]$CodexHome
    )

    $envMap = @{}

    $normalizePath = {
        param($p)
        if (-not $p) { return $null }
        return ($p -replace '\\','/')
    }

    if (-not $SessionDirs) {
        $SessionDirs = '/opt/codex-home/.codex/sessions,/workspace/.codex-gateway-sessions'
    }

    if ($SessionDirs) {
        $parts = $SessionDirs.Split(',') | ForEach-Object { & $normalizePath $_ } | Where-Object { $_ }
        if ($parts.Count -gt 0) {
            $envMap['CODEX_GATEWAY_SESSION_DIRS'] = ($parts -join ',')
        }
    }

    if (-not $SecureDir) {
        $SecureDir = '/opt/codex-home/.codex/sessions/secure'
    }
    if ($SecureDir) {
        $envMap['CODEX_GATEWAY_SECURE_SESSION_DIR'] = & $normalizePath $SecureDir
    }
    if ($SecureToken) {
        $envMap['CODEX_GATEWAY_SECURE_TOKEN'] = $SecureToken
    }

    return $envMap
}

function Get-ConfigFilePath {
    param(
        [string]$WorkspacePath
    )
    $candidates = @(
        (Join-Path $WorkspacePath '.codex-container.json'),
        (Join-Path $WorkspacePath '.codex_container.json'),
        (Join-Path $WorkspacePath '.codex-container.toml'),
        (Join-Path $WorkspacePath '.codex_container.toml')
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

function Read-ProjectConfig {
    param(
        [string]$WorkspacePath
    )

    $configPath = Get-ConfigFilePath -WorkspacePath $WorkspacePath
    if (-not $configPath) {
        return $null
    }

    $ext = [System.IO.Path]::GetExtension($configPath).ToLower()

    # Helper to coerce parsed data into our shape
    function Convert-ToConfigObject {
        param($data)
        return [pscustomobject]@{
            env         = if ($data -and $data.env) { $data.env } else { @{} }
            mounts      = if ($data -and $data.mounts) { $data.mounts } else { @() }
            tools       = if ($data -and $data.tools) { $data.tools } else { @() }
            env_imports = if ($data -and $data.env_imports) { $data.env_imports } else { @() }
        }
    }

    # JSON: use built-in ConvertFrom-Json
    if ($ext -eq '.json') {
        try {
            $raw = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop
            $data = $raw | ConvertFrom-Json -ErrorAction Stop
            return Convert-ToConfigObject $data
        } catch {
            Write-Warning "Failed to parse JSON config ${configPath}: $($_.Exception.Message)"
            return $null
        }
    }

    # TOML: naive PowerShell parse for env, env_imports, mounts, tools
    try {
        $lines = Get-Content -LiteralPath $configPath -ErrorAction Stop
    } catch {
        Write-Warning "Failed to read ${configPath}: $($_.Exception.Message)"
        return $null
    }

    $envTable = @{}
    $envImports = @()
    $inEnvImports = $false
    $envImportBuffer = @()
    $mounts = @()
    $tools = @()
    $inEnv = $false

    foreach ($line in $lines) {
        $trim = $line.Trim()
        if ($trim -match '^\[env\]') {
            $inEnv = $true
            continue
        }
        if ($trim -match '^\[') {
            $inEnv = $false
        }
        if ($inEnv -and $trim -match '^(?<k>[A-Za-z0-9_]+)\s*=\s*\"(?<v>[^\"]*)\"') {
            $envTable[$matches['k']] = $matches['v']
        }
        # Multiline-friendly env_imports parsing
        if (-not $inEnvImports -and $trim -match '^env_imports\s*=\s*\[(?<rest>.*)$') {
            $inEnvImports = $true
            $envImportBuffer = @()
            if ($matches['rest']) {
                $envImportBuffer += $matches['rest']
            }
            if ($trim -match '\]') {
                $inEnvImports = $false
                $joined = ($envImportBuffer -join ' ')
                $joined = $joined -replace '^\[','' -replace '\]$',''
                $parts = $joined -split ',' | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ }
                $envImports += $parts
            }
            continue
        }
        if ($inEnvImports) {
            $envImportBuffer += $trim
            if ($trim -match '\]') {
                $inEnvImports = $false
                $joined = ($envImportBuffer -join ' ')
                $joined = $joined -replace '^\[','' -replace '\]$',''
                $parts = $joined -split ',' | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ }
                $envImports += $parts
            }
        }
        if ($trim -match '^mounts\s*=\s*\[(?<arr>.*)\]') {
            $arr = $matches['arr']
            $parts = $arr -split ',' | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ }
            $mounts += $parts
        }
        if ($trim -match '^tools\s*=\s*\[(?<arr>.*)\]') {
            $arr = $matches['arr']
            $parts = $arr -split ',' | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ }
            $tools += $parts
        }
    }

    return [pscustomobject]@{
        env         = $envTable
        env_imports = $envImports
        mounts      = $mounts
        tools       = $tools
    }
}

function Build-MountArgs {
    param(
        [string]$WorkspacePath,
        $ConfigMounts
    )

    $args = @()
    if (-not $ConfigMounts) {
        return $args
    }

    $normalizePath = {
        param($p)
        if (-not $p) { return $null }
        return ($p -replace '\\','/')
    }

    foreach ($m in $ConfigMounts) {
        $hostPath = $null
        $container = $null
        $mode = 'rw'
        if ($m -is [string]) {
            $hostPath = $m
        } elseif ($m) {
            $hostPath = $m.host
            $container = $m.container
            if ($m.mode) { $mode = $m.mode }
        }
        if (-not $hostPath) { continue }
        $hostNorm = & $normalizePath $hostPath
        if (-not $container) {
            $container = "/workspace/" + ([System.IO.Path]::GetFileName($hostNorm))
        }
        $containerNorm = & $normalizePath $container
        $suffix = if ($mode -and $mode.ToLower() -eq 'ro') { ':ro' } else { '' }
        $args += @('-v', "${hostNorm}:${containerNorm}${suffix}")
    }
    return $args
}

function Build-EnvArgs {
    param(
        $EnvMap
    )
    $envArgs = @()
    if (-not $EnvMap) { return $envArgs }

    # Support both hashtables and PSCustomObjects (toml parser may return either)
    if ($EnvMap -is [hashtable]) {
        foreach ($key in $EnvMap.Keys) {
            $val = $EnvMap[$key]
            if ($null -ne $val) {
                $envArgs += @('-e', "$key=$val")
            }
        }
    }
    elseif ($EnvMap -is [psobject]) {
        foreach ($prop in $EnvMap.PSObject.Properties) {
            $key = $prop.Name
            $val = $prop.Value
            if ($null -ne $val) {
                $envArgs += @('-e', "$key=$val")
            }
        }
    }
    else {
        try {
            foreach ($entry in $EnvMap.GetEnumerator()) {
                if ($null -ne $entry.Value) {
                    $envArgs += @('-e', "$($entry.Key)=$($entry.Value)")
                }
            }
        } catch {
            # fallback: best effort
        }
    }
    return $envArgs
}

function Build-EnvImportArgs {
    param(
        [string[]]$Names
    )
    $envArgs = @()
    if (-not $Names) { return $envArgs }
    foreach ($name in $Names) {
        if (-not $name) { continue }
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($null -ne $value -and $value -ne '') {
            $envArgs += @('-e', "${name}=${value}")
        }
    }
    return $envArgs
}

function Get-SystemPromptContainerPath {
    param(
        [string]$WorkspacePath
    )

    $candidates = @()
    if ($env:CODEX_SYSTEM_PROMPT_FILE) {
        $candidates += $env:CODEX_SYSTEM_PROMPT_FILE
    }
    $candidates += $DefaultSystemPromptFile

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }

        $hostPath = $candidate
        if (-not [System.IO.Path]::IsPathRooted($hostPath)) {
            if (-not $WorkspacePath) {
                continue
            }
            $hostPath = Join-Path $WorkspacePath $candidate
        }

        try {
            $resolvedHost = (Resolve-Path $hostPath -ErrorAction Stop).Path
        } catch {
            continue
        }

        if (-not (Test-Path $resolvedHost)) {
            continue
        }

        if (-not $WorkspacePath) {
            continue
        }

        try {
            $resolvedWorkspace = (Resolve-Path $WorkspacePath -ErrorAction Stop).Path
        } catch {
            continue
        }

        if (-not $resolvedHost.StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }

        $relative = $resolvedHost.Substring($resolvedWorkspace.Length).TrimStart('\', '/')
        $containerPath = "/workspace/" + ($relative -replace '\\', '/')
        return $containerPath
    }

    return $null
}

function Add-DefaultSystemPrompt {
    param(
        [string]$Action,
        [string]$WorkspacePath
    )

    $script:DefaultSystemPromptContainerPath = $null
    $eligibleActions = @('Serve', 'Exec', 'Run')
    if ($eligibleActions -notcontains $Action) {
        return
    }
    if ($env:CODEX_DISABLE_DEFAULT_PROMPT -match '^(1|true|on)$') {
        return
    }
    if (-not $WorkspacePath) {
        return
    }

    $promptMapping = Get-SystemPromptContainerPath -WorkspacePath $WorkspacePath
    if (-not $promptMapping) {
        return
    }

    $script:DefaultSystemPromptContainerPath = $promptMapping
}

function Test-HasModelFlag {
    param(
        [string[]]$Args
    )

    if (-not $Args) {
        return $false
    }

    for ($i = 0; $i -lt $Args.Count; $i++) {
        $arg = $Args[$i]
        if ($arg -eq '--model' -or $arg -like '--model=*') {
            return $true
        }
    }

    return $false
}

function Test-HasSystemFlag {
    param(
        [string[]]$Args
    )

    if (-not $Args) {
        return $false
    }

    foreach ($arg in $Args) {
        if (-not $arg) { continue }
        if ($arg -eq '--system' -or $arg -like '--system=*') {
            return $true
        }
        if ($arg -eq '--system-file' -or $arg -like '--system-file=*') {
            return $true
        }
    }

    return $false
}

function Get-PythonInvocation {
    if ($env:PYTHON) {
        return [PSCustomObject]@{ FilePath = $env:PYTHON; Prefix = @() }
    }

    foreach ($candidate in @('python3', 'python')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            return [PSCustomObject]@{ FilePath = $candidate; Prefix = @() }
        }
    }

    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        return [PSCustomObject]@{ FilePath = 'py'; Prefix = @('-3') }
    }

    throw 'Unable to locate a Python interpreter on the host. Install Python or set $env:PYTHON.'
}

function Resolve-SpeakerPaths {
    param(
        [string]$CodexHome
    )

    $speakerRoot = Join-Path $CodexHome 'speaker'
    $voiceOutbox = Join-Path $CodexHome 'voice-outbox'
    $scriptTarget = Join-Path $speakerRoot 'speaker_service.py'
    $logPath = Join-Path $speakerRoot 'speaker.log'
    $pidPath = Join-Path $speakerRoot 'speaker.pid'

    return [PSCustomObject]@{
        SpeakerRoot   = $speakerRoot
        VoiceOutbox   = $voiceOutbox
        ScriptPath    = $scriptTarget
        LogPath       = $logPath
        PidPath       = $pidPath
    }
}

function Stop-SpeakerService {
    param(
        $Config
    )

    if (-not $Config) {
        return
    }

    if ($Config.Process -and -not $Config.Process.HasExited) {
        try {
            Stop-Process -Id $Config.Process.Id -ErrorAction SilentlyContinue
        } catch {
            # Ignore
        }
    }

    if ($Config.PidPath -and (Test-Path $Config.PidPath)) {
        try {
            $pidValue = Get-Content -Path $Config.PidPath -ErrorAction SilentlyContinue
            if ($pidValue) {
                $parsedPid = $pidValue -as [int]
                if ($parsedPid) {
                    try {
                        Stop-Process -Id $parsedPid -ErrorAction SilentlyContinue
                    } catch {
                        # Ignore
                    }
                }
            }
        } catch {
            # ignore
        }

        try {
            Remove-Item -Path $Config.PidPath -Force -ErrorAction SilentlyContinue
        } catch {
            # ignore
        }
    }
}

function Wait-SpeakerHealth {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthUrl = "http://127.0.0.1:$Port/health"
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }

    return $false
}

function Start-SpeakerService {
    param(
        $Context,
        [int]$Port
    )

    $paths = Resolve-SpeakerPaths -CodexHome $Context.CodexHome
    foreach ($dir in @($paths.SpeakerRoot, $paths.VoiceOutbox)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    $sourceScript = Join-Path $Context.CodexRoot 'scripts/speaker_service.py'
    if (-not (Test-Path $sourceScript)) {
        throw "speaker_service.py not found at $sourceScript"
    }
    Copy-Item -Path $sourceScript -Destination $paths.ScriptPath -Force

    if (Test-Path $paths.PidPath) {
        Stop-SpeakerService -Config @{ PidPath = $paths.PidPath }
    }

    $python = Get-PythonInvocation
    $bindAddress = if ($env:SPEAKER_BIND) { $env:SPEAKER_BIND } else { '0.0.0.0' }

    $argumentList = @()
    if ($python.Prefix) {
        $argumentList += $python.Prefix
    }
    $argumentList += @(
        $paths.ScriptPath,
        "--port=$Port",
        "--outbox=$($paths.VoiceOutbox)",
        "--log=$($paths.LogPath)",
        "--bind=$bindAddress",
        "--startup-test"
    )
    if ($env:SPEAKER_EXTRA_ARGS) {
        $argumentList += $env:SPEAKER_EXTRA_ARGS.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    }

    $process = Start-Process -FilePath $python.FilePath -ArgumentList $argumentList -PassThru -WindowStyle Hidden

    if (-not (Wait-SpeakerHealth -Port $Port -TimeoutSeconds 10)) {
        try { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue } catch {}
        throw "Speaker service failed to start on port $Port"
    }

    Set-Content -Path $paths.PidPath -Value $process.Id

    $hostUrl = "http://host.docker.internal:$Port/play"
    return [PSCustomObject]@{
        Process      = $process
        PidPath      = $paths.PidPath
        Port         = $Port
        VoiceOutbox  = $paths.VoiceOutbox
        ContainerOutbox = '/workspace/voice-outbox'
        SpeakerUrl   = $hostUrl
        LogPath      = $paths.LogPath
    }
}

function New-CodexContext {
    param(
        [string]$Tag,
        [string]$Workspace,
        [string]$ScriptRoot,
        [string]$CodexHomeOverride,
        [switch]$Privileged,
        [string]$GatewaySessionDirs,
        [string]$GatewaySecureDir,
        [string]$GatewaySecureToken
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

    if ($Privileged) {
        $runArgs += '--privileged'
    }

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

    $config = Read-ProjectConfig -WorkspacePath $workspacePath
    # Handle env_imports declared inside [env] table (common TOML style)
    if ($config -and $config.env -and -not $config.env_imports) {
        $envImportsValue = $null
        if ($config.env -is [hashtable]) {
            if ($config.env.ContainsKey('env_imports')) {
                $envImportsValue = $config.env['env_imports']
                $config.env.Remove('env_imports') | Out-Null
            }
        } else {
            # PSCustomObject path
            $prop = $config.env.PSObject.Properties['env_imports']
            if ($prop) {
                $envImportsValue = $prop.Value
                # cannot remove safely from PSCustomObject; leave as-is
            }
        }
        if ($envImportsValue) {
            $config.env_imports = $envImportsValue
        }
    }
    if ($config) {
        $configPath = (Get-ConfigFilePath -WorkspacePath $workspacePath)
        Write-Host "  Project config: $configPath" -ForegroundColor DarkGray
        $importList = if ($config.env_imports) { $config.env_imports -join ', ' } else { '' }
        if ($importList) {
            Write-Host ("  Config env_imports: {0}" -f $importList) -ForegroundColor DarkGray
        } else {
            Write-Host "  Config env_imports: none" -ForegroundColor DarkGray
        }
    }

    if ($config -and $config.mounts) {
        $runArgs += (Build-MountArgs -WorkspacePath $workspacePath -ConfigMounts $config.mounts)
    }

    if ($config -and $config.env) {
        $runArgs += (Build-EnvArgs -EnvMap $config.env)
    }
    if ($config -and $config.env_imports) {
        $envImportArgs = Build-EnvImportArgs -Names $config.env_imports
        if ($envImportArgs.Count -gt 0) {
            Write-Host ("  Injecting env_imports ({0} vars)" -f ($envImportArgs.Count / 2)) -ForegroundColor DarkGray
            # Show the names only (every even index is the -e flag)
            $names = @()
            for ($i = 1; $i -lt $envImportArgs.Count; $i += 2) { $names += ($envImportArgs[$i] -split '=',2)[0] }
            Write-Host ("    Names: {0}" -f ($names -join ', ')) -ForegroundColor DarkGray
        } else {
            Write-Host "  env_imports provided but no host values found" -ForegroundColor Yellow
        }
        $runArgs += $envImportArgs
    }

    $gatewaySessionEnv = Build-GatewaySessionEnv -SessionDirs $GatewaySessionDirs -SecureDir $GatewaySecureDir -SecureToken $GatewaySecureToken -CodexHome $codexHome
    foreach ($key in $gatewaySessionEnv.Keys) {
        $runArgs += @('-e', "${key}=$($gatewaySessionEnv[$key])")
    }

    # Add session webhook envs only when explicitly provided via flags
    if ($SessionWebhookUrl) { $runArgs += @('-e', "SESSION_WEBHOOK_URL=$SessionWebhookUrl") }
    if ($SessionWebhookAuthBearer) { $runArgs += @('-e', "SESSION_WEBHOOK_AUTH_BEARER=$SessionWebhookAuthBearer") }
    if ($SessionWebhookHeadersJson) { $runArgs += @('-e', "SESSION_WEBHOOK_HEADERS_JSON=$SessionWebhookHeadersJson") }
    if ($SessionWebhookTimeoutMs) { $runArgs += @('-e', "SESSION_WEBHOOK_TIMEOUT_MS=$SessionWebhookTimeoutMs") }

    # Inject env_imports from config (env vars present on host)
    if ($config -and $config.env_imports) {
        foreach ($import in $config.env_imports) {
            if (-not $import) { continue }
            $val = [Environment]::GetEnvironmentVariable($import)
            if ($null -ne $val -and $val -ne '') {
                $runArgs += @('-e', "$import=$val")
            }
        }
    }

    if ($Privileged) {
        Write-Host "  Docker run will use --privileged" -ForegroundColor DarkGray
        $runArgs += '--privileged'
    }

    return [PSCustomObject]@{
        Tag = $Tag
        CodexRoot = $codexRoot
        CodexHome = $codexHome
        GatewaySessionEnv = $gatewaySessionEnv
        ProjectConfig = $config
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
        'build'
    )
    if ($NoCache) {
        $buildArgs += '--no-cache'
    }
    $buildArgs += @(
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
        [string[]]$AdditionalEnv,
        [switch]$Danger,
        [switch]$GatewayMode
    )

    $args = @()
    $args += $Context.RunArgs
    if ($ExposeLoginPort) {
        $args += @('-p', '1455:1455')
    }
    if ($Oss) {
        $resolvedOss = $script:ResolvedOssServerUrl
        $resolvedOllama = $script:ResolvedOllamaHost
        $enableBridge = $false

        if (-not $resolvedOss -and -not $resolvedOllama) {
            $resolvedOss = 'http://host.docker.internal:11434'
            $resolvedOllama = $resolvedOss
            $enableBridge = $true
        } elseif (-not $resolvedOss -and $resolvedOllama) {
            $resolvedOss = $resolvedOllama
        } elseif (-not $resolvedOllama -and $resolvedOss) {
            $resolvedOllama = $resolvedOss
        }

        if ($resolvedOllama) {
            $args += @('-e', "OLLAMA_HOST=$resolvedOllama")
        }
        if ($resolvedOss) {
            $args += @('-e', "OSS_SERVER_URL=$resolvedOss")
        }
        if ($enableBridge) {
            $args += @('-e', 'ENABLE_OSS_BRIDGE=1')
        }
        if ($env:OSS_API_KEY) {
            $args += @('-e', "OSS_API_KEY=$($env:OSS_API_KEY)")
        }
        if ($env:OSS_DISABLE_BRIDGE) {
            $args += @('-e', "OSS_DISABLE_BRIDGE=$($env:OSS_DISABLE_BRIDGE)")
        }
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
    if ($Danger) {
        # Pass sandbox args via env var for gateway to use when spawning Codex
        $args += @('-e', 'CODEX_GATEWAY_EXTRA_ARGS=--sandbox danger-full-access')
        # Force network-enabled sandbox inside Codex
        $args += @('-e', 'CODEX_SANDBOX_NETWORK_DISABLED=0')
    }
    $args += $Context.Tag
    $args += '/usr/bin/tini'
    $args += '--'
    if (-not $GatewayMode) {
        $args += '/usr/local/bin/codex_entry.sh'
        if ($Danger) {
            $args += '--dangerously-bypass-approvals-and-sandbox'
        }
    }

    # VALIDATION: Ensure no empty strings or null values in arguments
    $nullCount = 0
    $emptyCount = 0
    foreach ($arg in $args) {
        if ($arg -eq $null) { $nullCount++ }
        elseif ($arg -eq '') { $emptyCount++ }
    }

    if ($nullCount -gt 0 -or $emptyCount -gt 0) {
        Write-Host "WARNING in New-DockerRunArgs: Found $nullCount nulls, $emptyCount empty strings" -ForegroundColor Yellow
    }

    return $args
}

function Test-CodexEnvironment {
    param(
        $Context
    )

    $issues = @()
    $warnings = @()

    # Warn about missing API key (non-blocking)
    if (-not $env:ANTHROPIC_API_KEY) {
        $warnings += "ANTHROPIC_API_KEY not set - Codex tools won't work until configured"
    }

    # Check Docker daemon is running (blocking)
    try {
        $dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
        if (-not $dockerVersion) {
            $issues += "Docker daemon is not running or not accessible"
        }
    } catch {
        $issues += "Docker check failed: $_"
    }

    # Check if image exists (blocking)
    if (-not (Ensure-DockerImage -Tag $Context.Tag)) {
        $issues += "Docker image $($Context.Tag) is not available"
    }

    # Show warnings
    if ($warnings.Count -gt 0) {
        Write-Host "Warnings:" -ForegroundColor Yellow
        foreach ($warning in $warnings) {
            Write-Host "  - $warning" -ForegroundColor Yellow
        }
    }

    # Show blocking issues
    if ($issues.Count -gt 0) {
        Write-Host "Environment Issues Found:" -ForegroundColor Red
        foreach ($issue in $issues) {
            Write-Host "  - $issue" -ForegroundColor Red
        }
        return $false
    }

    return $true
}

function Invoke-CodexContainer {
    param(
        $Context,
        [string[]]$CommandArgs,
        [switch]$ExposeLoginPort,
        [string[]]$AdditionalArgs,
        [string[]]$AdditionalEnv,
        [switch]$GatewayMode
    )

    $runArgs = New-DockerRunArgs -Context $Context -ExposeLoginPort:$ExposeLoginPort -AdditionalArgs $AdditionalArgs -AdditionalEnv $AdditionalEnv -Danger:$Danger -GatewayMode:$GatewayMode
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

    # CRITICAL FIX: Remove empty strings and null values that can cause docker command failure
    $cleanArgs = @($runArgs | Where-Object { $_ -ne $null -and $_ -ne '' })

    if ($cleanArgs.Count -ne $runArgs.Count) {
        Write-Host "WARNING: Removed $($runArgs.Count - $cleanArgs.Count) empty/null arguments" -ForegroundColor Yellow
    }

    # Print copy/paste-ready docker commands (full, final args)
    $posixArgs = $cleanArgs | ForEach-Object { "'" + ($_ -replace "'", "'\'''") + "'" }
    $psArgs    = $cleanArgs | ForEach-Object { '"' + ($_ -replace '"','`"') + '"' }
    Write-Host ("[bash/zsh] docker {0}" -f ($posixArgs -join ' ')) -ForegroundColor Yellow
    Write-Host ("[pwsh/cmd] docker {0}" -f ($psArgs -join ' ')) -ForegroundColor Yellow

    if ($env:CODEX_CONTAINER_TRACE) {
        Write-Host "docker $($cleanArgs -join ' ')" -ForegroundColor DarkGray
    }

    # Enhanced error reporting
    docker @cleanArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "ERROR: docker run exited with code $exitCode" -ForegroundColor Red
        Write-Host "Full docker command:" -ForegroundColor Red
        Write-Host "docker $($cleanArgs -join ' ')" -ForegroundColor DarkGray

        Write-Host "`nAll $($cleanArgs.Count) arguments:" -ForegroundColor Red
        for ($i = 0; $i -lt $cleanArgs.Count; $i++) {
            $arg = $cleanArgs[$i]
            if ([string]::IsNullOrEmpty($arg)) {
                Write-Host "  [$i] = <EMPTY>" -ForegroundColor Yellow
            } elseif ($arg -eq '--') {
                Write-Host "  [$i] = '--' (PROBLEM ARGUMENT)" -ForegroundColor Magenta
            } else {
                Write-Host "  [$i] = '$arg'" -ForegroundColor Gray
            }
        }

        throw "docker run exited with code $exitCode"
    }
}

function ConvertTo-ShellScript {
    param(
        [string[]]$Commands
    )

    return ($Commands -join '; ')
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

    $updateEnv = @()
    if ($env:CODEX_SKIP_MCP_SETUP) { $updateEnv += "CODEX_SKIP_MCP_SETUP=$($env:CODEX_SKIP_MCP_SETUP)" }
    if ($Silent) {
        Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash', '-c', $updateScript) -AdditionalEnv $updateEnv | Out-Null
    } else {
        Invoke-CodexContainer -Context $Context -CommandArgs @('/bin/bash', '-c', $updateScript) -AdditionalEnv $updateEnv
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
    if ($CodexModel) {
        $hasModel = $false
        if (Test-HasModelFlag -Args $cmd) {
            $hasModel = $true
        } elseif ($Arguments -and (Test-HasModelFlag -Args $Arguments)) {
            $hasModel = $true
        }
        if (-not $hasModel) {
            $cmd += @('--model', $CodexModel)
        }
    }

    # Disabled: codex CLI doesn't support --system-file flag
    # if ($script:DefaultSystemPromptContainerPath) {
    #     $hasSystem = Test-HasSystemFlag -Args $cmd
    #     if (-not $hasSystem -and $Arguments) {
    #         $hasSystem = Test-HasSystemFlag -Args $Arguments
    #     }
    #     if (-not $hasSystem) {
    #         $cmd += @('--system-file', $script:DefaultSystemPromptContainerPath)
    #     }
    # }
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

    if ($CodexModel -and -not (Test-HasModelFlag -Args $cmdArguments)) {
        $first = $cmdArguments[0]
        $rest = @()
        if ($cmdArguments.Length -gt 1) {
            $rest = $cmdArguments[1..($cmdArguments.Length - 1)]
        }
        $cmdArguments = @($first, '--model', $CodexModel) + $rest
    }

    # Disabled: codex CLI doesn't support --system-file flag
    # if ($script:DefaultSystemPromptContainerPath -and -not (Test-HasSystemFlag -Args $cmdArguments)) {
    #     $first = $cmdArguments[0]
    #     $rest = @()
    #     if ($cmdArguments.Length -gt 1) {
    #         $rest = $cmdArguments[1..($cmdArguments.Length - 1)]
    #     }
    #     $cmdArguments = @($first, '--system-file', $script:DefaultSystemPromptContainerPath) + $rest
    # }

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
        [string[]]$ExtraArgs,
        [int]$LogLevel
    )

    Ensure-CodexCli -Context $Context

    if (-not $Port) {
        $Port = 4000
    }
    if (-not $BindHost) {
        $BindHost = '127.0.0.1'
    }

    # Default file watcher settings if not supplied
    $configWatchPaths = $null
    if ($Context -and $Context.ProjectConfig -and $Context.ProjectConfig.env) {
        if ($Context.ProjectConfig.env -is [hashtable]) {
            $configWatchPaths = $Context.ProjectConfig.env['CODEX_GATEWAY_WATCH_PATHS']
        } elseif ($Context.ProjectConfig.env -is [psobject]) {
            $prop = $Context.ProjectConfig.env.PSObject.Properties['CODEX_GATEWAY_WATCH_PATHS']
            if ($prop) { $configWatchPaths = $prop.Value }
        }
    }

    if ([string]::IsNullOrWhiteSpace($GatewayWatchPaths)) {
        if (-not [string]::IsNullOrWhiteSpace($configWatchPaths)) {
            $GatewayWatchPaths = $configWatchPaths
        } elseif (-not [string]::IsNullOrWhiteSpace($env:CODEX_GATEWAY_WATCH_PATHS)) {
            $GatewayWatchPaths = $env:CODEX_GATEWAY_WATCH_PATHS
        } else {
            $GatewayWatchPaths = './temp'
        }
    }

    if (-not $GatewayWatchPattern) { $GatewayWatchPattern = '**/*' }
    # Do NOT set a default prompt file here; only use what the caller provides
    if (-not $GatewayWatchDebounceMs) { $GatewayWatchDebounceMs = 750 }

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
    if ($LogLevel) {
        $envVars += "CODEX_GATEWAY_LOG_LEVEL=$LogLevel"
    }
    if ($GatewayWatchPaths) {
        $envVars += "CODEX_GATEWAY_WATCH_PATHS=$GatewayWatchPaths"
    }
    if ($GatewayWatchPattern) {
        $envVars += "CODEX_GATEWAY_WATCH_PATTERN=$GatewayWatchPattern"
    }
    if ($GatewayWatchPromptFile) {
        $envVars += "CODEX_GATEWAY_WATCH_PROMPT_FILE=$GatewayWatchPromptFile"
    }
    if ($GatewayWatchDebounceMs) {
        $envVars += "CODEX_GATEWAY_WATCH_DEBOUNCE_MS=$GatewayWatchDebounceMs"
    }

    Invoke-CodexContainer -Context $Context -CommandArgs @('node', '/usr/local/bin/codex_gateway.js') -AdditionalArgs @('-p', $publish) -AdditionalEnv $envVars -GatewayMode:$true
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
        [int]$Limit = 5,
        [int]$SinceDays = 0  # 0 = no time filter
    )

    $sessionsDir = Join-Path $Context.CodexHome ".codex/sessions"

    if (-not (Test-Path $sessionsDir)) {
        return
    }

    # Find all rollout-*.jsonl files (sessions are stored as: sessions/2025/10/20/rollout-*.jsonl)
    $sessionFiles = Get-ChildItem -Path $sessionsDir -Recurse -Filter "rollout-*.jsonl" -File -ErrorAction SilentlyContinue |
        Where-Object {
            if ($SinceDays -le 0) { return $true }
            $cutoff = (Get-Date).AddDays(-$SinceDays)
            return $_.LastWriteTime -ge $cutoff
        } |
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
if ($ListSessions) { $actions += 'ListSessions' }

if (-not $actions) {
    $actions = @('Run')
}

if ($actions.Count -gt 1) {
    throw "Specify only one primary action (choose one of -Install, -Build, -Login, -Run, -Exec, -Shell, -Serve, -ListSessions)."
}

$action = $actions[0]

$jsonOutput = $Json -or $JsonE

$jsonFlagsSpecified = @()
if ($Json) { $jsonFlagsSpecified += '-Json' }
if ($JsonE) { $jsonFlagsSpecified += '-JsonE' }
if ($jsonFlagsSpecified.Count -gt 1) {
    throw "Specify only one of $($jsonFlagsSpecified -join ', ')."
}

$speakerConfig = $null
try {
    $context = New-CodexContext -Tag $Tag -Workspace $Workspace -ScriptRoot $PSScriptRoot -CodexHomeOverride $CodexHome -Privileged:$Privileged -GatewaySessionDirs $GatewaySessionDirs -GatewaySecureDir $GatewaySecureDir -GatewaySecureToken $GatewaySecureToken

    if (-not $jsonOutput) {
        Write-Host "Codex container context" -ForegroundColor Cyan
        Write-Host "  Image:      $Tag" -ForegroundColor DarkGray
        Write-Host "  Codex home: $($context.CodexHome)" -ForegroundColor DarkGray
        Write-Host "  Workspace:  $($context.WorkspacePath)" -ForegroundColor DarkGray
    }

    Add-DefaultSystemPrompt -Action $action -WorkspacePath $context.WorkspacePath
    if ($script:DefaultSystemPromptContainerPath) {
        $context.RunArgs = $context.RunArgs + @('-e', "CODEX_SYSTEM_PROMPT_FILE=$($script:DefaultSystemPromptContainerPath)")
    }

    if ($action -ne 'Install') {
        if (-not (Ensure-DockerImage -Tag $context.Tag)) {
            return
        }
    }

    if ($Speaker) {
        if ($action -eq 'Install') {
            Write-Warning "-Speaker has no effect during -Install."
        } else {
            $speakerConfig = Start-SpeakerService -Context $context -Port $SpeakerPort
            $context.RunArgs += @('-v', ("$($speakerConfig.VoiceOutbox):$($speakerConfig.ContainerOutbox)"))
            $context.RunArgs += @('-e', "VOICE_SPEAKER_URL=$($speakerConfig.SpeakerUrl)")
            $context.RunArgs += @('-e', "VOICE_OUTBOX_CONTAINER_PATH=$($speakerConfig.ContainerOutbox)")
            if (-not $jsonOutput) {
                Write-Host ("  Speaker:    $($speakerConfig.SpeakerUrl) (outbox: $($speakerConfig.VoiceOutbox))") -ForegroundColor DarkGray
            }
        }
    }

    # Check environment for actions that will run containers
    if ($action -in @('Shell', 'Exec', 'Serve', 'Run')) {
        if (-not (Test-CodexEnvironment -Context $context)) {
            Write-Host "`nFix the above issues before proceeding." -ForegroundColor Red
            Write-Host "Hint: Ensure Docker is running and ANTHROPIC_API_KEY is set" -ForegroundColor Yellow
            return
        }
    }

    switch ($action) {
    'Install' {
        Invoke-DockerBuild -Context $context -PushImage:$Push
        Ensure-CodexCli -Context $context -Force
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
        Invoke-CodexServe -Context $context -Port $GatewayPort -BindHost $GatewayHost -TimeoutMs $GatewayTimeoutMs -DefaultModel $GatewayDefaultModel -ExtraArgs $GatewayExtraArgs -LogLevel $GatewayLogLevel
    }
    'ListSessions' {
        Show-RecentSessions -Context $context -Limit $RecentLimit -SinceDays $SinceDays
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
            Show-RecentSessions -Context $context -Limit $RecentLimit -SinceDays $SinceDays
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
}
finally {
    if ($speakerConfig) {
        Stop-SpeakerService -Config $speakerConfig
    }
}
