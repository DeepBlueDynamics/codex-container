# Gnosis Container

[![License](https://img.shields.io/badge/license-BSD%20%2F%20Gnosis%20AI--Sovereign%20v1.3-blue.svg)](LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-272-green.svg)](MCP/)
[![GPU](https://img.shields.io/badge/GPU-CUDA%20enabled-brightgreen.svg)](vibe/TRANSCRIPTION_SERVICE.md)

> **An AI agent in a box.** One script launches a Docker container where Codex has access to 272 tools, can schedule its own runs, spawn sub-agents, crawl the web, watch files, and execute shell commands. You control how much power it gets.

---

## The Simple Mental Model

```
┌─────────────────────────────────────────────────────────────────┐
│  gnosis-container.ps1                                           │
│  ─────────────────────                                          │
│  Launches a Docker container running Codex with MCP tools.      │
│  That's it. Everything else is just configuration.              │
│                                                                 │
│  SANDBOXED (default)     →  Safe. Workspace access only.        │
│  -Privileged             →  Full shell access. AI goes wild.    │
│  -Serve                  →  HTTP API. Other systems call in.    │
└─────────────────────────────────────────────────────────────────┘
```

**Three ways to run it:**

| Mode | Command | What happens |
|------|---------|--------------|
| **CLI** | `pwsh ./scripts/gnosis-container.ps1 -Exec "do something"` | One-shot prompt, exits when done |
| **API** | `pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000` | HTTP server, each POST spawns a Codex run |
| **Full power** | `pwsh ./scripts/gnosis-container.ps1 -Privileged` | Container gets `--privileged`, AI controls real shell |

---

## 30-Second Quickstart

PowerShell is required to run the PowerShell script, and it's a quick install on Mac: `brew install --cask powershell` ([more info](#requirements) | [install brew](https://brew.sh))

```powershell
# 1. Create Docker network (once)
docker network create codex-network

# 2. Build the image
pwsh ./scripts/gnosis-container.ps1 -Install

# 3. Run it
pwsh ./scripts/gnosis-container.ps1 -Exec "list all markdown files and summarize them"
```

**What you get:**
```
╭───────────────────────────────────────────────────────╮
│ >_ OpenAI Codex                                       │
│                                                       │
│ model:     gpt-4.1-mini             /model to change  │
│ directory: /workspace                                 │
╰───────────────────────────────────────────────────────╯

  Tip: You can run any shell commands from codex using ! (e.g. !ls)

› I want it all.

  100% context left · ? for shortcuts
```

**Want the AI to have real power?**
```powershell
pwsh ./scripts/gnosis-container.ps1 -Privileged
```

```
› ping google

  93% context left · ? for shortcuts

✔ You approved codex to run ping -c 2 google.com this time

• Ran ping -c 2 google.com
  └ PING google.com (142.251.116.139) 56(84) bytes of data.
    64 bytes from 142.251.116.139: icmp_seq=1 ttl=63 time=42.5 ms
    64 bytes from 142.251.116.139: icmp_seq=2 ttl=63 time=38.5 ms
    2 packets transmitted, 2 received, 0% packet loss, time 999ms
```

That's it. Now the container runs with Docker's `--privileged` flag and the AI can do dangerous things in the shell it controls.

---

## What's Inside

| Capability | What it does |
|------------|--------------|
| **272 MCP tools** | Web crawling, file ops, search, Gmail/Calendar/Drive, Slack, weather, scheduling, and more |
| **Self-scheduling** | Agent can create triggers to run itself later (daily, interval, one-shot) |
| **Sub-agents** | `check_with_agent`, `agent_to_agent` — agents consulting other Claude instances |
| **File watching** | Drop a file, trigger a Codex run automatically |
| **HTTP gateway** | POST to `/completion`, get AI responses — integrate with anything ([API docs](README_API.md)) |
| **Model flexibility** | OpenAI, Anthropic, or local via Ollama |

---

## Requirements

- **Docker** (Desktop or Engine) — `docker network create codex-network` once
- **PowerShell** — Windows has it; macOS/Linux install [PowerShell Core](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (`pwsh`)
- **For Ollama/local models:** keep daemon running at `127.0.0.1:11434`; the helper bridges it into the container unless you set `OSS_SERVER_URL`
- **For GPU services:** NVIDIA + CUDA drivers

### Installing PowerShell on macOS/Linux

**macOS (Homebrew):**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install --cask powershell
```

**Ubuntu/Debian:**
```bash
sudo apt-get update && \
  sudo apt-get install -y wget apt-transport-https software-properties-common && \
  wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb" && \
  sudo dpkg -i packages-microsoft-prod.deb && \
  sudo apt-get update && \
  sudo apt-get install -y powershell
```

> The legacy Bash helper `scripts/gnosis-container.sh` remains for convenience on Unix-like systems, but feature parity is guaranteed through the PowerShell entrypoint.

---

## Operating Modes

### 1. CLI Mode — Run a prompt and exit

```powershell
# Sandboxed (safe)
pwsh ./scripts/gnosis-container.ps1 -Exec "draft release notes"

# Resume a session
pwsh ./scripts/gnosis-container.ps1 -SessionId session-123 -Exec "continue"

# Full access (dangerous)
pwsh ./scripts/gnosis-container.ps1 -Exec "install dependencies and run tests" -Danger -Privileged
```

| Flag | Effect |
|------|--------|
| `-Danger` | Removes Codex sandbox/approval prompts. Adds `--dangerously-bypass-approvals-and-sandbox` when launching Codex. |
| `-Privileged` | Runs Docker with `--privileged` (needed for file watchers or device access) |

Combine both when you want the AI to have unrestricted access. Pair them only when you fully trust the prompt.

### 2. API Gateway — HTTP interface

```powershell
pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000
```

Now POST to `http://localhost:4000/completion`:
```bash
curl -X POST http://localhost:4000/completion \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What time is it?"}]}'
```

**Endpoints:**
- `POST /completion` — run a prompt with `{ "prompt": "...", "model": "...", "workspace": "/workspace" }`
- `GET /sessions` — list all sessions
- `GET /sessions/:id` — session details
- `POST /sessions/:id/prompt` — continue a session
- `POST /sessions/:id/nudge` — replay with new metadata
- `GET /status` — concurrency, watcher, webhook info
- `GET /health` — liveness probe

Env vars: `CODEX_GATEWAY_DEFAULT_MODEL`, `CODEX_GATEWAY_TIMEOUT_MS`, `CODEX_GATEWAY_EXTRA_ARGS`

See [`README_API.md`](README_API.md) for full schemas, watcher events, and webhook payloads.

### 3. File Watcher — React to file changes

```powershell
$env:CODEX_GATEWAY_WATCH_PATHS = 'temp;inbox'
$env:CODEX_GATEWAY_WATCH_PROMPT_FILE = './MONITOR.md'
$env:CODEX_GATEWAY_WATCH_PATTERN = '**/*.txt'
pwsh ./scripts/gnosis-container.ps1 -Serve -GatewayPort 4000
```

Drop a file in `temp/` or `inbox/` → triggers a Codex run using `MONITOR.md` as the prompt template.

**Watcher env vars:**
- `CODEX_GATEWAY_WATCH_PATHS` — comma/semicolon separated paths (absolute or workspace-relative)
- `CODEX_GATEWAY_WATCH_PATTERN` — glob pattern (default `**/*`)
- `CODEX_GATEWAY_WATCH_PROMPT_FILE` — prompt template path
- `CODEX_GATEWAY_WATCH_DEBOUNCE_MS` — debounce timing
- `CODEX_GATEWAY_WATCH_USE_WATCHDOG` — use watchdog implementation

Watcher status exposed via `/` and `/status`. Use paths like `temp` instead of `./temp` on Windows PowerShell.

### 4. Scheduler — Agent schedules its own runs

The agent can use `monitor-scheduler.*` MCP tools (`create_trigger`, `toggle_trigger`, etc.) to create triggers:
- **Daily** — run at a specific time
- **Interval** — run every N minutes
- **Once** — run at a future timestamp

Triggers persist in `.codex-monitor-triggers.json`. The gateway dispatches them via the same queue as monitor/gateway runs.

---

## System Prompts

Drop a `PROMPT.md` in your workspace root. Every run picks it up automatically.

```
workspace/
├── PROMPT.md          ← system prompt for all runs
├── your-files/
└── ...
```

- Override with `CODEX_SYSTEM_PROMPT_FILE=/workspace/custom.md` (relative paths resolve from workspace)
- Disable with `CODEX_DISABLE_DEFAULT_PROMPT=1`
- The HTTP gateway reads the same env/file, so watch events, scheduler triggers, and API callers inherit the identical system prompt

---

## Security Levels

| Level | Flags | What the AI can do |
|-------|-------|-------------------|
| **Sandboxed** | *(default)* | Write to workspace, network inside sandbox only. Safe for automation. |
| **Danger** | `-Danger` | Unrestricted shell inside Codex, no approval prompts |
| **Privileged** | `-Privileged` | Docker `--privileged` — host file/device access |
| **Full power** | `-Danger -Privileged` | Everything. Use only when you trust the prompt completely. |

**Additional safety levers:**
- Allow/deny lists per tool
- Crawl depth/size/time caps; per-domain caps
- Rate and concurrency limits
- All actions logged to session files; trigger file with `last_fired`
- Backups/diffs via gnosis-files-diff
- Workspace-scoped tool config via `.codex-mcp.config` (one filename per line). Override per workspace at `/workspace/.codex-mcp.config`

---

## MCP Tools (272 and counting)

| Category | Examples |
|----------|----------|
| **Web/Search** | `gnosis-crawl.*` (markdown/HTML, JS optional, caps/allowlists), `serpapi-search.*` (low num, filters) |
| **Term Graph** | `oracle_walk_hint`, `sample_urls`, `build_term_graph`, `summarize_signals`, `save_page`/`search_saved_pages` |
| **Files** | read, write, stat, exists, delete, copy, move, diff, backup, restore, patch, list, find, search, tree, recent |
| **Scheduling** | `monitor-scheduler.*` — create/update/toggle/delete/list triggers; clock utilities |
| **Orchestration** | `agent_to_agent`, `check_with_agent`, `recommend_tool` |
| **Comms** | Gmail, Calendar, Drive, Slack, sticky notes, marketbot |
| **Data** | open-meteo weather, NOAA marine, time |
| **Audio** | elevenlabs-tts, speaker-bridge, transcribe-wav, nuts-news |

**Manage tools:**

Just ask the agent: "add the gnosis-crawl tools" or "remove serpapi" — it calls the MCP helpers (`mcp_add_tool`, `mcp_remove_tool`, `mcp_list_installed`, etc.) and updates the config for you.

You can get surprisingly specific — almost like writing code — and it still works:
```
> mcp_add_tool('my-custom-tool.py')
> mcp_remove_tool('serpapi-search.py')
> mcp_list_installed()
```

Or edit the config file directly:
```bash
# List one tool filename per line
cat /workspace/.codex-mcp.config
gnosis-crawl.py
gnosis-files.py
monitor-scheduler.py
```

If no `/workspace/.codex-mcp.config` exists, the container uses the image defaults. When you first add or remove a tool, it automatically creates the workspace config based on those defaults — you don't need to create the file manually.

After modifying the config, restart the container or rerun `-Install` so Codex reloads the MCP configuration.

---

## Optional Services

| Service | Port | Start command | Notes |
|---------|------|---------------|-------|
| Whisper transcription (GPU) | 8765 | `./scripts/start_transcription_service_docker.sh --build` | Provides `/transcribe` REST endpoint + `transcribe-wav` MCP tool. Requires NVIDIA GPU + CUDA. |
| Instructor-XL embeddings | 8787 | `./scripts/start_instructor_service_docker.sh --build` | Sets `INSTRUCTOR_SERVICE_URL`. Used by embedding-aware MCP tools. |
| Callback relay | 8088 | `./scripts/start_callback_service_docker.sh --build` | Receives session webhooks, forwards to custom URLs. Tie into `SESSION_WEBHOOK_URL`. |
| DocDB (Mongo-compatible) | 27017 | `./scripts/start_docdb_service_docker.sh --build` | Backing store for long-lived state or custom MCP tools. |
| OpenSearch + dashboards | 9200 / 9600 | `./scripts/start_opensearch_service_docker.sh --build` | Enables search/index pipelines, pairs with `open-search` MCP tools. |

All `start_*` scripts accept `--build` for first run, can run without it afterward. Stop with `--stop` or Docker Compose.

---

## Model Flexibility

```powershell
# OpenAI (default)
pwsh ./scripts/gnosis-container.ps1 -Exec "hello"

# Local/Ollama
pwsh ./scripts/gnosis-container.ps1 -Oss -Exec "hello"

# Specific model (implies -Oss)
pwsh ./scripts/gnosis-container.ps1 -Model llama3 -Exec "hello"

# Hosted model override
pwsh ./scripts/gnosis-container.ps1 -CodexModel gpt-4 -Exec "hello"
```

Env vars: `OSS_SERVER_URL`, `OLLAMA_HOST`, `OSS_API_KEY`, `CODEX_DEFAULT_MODEL`. Disable bridge with `OSS_DISABLE_BRIDGE=1`.

---

## Setup & Common Flags

| Flag | Description |
|------|-------------|
| `-Install` | Build image, register MCP tools from `MCP/`, place runner on PATH |
| `-Login` | Refresh Codex auth |
| `-Exec "prompt"` | Run single prompt |
| `-Serve` | Start HTTP gateway |
| `-GatewayPort N` | Port for gateway (default 4000) |
| `-Privileged` | Docker `--privileged` mode |
| `-Danger` | Bypass Codex sandbox/approvals |
| `-Oss` | Use local/Ollama models |
| `-Model name` | Specific model (implies `-Oss`) |
| `-CodexModel name` | Hosted model override |
| `-SessionId id` | Resume existing session |
| `-Workspace path` | Mount different workspace |
| `-CodexHome path` | Override Codex home (default `$HOME/.codex-service`) |
| `-Tag image` | Custom image tag |
| `-Push` | Push image after build |
| `-SkipUpdate` | Skip image update check |
| `-NoAutoLogin` | Don't auto-login |
| `-Json` / `-JsonE` | JSON output modes |
| `-Shell` | Drop into container shell |
| `-TranscriptionServiceUrl url` | Whisper service URL |
| `-MonitorPrompt file` | Monitor prompt file |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `permission denied` to Docker | Add user to `docker` group, restart shell; verify with `docker ps` |
| `network codex-network not found` | `docker network create codex-network` |
| Ollama tools error | Pick a model with tool support or disable tool use |
| File watcher not triggering | Check `--watch-path` and prompt file readability |
| Need fresh start | Remove Codex home (`~/.codex-service`) and rerun `-Install`/`-Login` |

### Codex update prompt

When Codex starts, you may see:
```
✨ Update available! 0.72.0 -> 0.73.0
Release notes: https://github.com/openai/codex/releases/latest

1. Update now (runs `npm install -g @openai/codex`)
› 2. Skip
```

**Always choose Skip.** The container builds Codex from the Dockerfile — running `npm install` inside the container won't persist and will break the current session. To update Codex, update the version in the Dockerfile and rebuild with `-Install`.

---

## Examples

- `examples/run_codex_stream.py` — stream Codex CLI output using `--json-e`
- `monitor_prompts/MONITOR.md` — file-event prompt template with moustache vars (`{{file}}`, `{{container_path}}`)

---

**This is agentic ops infrastructure.** Reproducible Docker images, safety levers, 272 tools, and the ability to run sandboxed or with full power. Everything logged, everything containerized. Swap between OpenAI and local models as needed.
