# Codex Service Container Helper

[![License](https://img.shields.io/badge/license-BSD%20%2F%20Gnosis%20AI--Sovereign%20v1.3-blue.svg)](LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Security](https://img.shields.io/badge/security-reproducible%20%7C%20secured%20%7C%20auditable-brightgreen.svg)](#reproducible-secured-and-auditable)
[![GPU](https://img.shields.io/badge/GPU-CUDA%20enabled-brightgreen.svg)](vibe/TRANSCRIPTION_SERVICE.md)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-135-green.svg)](MCP/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/shell-PowerShell%20%7C%20Bash-orange.svg)]()

**Codex CLI in a box.** These scripts launch the OpenAI Codex CLI inside a **reproducible, secured, and auditable** Docker container with **135 specialized MCP tools**, GPU-accelerated transcription, event-driven monitoring, time-based scheduling, and AI-powered multi-agent orchestration. The installable helper mounts your workspace alongside persistent credentials, giving you a production-ready autonomous agent platform in minutes. **Skip ahead:** [Installer instructions →](#windows-powershell)

## System Capabilities Snapshot

- **Autonomous agent platform**: Runs Codex inside Docker with persistent session state, tool access, and GPU acceleration for Whisper transcription.
- **Three operating modes**: Terminal (exec/resume), API gateway (`--serve`), and Monitor mode for event-driven automation.
- **Unified event queue**: File changes and scheduled triggers flow through the same pipeline, keeping session context and writing `last_fired` metadata back to `.codex-monitor-triggers.json`.
- **Self-scheduling agents**: Use `monitor-scheduler.*` tools to create interval, daily, or one-shot triggers (including immediate fire-on-reload patterns) directly from Codex conversations.
- **135 MCP tools across domains**: File operations, web/search integrations, Google Workspace, maritime navigation, weather, task planners, agent-to-agent comms, and more.
- **Observability & persistence**: Trigger configuration, session IDs, and logs live alongside your workspace so behavior survives restarts and remains audit-able.

## Reproducible, Secured, and Auditable

**Reproducibility**
- **Immutable base images**: Docker ensures identical runtime environments across all deployments - same dependencies, same toolchain, same Python versions
- **Declarative configuration**: All MCP tools, dependencies, and settings defined in version-controlled files (`Dockerfile`, `requirements.txt`, `.codex-mcp.config`)
- **Pinned versions**: Codex CLI, BAML, npm packages, and Python libraries use explicit version numbers (e.g., `@openai/codex@0.58.0`)
- **Build-time validation**: MCP servers are validated during image build, catching configuration errors before runtime

**Security**
- **Isolated execution**: All agent operations run inside Docker containers with no direct host access unless explicitly mounted
- **Credential isolation**: API keys and tokens stored in `.env` files excluded from version control (`.gitignore` patterns prevent accidental commits)
- **Workspace-scoped tools**: `.codex-mcp.config` allows per-project tool activation - disable unnecessary capabilities for defense-in-depth
- **Secrets management**: Environment variables for sensitive data (Google OAuth tokens, API keys) kept outside the image and injected at runtime
- **Audit trail prevention of credential leaks**: `.wraithenv`, `*.env`, `*credentials*.json`, and OAuth tokens automatically ignored by git

**Auditability**
- **Persistent logs**: All MCP tool operations log to `/workspace/.mcp-logs/` with timestamps and structured data
- **Trigger history**: `.codex-monitor-triggers.json` records `last_fired` timestamps and execution counts for scheduled tasks
- **Session tracking**: Session IDs tie all operations together - reconstruct agent behavior across multiple runs
- **File versioning**: `gnosis-files-diff.py` creates `.gnosis_versions/` directories tracking all file modifications with diffs
- **Configuration transparency**: All active tools visible via `mcp_show_config()` - know exactly what capabilities are enabled
- **Reproducible investigations**: Session data, trigger configs, and logs survive container restarts for post-mortem analysis

## Deep Dive: Container Architecture & Capabilities

### Core Architecture
- **Reproducible runtime**: Docker containers with pinned versions ensure identical behavior across machines - `Codex@0.58.0`, `Node 24`, `Python 3.11+`, and CUDA tooling locked at build time
- **Secured by default**: Credentials isolated in `.env` files (git-ignored), API keys injected at runtime, and workspace-scoped tool activation limits attack surface
- **Codex CLI + MCP toolchain** packaged with CUDA acceleration, so every session has standardized dependencies, credentials, and GPU-ready Whisper transcription
- **Multi-agent orchestration** through Claude-powered helpers (`agent_to_agent`, `check_with_agent`, `get_next_step`) lets tasks bounce between specialists without leaving the container
- **Auditable state**: Session IDs, trigger definitions, tool logs, and file version history all persist under your mounted workspace (`/workspace` by default) for post-mortem analysis and compliance tracking

### Operating Modes at a Glance
1. **Terminal Mode** – one-shot or conversational `--exec` / `--session-id` calls. Ideal for scripting, CI, or quick manual interventions.
2. **API Mode** – `--serve` exposes REST endpoints (`POST /completion`, `GET /health`) so external systems can treat the container like a hosted LLM gateway.
3. **Monitor Mode** – `--monitor --watch-path …` turns Codex into an autonomous agent that reacts to filesystem events or scheduler triggers using prompt templates such as `monitor_prompts/MONITOR.md` or `/workspace/temp/MONITOR.md`.

### Automation Inputs
- **File-system events**: Watchdogs detect create/modify/move events, substitute metadata (`{{container_path}}`, `{{filename}}`, etc.), then feed the resulting prompt to Codex.
- **Scheduled triggers (NEW)**: Use the `monitor-scheduler.*` MCP tools to create cron-like jobs (`once`, `interval`, or `daily`). Triggers can opt into tags like `fire_on_reload` and are serialized inside `.codex-monitor-triggers.json`.

```python
create_trigger(
    watch_path="/workspace/temp",
    title="Hourly Weather Check",
    schedule_mode="interval",
    interval_minutes=60,
    prompt_text="Check NOAA marine forecast and log summary",
    tags=["fire_on_reload"]
)
```

### Tooling Surface (135 tools across categories)
- **AI orchestration**: `agent_to_agent`, `chat_with_context`, `get_next_step`, and `recommend_tool`.
- **File operations**: `gnosis-files-basic`, `gnosis-files-diff`, and `gnosis-files-search` families handle read/write, backup/diff, patching, and tree/search at scale.
- **Web & search**: Wraith-powered `gnosis-crawl.*` plus SerpAPI search utilities capture Markdown or raw HTML from the open web.
- **Productivity suites**: Google Calendar/Drive/Gmail, Slack, sticky notes, and task planners keep humans in the loop.
- **Maritime & navigation**: NOAA marine forecasts, VHF control, radio network comms, and OpenCPN integration address the sailing/VHF monitoring workflows.
- **Utilities**: Time conversions, log readers, water-cooler coordination, and transcription services (Whisper large-v3 running warm on the GPU) round out the platform.

### Key Differentiators
1. **Reproducible deployments** – Pinned versions (`Codex@0.58.0`, `Node 24`, `Python 3.11+`) and declarative config (`.codex-mcp.config`, `Dockerfile`) ensure identical behavior across machines and time
2. **Secured by design** – Credentials isolated outside version control (`.gitignore` patterns), workspace-scoped tool activation, and runtime-injected secrets prevent leaks
3. **Self-modifying agents** – Automations can create/update/delete their own triggers, sticky notes, or prompts mid-run, making adaptive schedules trivial
4. **GPU-accelerated transcription** – The Whisper large-v3 model stays loaded in VRAM, so minutes of audio process in seconds with `transcribe_wav`
5. **Unified prompt templates** – The same `MONITOR.md` prompt used for automation can be executed manually via `--exec` for deterministic testing
6. **Auditable operations** – Session IDs, trigger histories with `last_fired` timestamps, MCP tool logs, and file version tracking enable post-mortem analysis
7. **Persistent memory** – Sticky notes and trigger metadata let agents leave breadcrumbs ("Agent Lumen") for later sessions to resume safely
8. **Multi-channel communication** – Slack, Gmail, Google Calendar, and radio tools mean the agent can both ingest signals and notify humans without leaving the container

## Three Interaction Modes

The *codex-container* application supports three distinct ways to interact with the system, each suited for different workflows:

### 1. TERMINAL MODE (Exec)
Interactive or non-interactive execution for quick queries and commands.

```bash
codex-container --exec "create a new README.md based off PLAN.md" # Single command exits with session ID
codex-container --session-id abc12   # Resume interactive conversation with that ID
```

**Use Cases:**
- Quick queries and commands
- Long-running conversations via session ID
- Scripted automation
- CI/CD integration

### 2. REMOTE API MODE (Serve)
HTTP gateway for external tool access and multi-user scenarios.

```bash
codex-container --serve --gateway-port 4000
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
- Integration with external tools
- Multi-user scenarios
- Language-agnostic clients

### 3. MONITOR MODE (Monitor)
Chat sessions or event-driven autonomous agents.

```bash
codex-container --monitor --watch-path ./recordings  # Event-driven agent
```

**Event Flow:** File changes → Template substitution → Processing

**Template Variables:** `{{file}}`, `{{path}}`, `{{timestamp}}`, etc.

**Use Cases:**
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

### Scheduled Monitor Triggers

The monitor can now wake itself up on a schedule without waiting for new files. Define time-based prompts with the `monitor-scheduler` MCP tool; each watch directory persists its configuration in `.codex-monitor-triggers.json`.

- `monitor-scheduler.list_triggers(watch_path="./recordings")` – inspect current schedules and the next planned run.
- `monitor-scheduler.create_trigger(...)` – supply a `schedule_mode` (`daily`, `once`, or `interval`), timezone, and the full `prompt_text` that Codex should receive when the trigger fires. The prompt can include moustache placeholders such as `{{now_iso}}`, `{{now_local}}`, `{{trigger_title}}`, `{{trigger_time}}`, `{{created_by.name}}`, and `{{watch_root}}`.
- `monitor-scheduler.update_trigger` / `toggle_trigger` / `delete_trigger` – adjust existing entries.

While the monitor is running, it loads the trigger config, keeps a lightweight scheduler thread, and queues scheduled prompts through the same execution pipeline as file events (respecting session reuse and concurrency limits). After each run it records `last_fired` back into the config so operators can audit when a reminder last executed.

### AI-Powered Task Planning

The container includes **stateless instructor agents** that guide multi-step workflows without taking control away from Codex:

**Pattern: Instructor → Execute → Report → Repeat**

```bash
# Codex asks: "What should I do next?"
get_next_step(task="Check weather and post to Slack")
# → Returns: {"next_action": "call_tool", "tool_call": {"tool": "noaa-marine.get_forecast", ...}}

# Codex executes the suggested tool, then asks again
get_next_step(task="...", completed_steps=[{...forecast result...}])
# → Returns: {"next_action": "call_tool", "tool_call": {"tool": "slackbot.post_message", ...}}

# After final step
get_next_step(task="...", completed_steps=[...])
# → Returns: {"next_action": "complete", "summary": "Weather posted to Slack"}
```

**Key Tools:**
- `get_next_step()` - Stateless planning: gives next action based on task + progress
- `recommend_tool()` - Claude analyzes task and suggests which MCP tools to use
- `check_with_agent()` - Consult Claude with specific role/expertise
- `agent_to_agent()` - Have specialized agents consult each other

**Why this pattern?**
- **Codex stays in control** - It executes, the instructor just advises
- **Fully testable** - Each step can be run manually
- **Transparent** - User sees every decision and action
- **Adaptable** - Plan adjusts based on actual results, not assumptions

Set `ANTHROPIC_API_KEY` before use. The instructor agents use Claude 3.5 Sonnet by default.

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
  - `-Oss` tells Codex to target a locally hosted provider via `--oss` (e.g., Ollama). The helper automatically bridges `127.0.0.1:11434` inside the container to your host service—just keep Ollama running as you normally would. Set `OSS_DISABLE_BRIDGE=1` if you need to keep `--oss` but do *not* want the helper to start the bridge.
  - `-OssModel <name>` (maps to Codex `-m/--model` and implies `-Oss`) selects the model Codex should request when using the OSS provider.
  - `-OssServerUrl <url>` / `-OllamaHost <url>` forward custom endpoints to the container. Use these to point Codex at a hosted GPT-OSS cloud endpoint instead of your local Ollama daemon. (`OSS_SERVER_URL`, `OLLAMA_HOST`, and `OSS_API_KEY` environment variables are also honored.)
  - `-CodexModel <name>` forwards `--model <name>` directly to Codex without enabling `-Oss` (ideal for hosted IDs such as `kimi-k2-thinking` or `gpt-oss:120b-cloud`).
  - `-CodexArgs <value>` and `-Exec` both accept multiple values (repeat the flag or pass positionals after `--`) to forward raw arguments to the CLI.
  - `-SessionId <id>` resumes a previous session (accepts full UUID or last 5 characters)
  - `-TranscriptionServiceUrl <url>` configures the transcription service endpoint (default: `http://host.docker.internal:8765`)
  - Set `CODEX_DEFAULT_MODEL` (or `CODEX_CLOUD_MODEL`) in your shell to make the wrapper automatically pass that hosted model without toggling `-Oss`.

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
  - `--oss` forwards the `--oss` flag and the helper bridge takes care of sending container traffic to your host Ollama service automatically (export `OSS_DISABLE_BRIDGE=1` to suppress the bridge even when `--oss` is set).
  - `--model <name>` (maps to Codex `-m/--model` and implies `--oss`) mirrors the PowerShell `-OssModel` flag.
  - `--oss-server-url <url>` / `--ollama-host <url>` override the endpoint Codex should reach when `--oss` is active (or export `OSS_SERVER_URL` / `OLLAMA_HOST` / `OSS_API_KEY` before invoking the script). Leave these unset to keep the default `127.0.0.1:11434` bridge.
  - `--codex-model <name>` passes `--model <name>` to Codex without enabling `--oss`; use this for hosted/remote models like `gpt-oss:120b-cloud`.
  - `--codex-arg <value>` and `--exec-arg <value>` forward additional parameters to Codex (repeat the flag as needed).
  - `--watch-*` controls the directory watcher (see *Directory Watcher* below).
  - `--monitor [--monitor-prompt <file>]` watches a directory and, for each change, feeds `MONITOR.md` (or your supplied prompt file) to Codex alongside the file path.
  - `--session-id <id>` resumes a previous session (accepts full UUID or last 5 characters)
  - `--transcription-service-url <url>` configures the transcription service endpoint (default: `http://host.docker.internal:8765`)
  - Export `CODEX_DEFAULT_MODEL`/`CODEX_CLOUD_MODEL` to inject a remote model automatically without opting into `--oss`.
  - When using hosted GPT-OSS plans, set `OSS_SERVER_URL` (and, if required, `OSS_API_KEY`) to the HTTPS endpoint your provider gives you, then run `--oss --model gpt-oss:120b-cloud`. The helper only enables the localhost bridge when no custom endpoint is specified, so remote URLs won't trigger giant local downloads.

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

### Customizing MCP Tools Per Workspace

You can control which MCP tools are activated using `.codex-mcp.config` files:

**Default Configuration** (`MCP/.codex-mcp.config`):
- Defines the default set of tools baked into the Docker image
- Used when no workspace-specific config exists
- Edit this file and rebuild to change the default tool set

**Workspace-Specific Configuration** (`/workspace/.codex-mcp.config`):
- Place this file in your workspace root to override the default
- Only the listed tools will be loaded for that workspace
- Useful for project-specific tool subsets (e.g., only web scraping tools for a crawling project)

**Config Format**: One tool filename per line (comments with `#` supported)
```
# Core utilities
time-tool.py
calculate.py

# File operations
gnosis-files-basic.py
gnosis-files-search.py

# Web tools
gnosis-crawl.py
```

**Runtime Behavior**:
- On container start, the entrypoint checks `/workspace/.codex-mcp.config` first
- If not found, falls back to the default config from the image
- If using the default, logs a helpful message showing which tools are active and how to customize

**Example**: Create `.codex-mcp.config` in your workspace to enable only web scraping and file tools:
```bash
cat > .codex-mcp.config << 'EOF'
gnosis-crawl.py
gnosis-files-basic.py
gnosis-files-search.py
serpapi-search.py
EOF
```

### Available MCP Tools (135 total)

The container provides **135 specialized tools** spanning file operations, web scraping, AI orchestration, time-based scheduling, maritime operations, and cloud integrations. Every tool uses the FastMCP framework for reliable async execution.

**AI Orchestration & Agent Communication**
- **Agent Chat**: `check_with_agent`, `chat_with_context`, `agent_to_agent` - Multi-agent collaboration with role specialization
- **Task Planning**: `get_next_step` - Stateless instructor pattern for multi-step workflows
- **Tool Discovery**: `recommend_tool`, `list_available_tools`, `list_anthropic_models` - Claude-powered tool selection

**Time-Based Scheduling** (monitor-scheduler.py)
- **Trigger Management**: `list_triggers`, `get_trigger`, `create_trigger`, `update_trigger`, `toggle_trigger`, `delete_trigger`, `record_fire_result`
- **Schedule Modes**: Daily (specific time + timezone), Interval (every N minutes), Once (specific datetime)
- **Self-Modifying Agents**: Agents can create/modify their own schedules while running
- **Fire on Reload**: Tag triggers with `"fire_on_reload"` to execute immediately when created/enabled
- **Persistent State**: Triggers stored in `.codex-monitor-triggers.json` in watch directory

**File Operations** (gnosis-files-*.py)
- Basic: `file_read`, `file_write`, `file_stat`, `file_exists`, `file_delete`, `file_copy`, `file_move`
- Advanced: `file_diff`, `file_backup`, `file_list_versions`, `file_restore`, `file_patch`
- Search: `file_list`, `file_find_by_name`, `file_search_content`, `file_tree`, `file_find_recent`

**Web Scraping & Search**
- **Wraith Integration**: `crawl_url`, `crawl_batch`, `raw_html`, `set_auth_token`, `crawl_status` - Production web scraper with markdown conversion
- **SerpAPI**: `google_search`, `google_search_markdown`, `set_serpapi_key`, `serpapi_status` - Google search with optional page fetching

**Google Workspace Integration**
- **Calendar**: `gcal_list_events`, `gcal_create_event`, `gcal_update_event`, `gcal_delete_event`, etc.
- **Gmail**: `gmail_list_messages`, `gmail_send`, `gmail_search`, `gmail_get_thread`, `gmail_create_draft`, etc.
- **Drive**: `gdrive_list_files`, `gdrive_upload`, `gdrive_download`, `gdrive_search`, `gdrive_share`, etc.

**Communication & Collaboration**
- **Slack**: `slack_send_message`, `slack_send_image`, `slack_upload_file`, `slack_get_user`, `slack_get_channel`
- **Human Interaction**: `talk_to_human`, `report_to_supervisor`
- **Notes**: `create_sticky_note`, `read_sticky_notes`, `update_sticky_note`, `delete_sticky_note`

**Maritime & Navigation**
- **VHF Radio**: Full SDR control, monitoring, recording, and automated transcription
- **NOAA Marine**: `get_marine_forecast`, `get_marine_warnings` - Official marine weather data
- **OpenCPN Integration**: Chart plotting and navigation data access
- **Radio Networks**: Frequency management and scanning coordination

**Weather & Environment**
- **Open-Meteo**: `get_current_weather`, `get_forecast`, `get_marine_weather` - Global weather with marine conditions, wave heights, and wind data

**Development & Monitoring**
- **Logs**: `logs_tail`, `logs_list_files`, `logs_read_file`, `logs_status` - System log analysis with level filtering
- **Monitor Status**: Real-time monitoring of active processes and file watchers
- **Environment Testing**: `check_env`, `say_hello` - Anthropic API connectivity verification

**Utilities & Coordination**
- **Time**: Scheduling, timezone conversion, and temporal operations
- **Water Cooler**: Background process coordination (`wait_at_water_cooler`, `take_cups`, `recycle_cups`)
- **Transcription**: `transcribe_wav`, `check_transcription_status`, `download_transcript` - GPU-accelerated Whisper large-v3

## Key Differentiators

- **Reproducible runtime**: Pinned dependencies (`Codex@0.58.0`, `BAML@0.211.2`, locked Python packages) ensure identical behavior across deployments - rebuild the same image anytime
- **Secured credential handling**: All secrets (`.wraithenv`, `*.env`, OAuth tokens) excluded from git, injected at runtime, and scoped per-workspace
- **Self-modifying agents**: Codex can create, update, or delete its own scheduled triggers (interval, daily, once, and fire-on-reload tags) by calling the `monitor-scheduler.*` tools mid-conversation
- **Hybrid event pipeline**: File system events and scheduled triggers share a single queue, so context is preserved regardless of how work is initiated
- **Session continuity**: `.codex-monitor-session` keeps chat state across container restarts, file events, and trigger executions
- **Template-driven prompts**: `MONITOR.md` (or `MONITOR_*.md`) supports moustache variables such as `{{trigger_title}}`, `{{now_local}}`, and `{{container_path}}` so responses adapt to each event
- **Persistent, auditable state**: `.codex-monitor-triggers.json` records schedules plus `last_fired` timestamps, and structured logs show trigger detection, execution, and queue activity
- **Configuration transparency**: `.codex-mcp.config` files explicitly list active tools - inspect or modify tool capabilities per workspace with full audit trail
- **Domain-specialized tooling**: Maritime navigation, VHF radio automation, NOAA/Open-Meteo weather, and OpenCPN charting live alongside general developer tooling and cloud integrations

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
- The helper runs `docker run … --network codex-network`, so make sure that bridge network exists once per host: `docker network create codex-network`. The command is idempotent and will simply return the existing network if it is already present (`docker network ls` should list it).
- No local Node.js install is required; the CLI lives inside the container.
- Building the image (or running the update step) requires internet access to fetch `@openai/codex` from npm. You can pin a version at build time via `--build-arg CODEX_CLI_VERSION=0.42.0` if desired.
- The container includes a Python 3 virtual environment at `/opt/mcp-venv` for MCP server execution with pre-installed dependencies (`aiohttp`, `fastmcp`, `tomlkit`).
- When using `--oss/-Oss`, the helper bridge tunnels `127.0.0.1:11434` inside the container to your host; just keep your Ollama daemon running as usual.
- When using `--serve/-Serve`, the gateway exposes port 4000 (configurable) for HTTP access to Codex.

## Troubleshooting

- **`permission denied` talking to Docker** – ensure your user is in the `docker` group and restart the shell; verify `docker ps` works before rerunning the scripts.
- **`network codex-network not found`** – create the bridge network once via `docker network create codex-network` (safe to rerun). The PowerShell/Bash wrappers expect that network so the containers can talk to companion services like the transcription API.
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
