# Gnosis Container (agent ops stack)

[![License](https://img.shields.io/badge/license-BSD%20%2F%20Gnosis%20AI--Sovereign%20v1.3-blue.svg)](LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Security](https://img.shields.io/badge/security-reproducible%20%7C%20secured%20%7C%20auditable-brightgreen.svg)](#safety--audit-levers)
[![GPU](https://img.shields.io/badge/GPU-CUDA%20enabled-brightgreen.svg)](vibe/TRANSCRIPTION_SERVICE.md)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-272-green.svg)](MCP/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/shell-PowerShell%20%7C%20Bash-orange.svg)]()

**Automate anything, anywhere.** Codex in a container with cron jobs, file monitors, URL fetch/index, search, speech, and hundreds of tools.

**Why it matters:** This is “agentic ops” infrastructure—reproducible Docker images, safety levers, and hundreds of MCP tools (currently **272** detectable `@mcp.tool` functions) so you can ship cron jobs, file monitors, URL pipelines, and search/indexing workflows without glue-code sprawl.

- **Models:** OpenAI or local/Ollama (OSS bridge included)
- **Ingress:** gnosis-crawl (markdown/HTML, JS optional, caps/allowlists) + low-count SerpAPI wrapper
- **Automation:** monitor + scheduler (interval/daily/once), unified queue, stuck/timeout/nudge/retry/backoff
- **Noise-cutting:** term-graph `oracle_walk_hint` + `sample_urls` for allowlisted, deduped URL batches pre-crawl
- **Safety:** allow/deny, rate/concurrency caps, depth/size/time caps, logs, backups/diffs
- **Optional services:** GPU Whisper (8765), Instructor-XL (8787)

## Requirements
- Docker (Desktop/Engine). Create the network once: `docker network create codex-network` (idempotent).
- PowerShell (Windows ships with it; macOS/Linux install [PowerShell Core](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) aka `pwsh`). The legacy Bash script still exists but the PowerShell entrypoint is the supported path.
- For Ollama/local: keep your daemon running; the helper bridges `127.0.0.1:11434` into the container unless you set custom `OSS_SERVER_URL`.
- For GPU services: NVIDIA + CUDA drivers installed on host.

## PowerShell entrypoint (cross-platform)
The supported entrypoint is `scripts/gnosis-container.ps1`. Use it everywhere for consistent behavior, regardless of host OS.

### Windows
PowerShell is built in. Run commands directly from a PowerShell prompt:
```powershell
.\scripts\gnosis-container.ps1 -Install
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000
```

### macOS / Linux
Install PowerShell Core (`pwsh`) if it is not already available, then run the same script via `pwsh`:

**Install (Homebrew on macOS):**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install --cask powershell
```

**Install (Ubuntu/Debian):**
```bash
sudo apt-get update && \
  sudo apt-get install -y wget apt-transport-https software-properties-common && \
  wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb" && \
  sudo dpkg -i packages-microsoft-prod.deb && \
  sudo apt-get update && \
  sudo apt-get install -y powershell
```

**Run:**
```bash
pwsh ./scripts/gnosis-container.ps1 -Install
pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000
```

> The legacy Bash helper `scripts/gnosis-container.sh` remains for convenience on Unix-like systems, but feature parity is guaranteed through the PowerShell entrypoint.

## Quick start

### Windows (PowerShell)
```powershell
# install/update image (registers MCP tools from MCP/)
.\scripts\gnosis-container.ps1 -Install

# one-off prompt (non-interactive)
.\scripts\gnosis-container.ps1 -Exec "list markdown files"

# serve HTTP gateway on port 4000 (POST /completion)
# -Danger bypasses approval prompts and enables danger-full-access sandbox for unrestricted shell execution
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000 -Danger

# gateway file watcher (preferred in serve mode)
$env:CODEX_GATEWAY_WATCH_PATHS = 'temp'
$env:CODEX_GATEWAY_WATCH_PROMPT_FILE = '.\\MONITOR.md'
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000 -Danger
```

### macOS / Linux (PowerShell Core via `pwsh`)
```bash
pwsh ./scripts/gnosis-container.ps1 -Install
pwsh ./scripts/gnosis-container.ps1 -Exec "list markdown files"
# -Danger bypasses approval prompts and enables danger-full-access sandbox for unrestricted shell execution
pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000 -Danger
pwsh ./scripts/gnosis-container.ps1 -Monitor -WatchPath ./recordings -Danger
CODEX_GATEWAY_WATCH_PATHS=./temp \
  CODEX_GATEWAY_WATCH_PROMPT_FILE=./MONITOR.md \
  pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000 -Danger
```
Use paths like `temp` (or `/workspace/temp`) instead of `./temp` when running on Windows PowerShell because of watcher semantics.

### Legacy Bash helper (optional)
A bash port exists for historical reasons but is not actively maintained. Prefer the PowerShell entrypoint unless you have a strict Bash-only requirement. To run legacy commands:
```bash
./scripts/gnosis-container.sh --install
./scripts/gnosis-container.sh --exec "list markdown files"
./scripts/gnosis-container.sh --serve --gateway-port 4000
```

## System prompt defaults
- Place a `PROMPT.md` in your workspace root to give every session a baseline system prompt. PowerShell and Bash helpers automatically forward it to `codex` for `-Run`, `-Exec`, and `-Serve` unless you already pass `--system`/`--system-file`.
- Override the file by setting `CODEX_SYSTEM_PROMPT_FILE=/workspace/custom.md` (relative paths resolve from the workspace). The helper maps host paths to `/workspace/...` before launching the container.
- Toggle the feature off with `CODEX_DISABLE_DEFAULT_PROMPT=1` when you want a completely clean system prompt.
- The HTTP gateway (`-Serve`) reads the same env/file, so watch events, scheduler triggers, and API callers inherit the identical top-of-stack system prompt without repeating it in every request.

## Optional services
- `./scripts/start_transcription_service_docker.sh --build` — Whisper GPU @8765
- `./scripts/start_instructor_service_docker.sh --build` — Instructor-XL @8787

## Operating modes
### 1. Terminal / Exec
Default mode (no extra switches) runs a single prompt with sandboxed permissions. Examples:
```powershell
# sandboxed run
.\scripts\gnosis-container.ps1 -Exec "draft release notes"

# resume an existing session
.\scripts\gnosis-container.ps1 -SessionId session-123 -Exec "continue"

# elevated run (danger + privileged)
.\scripts\gnosis-container.ps1 -Exec "read /opt/codex-home" -Danger -Privileged
```
Use `-SessionId` (or `--session-id`) to resume. `-Danger` bypasses Codex approval prompts and enables unrestricted shell execution. `-Privileged` runs the Docker container with `--privileged` for device/filesystem access. Network access is available by default. Use `-Danger` and `-Privileged` together only when you need both unrestricted Codex sandbox AND Docker privileged mode.

### 2. API Gateway (`/completion`)
Expose Codex over HTTP:
```powershell
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000
```
Env vars like `CODEX_GATEWAY_DEFAULT_MODEL`, `CODEX_GATEWAY_TIMEOUT_MS`, `CODEX_GATEWAY_EXTRA_ARGS` tune behavior. See [`API.md`](API.md) for endpoint details.

### 3. Gateway File Watcher
Use env vars with the API gateway so file events trigger `/completion` automatically:
```powershell
$env:CODEX_GATEWAY_WATCH_PATHS = 'temp;more-files'
$env:CODEX_GATEWAY_WATCH_PROMPT_FILE = '.\MONITOR.md'
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000
```
Key envs:
- `CODEX_GATEWAY_WATCH_PATHS` (comma/semicolon separated absolute or workspace-relative paths)
- `CODEX_GATEWAY_WATCH_PATTERN` (glob, default `**/*`)
- `CODEX_GATEWAY_WATCH_PROMPT_FILE` (prompt template path)
- `CODEX_GATEWAY_WATCH_DEBOUNCE_MS`, `CODEX_GATEWAY_WATCH_USE_WATCHDOG`
Watcher status is exposed via `/` and `/status`.

### 4. Scheduler
Use the `monitor-scheduler.*` MCP tools (`create_trigger`, `toggle_trigger`, etc.) to schedule daily/interval/once prompts. Triggers live in `.codex-monitor-triggers.json`; they dispatch via the same queue as monitor/gateway runs.

## Model flexibility
- OpenAI default; pass `--oss` (or PowerShell `-Oss`) to use local/Ollama. The helper bridges host `127.0.0.1:11434` into the container; disable bridge with `OSS_DISABLE_BRIDGE=1`.
- Override model: `--model <name>` (implies `--oss`) or `--codex-model <name>` (hosted). Env vars honored: `OSS_SERVER_URL`, `OLLAMA_HOST`, `OSS_API_KEY`, `CODEX_DEFAULT_MODEL`.

## Safety & security levels
- **Default (sandboxed)**: No extra flags. Codex runs with workspace-write permissions. Network access is available by default (container uses `--network codex-network`). Codex's internal sandbox may require approval for certain operations. Safe for automation.
- **Danger mode (`-Danger`)**: Bypasses Codex approval prompts and sets `--sandbox danger-full-access` for unrestricted shell execution inside Codex. Use when you need unrestricted shell access. Note: Network access is available with or without this flag.
- **Privileged container (`-Privileged`)**: Runs Docker with `--privileged` so the container can access host devices and use advanced file system features (needed for some file-watchers or specialized hardware access). This is separate from `-Danger` and controls Docker container privileges, not Codex sandbox behavior.
- **Environment variable forwarding**: Use `env_imports` in `.codex-container.toml` to forward specific host environment variables into the container. Only variables listed in `env_imports` and present on the host will be forwarded (works with or without `-Danger`).
- Allow/deny lists per tool; crawl depth/size/time caps; per-domain caps; rate/concurrency caps.
- Logs and session history; trigger file with `last_fired`; backups/diffs via gnosis-files-diff.
- Workspace-scoped tool config via `.codex-mcp.config` (one filename per line). Default lives in the image; override per workspace at `/workspace/.codex-mcp.config`.

## Key tools (MCP highlights)
- **Web/Search:** `gnosis-crawl.*` (markdown/HTML, JS optional), `serpapi-search.*` (low num, filters).
- **Term Graph:** `oracle_walk_hint`, `sample_urls`, `build_term_graph`, `summarize_signals`, `save_page`/`search_saved_pages`.
- **Scheduler/Monitor:** `monitor-scheduler.*` (create/update/toggle/delete/list triggers; clock utilities).
- **Files:** read/write/stat/exists/delete/copy/move; diff/backup/restore/patch; list/find/search/tree/recent.
- **Orchestration:** `agent_to_agent`, `check_with_agent`, `recommend_tool`.
- **Comms/Workspace:** Gmail/Calendar/Drive, Slack, sticky notes, marketbot, time, open-meteo, etc.

## MCP tool catalog & installation
- **Count:** 272 active MCP tools (scan `MCP/`). Each workspace can opt in/out via `.codex-mcp.config`.
- **Install/Update:** `./scripts/gnosis-container.ps1 -Install` (or `--install` via Bash helper) ensures dependencies are installed inside the container. To refresh MCP Python deps only, run `./scripts/install_mcp_servers.sh`.
- **Enable/Disable:** edit `.codex-mcp.config` (one filename per line). Create `/workspace/.codex-mcp.config` to override the image defaults and list only the tools you want loaded.
- **Custom tools:** drop new MCP servers under `MCP/` and add the filename to the config. Use `pip install -r requirements.txt` (inside the image) if extra deps are required.
- **Helper commands:** `mcp_add` / `mcp_remove` / `mcp_list` (see `scripts/mcp_add.py` or CLI equivalents) make it easier to toggle tools. After modifying tool lists, restart the container or rerun `./scripts/gnosis-container.ps1 -Install` so Codex reloads the updated MCP configuration before testing.

Common categories:
- **Data ingest:** `gnosis-crawl`, `open-meteo`, `noaa-marine`, `serpapi-search`, `sticky-notes`.
- **Automation:** `monitor-scheduler`, `monitor-server`, `monitor-env`, `task-instructor`, `agent-chat`.
- **Files & storage:** `gnosis-files-*`, `open-search`, `google-drive`, `google-calendar`, `google-gmail`.
- **Comms & audio:** `elevenlabs-tts`, `speaker-bridge`, `transcribe-wav`, `nuts-news`, `marketbot`.

## Optional services
| Service | Port | Start command | Notes |
| --- | --- | --- | --- |
| Whisper transcription (GPU) | 8765 | `./scripts/start_transcription_service_docker.sh --build` (then rerun without `--build` for normal start) | Provides `/transcribe` REST endpoint + `transcribe-wav` MCP tool. Requires NVIDIA GPU + CUDA drivers if you want acceleration. |
| Instructor-XL embeddings | 8787 | `./scripts/start_instructor_service_docker.sh --build` | Sets `INSTRUCTOR_SERVICE_URL=http://instructor-service:8787/embed` (container) or `http://localhost:8787/embed` (host). Used by embedding-aware MCP tools. |
| Callback relay (monitor webhooks) | 8088 | `./scripts/start_callback_service_docker.sh --build` | Receives session webhooks, forwards to custom URLs. Tie into `SESSION_WEBHOOK_URL`. |
| DocDB (Mongo-compatible) | 27017 | `./scripts/start_docdb_service_docker.sh --build` | Backing store for long-lived state or custom MCP tools needing Mongo. |
| OpenSearch + dashboards | 9200 / 9600 | `./scripts/start_opensearch_service_docker.sh --build` | Enables search/index pipelines, pairs with `open-search` MCP tools. |
| Instructor/copernicus aux services | see respective scripts | `./scripts/start_instructor_service_docker.sh`, `./scripts/start_copernicus_service_docker.ps1` etc. | Check `scripts/start_*` for additional optional stacks (radio, OCR, etc.). |

> All `start_*` scripts accept `--build` for the first run (builds images) and can be run without it afterward. Stop services with `--stop` or Docker Compose commands. |

## Examples
- `examples/run_codex_stream.py` — stream Codex CLI output using `--json-e`.
- `monitor_prompts/MONITOR.md` — template for file-event agents (moustache vars like `{{file}}`, `{{container_path}}`).

## Setup notes
- `-Install` builds the image, registers MCP servers from `MCP/`, and places a runner on PATH.
- `-Login` refreshes Codex auth if needed.
- Override Codex home: `-CodexHome <path>` (default `$HOME/.codex-service`, Windows `%USERPROFILE%\.codex-service`).
- Common flags: `-Workspace <path>`, `-Tag <image>`, `-Push`, `-SkipUpdate`, `-NoAutoLogin`, `-Json`, `-JsonE`, `-Shell`, `-TranscriptionServiceUrl <url>`, `-MonitorPrompt <file>`, `-Danger`, `-Privileged`.
- System prompt control: drop a `PROMPT.md` next to your workspace, override with `CODEX_SYSTEM_PROMPT_FILE`, or disable via `CODEX_DISABLE_DEFAULT_PROMPT=1`. The runner injects it for CLI runs and exports the path for gateway/API calls.

## Gateway usage
- Serve API: `./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000` (or `pwsh ./scripts/gnosis-container.ps1 ...` on macOS/Linux).
- POST `/completion` with `{ "prompt": "...", "model": "...", "workspace": "/workspace" }` to trigger jobs.
- Use `/sessions` endpoints to list/detail/search runs, `/sessions/:id/prompt` to continue, `/sessions/:id/nudge` to replay with new metadata.
- `/status` exposes concurrency, watcher, webhook info; `/health` is a liveness probe.
- See [`API.md`](API.md) for full schemas, watcher events, and webhook payloads.

### Gateway file watcher
Set env vars before `-Serve` to turn on file-triggered completions:
```powershell
$env:CODEX_GATEWAY_WATCH_PATHS = 'temp;more-files'
$env:CODEX_GATEWAY_WATCH_PROMPT_FILE = '.\MONITOR.md'
$env:CODEX_GATEWAY_WATCH_PATTERN = '**/*.txt'
.\scripts\gnosis-container.ps1 -Serve -GatewayPort 4000
```
- `CODEX_GATEWAY_WATCH_PATHS`: comma/semicolon separated absolute or workspace-relative paths.
- `CODEX_GATEWAY_WATCH_PATTERN`: optional glob for matched files (default `**/*`).
- `CODEX_GATEWAY_WATCH_PROMPT_FILE`: prompt template to use per event.
- `CODEX_GATEWAY_WATCH_DEBOUNCE_MS`, `CODEX_GATEWAY_WATCH_USE_WATCHDOG`: tune frequency/implementation.
Watcher health/status is reported in `/` and `/status` responses.

## Troubleshooting
- `permission denied` to Docker: add your user to `docker` group, restart shell; verify `docker ps`.
- `network codex-network not found`: run `docker network create codex-network` once.
- Ollama tools error: pick a model with tool support or disable tool use.
- Agent not firing on changes: check `--watch-path` and prompt file readability.
- Reset: remove Codex home (e.g., `~/.codex-service`) and rerun `--install`/`--login`.

---
This stack is for semi-technical operators who want AI agents to do real work—crawling, scheduling, deduping URLs, and shipping outputs—without fighting dependencies or losing control. Everything runs in containers, every action is logged, and you can swap between OpenAI and local models as needed.
