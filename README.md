# Codex Service Container Helper

[![License](https://img.shields.io/badge/license-Gnosis%20AI--Sovereign%20v1.2-blue.svg)](LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![GPU](https://img.shields.io/badge/GPU-CUDA%20enabled-brightgreen.svg)](vibe/TRANSCRIPTION_SERVICE.md)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-112-green.svg)](MCP/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/shell-PowerShell%20%7C%20Bash-orange.svg)]()

These scripts launch the OpenAI Codex CLI inside a reproducible Docker container. Drop either script somewhere on your `PATH`, change into any project, and the helper mounts the current working directory alongside a persistent Codex home so credentials survive between runs.

## Three Interaction Modes

The gnosis-radio application supports three distinct ways to interact with the system, each suited for different workflows:

### 1. TERMINAL MODE (Exec)
One-shot execution for quick queries and commands.

```bash
gnosis-radio --exec "status"                    # Single command
gnosis-radio --exec "scan" --session-id abc12   # Resume conversation
```

**Use Cases:**
- Quick queries and commands
- Long-running conversations via session ID
- Scripted automation
- CI/CD integration

### 2. REMOTE API MODE (Serve)
HTTP gateway for external tool access and multi-user scenarios.

```bash
gnosis-radio --serve --gateway-port 4000
```

**Endpoint:** `POST /completion`

```json
{
  "prompt": "Analyze VHF traffic",
  "model": "opus-4",
  "workspace": "/workspace"
}
```

**Use Cases:**
- Integration with external tools (Webwright, etc.)
- Multi-user scenarios
- Language-agnostic clients
- Remote access to gnosis-radio capabilities

### 3. INTERACTIVE MODE (Monitor)
Chat sessions or event-driven autonomous agents.

```bash
gnosis-radio                                    # Interactive chat
gnosis-radio --monitor --watch-path ./recordings  # Event-driven agent
```

**Event Flow:** File changes → Template substitution → Processing

**Template Variables:** `{{file}}`, `{{path}}`, `{{timestamp}}`, etc.

**Use Cases:**
- Interactive chat for exploration and development
- VHF monitor (new recordings → transcribe → analyze)
- Code watchers (new commits → review → report)
- Log monitoring (errors → investigate → alert)
- Autonomous agents responding to file system events

### MIXING MODES

- Run API server in background: `--serve`
- Test monitor behavior manually: `--exec "$(cat MONITOR.md)"`
- Debug event-driven logic before enabling `--monitor`
- Use session IDs to maintain context across exec calls

## Event-Driven Agent Pattern

**The key feature**: Codex can automatically activate in response to file system changes. This creates an **agent that responds to events** rather than waiting for manual commands. You can replicate any agent behavior manually for testing, then switch to automated monitoring for production.

### How It Works

1. **Monitor Mode** (`--monitor`) - Watches a directory and activates Codex when files change
2. **Template-Driven Prompts** - Uses `MONITOR.md` (or custom prompt file) with variable substitution
3. **Manual Testing** - Run the exact same command with `--exec` to test behavior before enabling monitoring
4. **Event Triggers** - Any file change triggers the agent with context about what changed

**Example workflow:**
```bash
# Test manually first - see what the agent would do
./scripts/codex_container.sh --exec \
  --workspace vhf_monitor \
  "Check for new recordings and transcribe them"

# Same behavior, now automated on file changes
./scripts/codex_container.sh --monitor \
  --watch-path vhf_monitor \
  --monitor-prompt MONITOR.md
```

The agent sees the same files, same tools, same context - whether triggered manually or automatically. This makes testing and debugging trivial: just run the manual version to see what would happen.

### Monitor Mode in Detail

Monitor mode watches a directory and runs Codex whenever files change, using a prompt template that gets variable substitution:

```bash
./scripts/codex_container.sh --monitor \
  --watch-path vhf_monitor \
  --monitor-prompt MONITOR.md \
  --codex-arg "--model" --codex-arg "o4-mini"
```

PowerShell variant:
```powershell
./scripts/codex_container.ps1 -Monitor -WatchPath ..\vhf_monitor -CodexArgs "--model","o4-mini"
```

**Template variables available in your prompt:**
- `{{file}}`, `{{directory}}` - File/directory name
- `{{full_path}}`, `{{relative_path}}` - Paths on host
- `{{container_path}}`, `{{container_dir}}` - Paths inside container
- `{{extension}}`, `{{action}}`, `{{timestamp}}` - File metadata
- `{{watch_root}}` - Base directory being monitored
- `{{old_file}}`, `{{old_full_path}}`, etc. - For file moves/renames

**Testing pattern:**
1. Write your prompt in `MONITOR.md` with template variables
2. Test manually: `./scripts/codex_container.sh --exec "$(cat MONITOR.md)"`
3. Enable monitoring: `./scripts/codex_container.sh --monitor --watch-path .`
4. Agent now responds automatically to file changes

**Example `MONITOR.md`:**
```markdown
File changed: {{relative_path}}

Check if this is a new VHF recording. If so:
1. Call transcribe_pending_recordings MCP tool
2. Review transcription for maritime callsigns
3. Update status log

Container path: {{container_path}}
```

Combine with MCP tools (e.g., `transcribe_pending_recordings` from `radio_control.py`) for end-to-end automation. The agent can call tools, read files, and take actions - all triggered by file system events.

## Codex Home Directory

By default the container mounts a user-scoped directory as its `$HOME`:

- Windows PowerShell: `%USERPROFILE%\.codex-service`
- macOS / Linux / WSL: `$HOME/.codex-service`

This folder holds Codex authentication (`.codex/`), CLI configuration, and any scratch files produced inside the container. You can override the location in two ways:

1. Set `CODEX_CONTAINER_HOME` before invoking the script.
2. Pass an explicit flag (`-CodexHome <path>` or `--codex-home <path>`).

Relative paths are resolved the same way your shell would (e.g. `./state`, `~/state`).

Both scripts expand `~`, accept absolute paths, and create the directory if it does not exist. If you previously used the repo-local `codex-home/` folder, move or copy its contents into the new location and delete the old directory when you're done.

## Session Management

Both scripts now support resuming previous Codex sessions:

**List recent sessions:**
```bash
# Bash - shows recent sessions automatically when running without arguments
./scripts/codex_container.sh

# PowerShell
./scripts/codex_container.ps1
```

**Resume a session by short ID:**
```bash
# Bash - use last 5 characters of session UUID
./scripts/codex_container.sh --session-id bffba

# PowerShell
./scripts/codex_container.ps1 -SessionId bffba
```

Sessions are stored in `~/.codex-service/.codex/sessions/` organized by date. The scripts support Docker-style partial matching - you only need to provide enough characters to uniquely identify the session (typically 5).

## Windows (PowerShell)

`scripts\codex_container.ps1` (once on `PATH`, invoke it as `codex-container.ps1` or similar):

- **Install / rebuild the image**
  ```powershell
  ./scripts/codex_container.ps1 -Install
  ```
  Builds the `gnosis/codex-service:dev` image and refreshes the bundled Codex CLI.
  The script always mounts the workspace you specify with `-Workspace` (or, by default, the directory you were in when you invoked the command) so Codex sees the same files regardless of the action.

  The install process also:
  - Installs any MCP servers found in the `MCP/` directory (Python scripts are automatically registered in Codex config)
  - Creates a runner script in your Codex home `bin/` directory and adds it to your PATH for easy invocation

- **Authenticate Codex** *(normally triggered automatically)*
  ```powershell
  ./scripts/codex_container.ps1 -Login
  ```

- **Run the interactive CLI in the current repo**
  ```powershell
  ./scripts/codex_container.ps1 -- "summarize the repo"
  ```

- **Non-interactive execution**
  ```powershell
  ./scripts/codex_container.ps1 -Exec "hello"
  ./scripts/codex_container.ps1 -Exec -JsonE "status report"
  ```
  `-Json` enables the legacy `--json` stream; `-JsonE` selects the new `--experimental-json` format.

- **Custom Codex home**
  ```powershell
  ./scripts/codex_container.ps1 -Exec "hello" -CodexHome "C:\\Users\\kordl\\.codex-service-test"
  ```

- **Other useful switches**
  - `-Shell` opens an interactive `/bin/bash` session inside the container.
  - `-Workspace <path>` mounts a different project directory at `/workspace`.
  - `-Tag <image>` and `-Push` let you build or push under a custom image name.
  - `-SkipUpdate` skips the npm refresh (useful when you know the CLI is up to date).
  - `-NoAutoLogin` disables the implicit login check; Codex must already be authenticated.
  - `-Oss` tells Codex to target a locally hosted provider via `--oss` (e.g., Ollama). The helper automatically bridges `127.0.0.1:11434` inside the container to your host service—just keep Ollama running as you normally would.
  - `-OssModel <name>` (maps to Codex `-m/--model` and implies `-Oss`) selects the model Codex should request when using the OSS provider.
  - `-CodexArgs <value>` and `-Exec` both accept multiple values (repeat the flag or pass positionals after `--`) to forward raw arguments to the CLI.
  - `-SessionId <id>` resumes a previous session (accepts full UUID or last 5 characters)
  - `-TranscriptionServiceUrl <url>` configures the transcription service endpoint (default: `http://host.docker.internal:8765`)

## macOS / Linux / WSL (Bash)

`scripts/codex_container.sh` provides matching functionality:

- Primary actions: `--install`, `--login`, `--run` (default), `--exec`, `--shell`, `--serve`, `--watch`, `--monitor`
  - `--install` builds the image, updates the Codex CLI, installs MCP servers from `MCP/`, and sets up the runner on PATH
- JSON output switches: `--json`, `--json-e` (alias `--json-experimental`)
- Override Codex home: `--codex-home /path/to/state`
- Other useful flags:
  - `--workspace <path>` mounts an alternate directory as `/workspace`.
  - `--tag <image>` / `--push` match the Docker image controls in the PowerShell script.
  - `--skip-update` skips the npm refresh; `--no-auto-login` avoids implicit login attempts.
  - `--oss` forwards the `--oss` flag and the helper bridge takes care of sending container traffic to your host Ollama service automatically.
  - `--model <name>` (maps to Codex `-m/--model` and implies `--oss`) mirrors the PowerShell `-OssModel` flag.
  - `--codex-arg <value>` and `--exec-arg <value>` forward additional parameters to Codex (repeat the flag as needed).
  - `--watch-*` controls the directory watcher (see *Directory Watcher* below).
  - `--monitor [--monitor-prompt <file>]` watches a directory and, for each change, feeds `MONITOR.md` (or your supplied prompt file) to Codex alongside the file path.
  - `--session-id <id>` resumes a previous session (accepts full UUID or last 5 characters)
  - `--transcription-service-url <url>` configures the transcription service endpoint (default: `http://host.docker.internal:8765`)

Typical example:

```bash
./scripts/codex_container.sh --exec --json-e "hello"
```
The directory passed via `--workspace`—or, if omitted, the directory you were in when you invoked the script—is what gets mounted into `/workspace` for *all* actions (install, login, run, etc.).

### Run the local HTTP gateway

To expose Codex as a lightweight chat-completions service on your machine:

```bash
./scripts/codex_container.sh --serve --gateway-port 4000
```
PowerShell equivalent:

```powershell
./scripts/codex_container.ps1 -Serve -GatewayPort 4000
```

- The script mounts your current directory at `/workspace`, so Codex tools can operate on the same files Webwright sees.
- `--gateway-port` controls the host/container port (defaults to `4000`). `--gateway-host` lets you bind to a specific host interface (default `127.0.0.1`).
- The container listens for POST requests at `/completion` and exposes a simple health probe at `/health`.

Set any of the following environment variables before invoking `--serve` to tweak behaviour:

| Variable | Purpose |
| --- | --- |
| `CODEX_GATEWAY_DEFAULT_MODEL` | Force a specific Codex model (falls back to Codex defaults when unset). |
| `CODEX_GATEWAY_TIMEOUT_MS` | Override the default 120s request timeout. |
| `CODEX_GATEWAY_EXTRA_ARGS` | Extra flags forwarded to `codex exec` (space-delimited). |

Stop the gateway with `Ctrl+C`; the container exits when the process ends.

## MCP Servers

The install process automatically discovers and registers MCP (Model Context Protocol) servers:

- Place Python MCP server scripts (`.py` files) in the `MCP/` directory at the repository root
- During `--install`/`-Install`, the scripts are copied to your Codex home and registered in `.codex/config.toml`
- MCP servers run in a dedicated Python virtual environment (`/opt/mcp-venv`) with `aiohttp`, `fastmcp`, and `tomlkit` pre-installed
- Servers are invoked via `/opt/mcp-venv/bin/python3` to avoid PEP-668 conflicts

Example MCP directory structure:
```
codex-container/
├── MCP/
│   ├── my_tool_server.py
│   └── data_processor.py
├── scripts/
└── Dockerfile
```

After running install, these servers will be available to Codex for tool execution.

### Available MCP Tools (112 total)

The container includes comprehensive tool coverage across multiple domains:

**File Operations** (gnosis-files-*.py)
- Basic: `file_read`, `file_write`, `file_stat`, `file_exists`, `file_delete`, `file_copy`, `file_move`
- Advanced: `file_diff`, `file_backup`, `file_list_versions`, `file_restore`, `file_patch`
- Search: `file_search`, `file_search_content`, `file_search_regex`

**Web Scraping & Search**
- `crawl_url`, `crawl_batch`, `raw_html` - Web crawling with markdown conversion
- `serpapi_search` - Google search results via SerpAPI
- `product_search` - E-commerce product search

**Google Workspace Integration**
- **Calendar**: `gcal_list_events`, `gcal_create_event`, `gcal_update_event`, `gcal_delete_event`, etc.
- **Gmail**: `gmail_list_messages`, `gmail_send`, `gmail_search`, `gmail_get_thread`, `gmail_create_draft`, etc.
- **Drive**: `gdrive_list_files`, `gdrive_upload`, `gdrive_download`, `gdrive_search`, `gdrive_share`, etc.

**Communication & Collaboration**
- **Slack**: `slack_send_message`, `slack_send_image`, `slack_upload_file`, `slack_get_user`, `slack_get_channel`
- **Human Interaction**: `talk_to_human`, `report_to_supervisor`
- **Notes**: `create_sticky_note`, `read_sticky_notes`, `update_sticky_note`, `delete_sticky_note`

**Maritime & Radio Operations**
- VHF radio control and monitoring
- Radio network management
- Audio transcription with Whisper AI

**Weather & Environment**
- `get_current_weather`, `get_forecast`, `get_marine_weather` - Open-Meteo integration with marine conditions

**Utilities**
- Time operations and scheduling
- Log file reading and monitoring
- Background process coordination (`wait_at_water_cooler`, `take_cups`, `recycle_cups`)

All MCP servers use the FastMCP framework for reliable, async tool execution.

## GPU-Accelerated Transcription Service

The project includes a persistent GPU-accelerated transcription service using OpenAI Whisper large-v3:

**Features:**
- **CUDA-Accelerated**: 10x faster transcription with NVIDIA GPU support
- **Persistent Model**: Whisper large-v3 stays loaded in memory (no reload between jobs)
- **HTTP API**: Simple REST interface for uploading WAV files and retrieving transcripts
- **Async Queue**: Background job processing with status polling
- **Pre-cached Model**: ~3GB Whisper model baked into Docker image for instant startup
- **Formatted Output**: Transmission-style reports with waveform visualization and metadata

**Quick Start:**
```powershell
# Build and start the service (PowerShell)
./scripts/start_transcription_service_docker.ps1 -Build

# Stop the service
./scripts/start_transcription_service_docker.ps1 -Stop

# View logs
./scripts/start_transcription_service_docker.ps1 -Logs
```

**API Endpoints:**
- `POST /transcribe` - Upload WAV file, get job ID
- `GET /status/{job_id}` - Check transcription status
- `GET /download/{job_id}` - Download completed transcript
- `GET /health` - Service health and GPU status

**Performance (NVIDIA RTX 3080):**
- 1 minute audio: ~5-10 seconds
- 10 minute audio: ~30-60 seconds

**MCP Integration:**
The `transcribe-wav.py` MCP server provides agent-friendly tools that use this service:
- `transcribe_wav(filename)` - Upload and transcribe audio file
- `check_transcription_status(job_id)` - Poll job status
- `download_transcript(job_id)` - Retrieve completed transcript

CPU fallback is automatic when GPU isn't available (much slower). See [TRANSCRIPTION_SERVICE.md](vibe/TRANSCRIPTION_SERVICE.md) for detailed setup and troubleshooting.

## Event-Driven Testing Pattern

The monitor mode creates a powerful testing pattern:

1. **Write your agent logic** in a template file (`MONITOR.md`)
2. **Test manually** with `--exec` to verify behavior
3. **Enable automation** with `--monitor` - same logic, now event-driven
4. **Debug by going back to manual** - exact same execution path

This makes it trivial to develop and test autonomous agent behaviors. You're never guessing what the automated agent will do - just run it manually first.

**Example: VHF Monitor Agent**
```bash
# 1. Test: "What would the agent do with this new recording?"
./scripts/codex_container.sh --exec \
  --workspace vhf_monitor \
  "New recording detected. Transcribe and check for callsigns."

# 2. Automate: Agent now does this automatically on new recordings
./scripts/codex_container.sh --monitor \
  --watch-path vhf_monitor \
  --monitor-prompt MONITOR.md
```

The agent has access to all MCP tools (file operations, transcription, etc.), so it can perform complex workflows autonomously while remaining fully testable.

## Examples

The `examples/` directory contains sample code for working with Codex:

- **`run_codex_stream.py`** - Demonstrates streaming Codex CLI output using experimental JSON events
  ```bash
  python examples/run_codex_stream.py "list python files"
  ```
  This example shows how to parse Codex's `--experimental-json` output format for real-time message processing.

## Cleanup Helpers

To wipe Codex state quickly:

- PowerShell: `./scripts/cleanup_codex.ps1 [-CodexHome C:\path\to\state] [-RemoveDockerImage]`
- Bash: `./scripts/cleanup_codex.sh [--codex-home ~/path/to/state] [--remove-image] [--tag image:tag]`

## Requirements

- Docker Desktop / Docker Engine accessible from your shell. On Windows + WSL, enable Docker Desktop's WSL integration **and** add your user to the `docker` group (`sudo usermod -aG docker $USER`).
- No local Node.js install is required; the CLI lives inside the container.
- Building the image (or running the update step) requires internet access to fetch `@openai/codex` from npm. You can pin a version at build time via `--build-arg CODEX_CLI_VERSION=0.42.0` if desired.
- The container includes a Python 3 virtual environment at `/opt/mcp-venv` for MCP server execution with pre-installed dependencies (`aiohttp`, `fastmcp`, `tomlkit`).
- When using `--oss/-Oss`, the helper bridge tunnels `127.0.0.1:11434` inside the container to your host; just keep your Ollama daemon running as usual.
- When using `--serve/-Serve`, the gateway exposes port 4000 (configurable) for HTTP access to Codex.

## Troubleshooting

- **`permission denied` talking to Docker** – ensure your user is in the `docker` group and restart the shell; verify `docker ps` works before rerunning the scripts.
- **Codex keeps asking for login** – run `-Login`/`--login` to refresh credentials. The persisted files live under the configured Codex home (not the repo).
- **`… does not support tools` from Ollama** – switch to a model that advertises tool support or disable tool usage when invoking Codex; the OSS bridge assumes the provider can execute tool calls.
- **Reset everything** – delete the Codex home folder you configured (e.g. `%USERPROFILE%\.codex-service`) and reinstall/login.
- **Agent not responding to file changes** – Check that `--watch-path` points to the correct directory and that `MONITOR.md` exists and is readable.

Bundled servers also cover file diffing, crawling, Google/Gmail integrations, and the `radio_control.py` helper for the VHF monitor workspace (read-only status, recordings, logs, Whisper transcriptions).

### Directory Watcher

`--watch` lets the helper monitor a host directory and automatically rerun Codex whenever new artifacts appear. Typical usage:

```bash
./scripts/codex_container.sh --watch \
  --watch-path vhf_monitor \
  --watch-pattern "transcriptions.log" \
  --watch-template "New VHF transcript update in {name}." \
  --codex-arg "--model" --codex-arg "o4-mini" \
  --json-e
```

- Templates accept `{path}`, `{name}`, `{stem}` placeholders; add `--watch-include-content` to inline UTF-8 text (bounded by `--watch-content-bytes`).
- Repeat `--watch-pattern` for multiple globs, and provide `--watch-state-file` to persist seen timestamps across restarts.
- Any `--codex-arg` / `--exec-arg` flags are forwarded to each triggered `--exec` run, so you can pre-load system prompts or pick models. For example, ask Codex to call the `radio_control.transcribe_pending_recordings` MCP tool to mirror the old `auto_transcribe.py` loop from inside the container.
