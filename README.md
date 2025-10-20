# Codex Service Container Helper

These scripts launch the OpenAI Codex CLI inside a reproducible Docker container. Drop either script somewhere on your `PATH`, change into any project, and the helper mounts the current working directory alongside a persistent Codex home so credentials survive between runs.

## Codex Home Directory

By default the container mounts a user-scoped directory as its `$HOME`:

- Windows PowerShell: `%USERPROFILE%\.codex-service`
- macOS / Linux / WSL: `$HOME/.codex-service`

This folder holds Codex authentication (`.codex/`), CLI configuration, and any scratch files produced inside the container. You can override the location in two ways:

1. Set `CODEX_CONTAINER_HOME` before invoking the script.
2. Pass an explicit flag (`-CodexHome <path>` or `--codex-home <path>`).

Relative paths are resolved the same way your shell would (e.g. `./state`, `~/state`).

Both scripts expand `~`, accept absolute paths, and create the directory if it does not exist. If you previously used the repo-local `codex-home/` folder, move or copy its contents into the new location and delete the old directory when you’re done.

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

### Monitor Mode

`--monitor` is a lightweight polling loop that reads a prompt from `MONITOR.md` (or `--monitor-prompt`) inside the watched directory and reruns Codex whenever files change:

```bash
./scripts/codex_container.sh --monitor \
  --watch-path vhf_monitor \
  --monitor-prompt MONITOR.md \
  --codex-arg "--model" --codex-arg "o4-mini"
```

PowerShell variant:

```powershell
cd C:\Users\kord\Code\gnosis\codex-container
./scripts/codex_container.ps1 -Monitor -WatchPath ..\vhf_monitor -CodexArgs "--model","o4-mini"
```

- Templating: within the prompt, use tokens such as `{{file}}`, `{{directory}}`, `{{full_path}}`, `{{relative_path}}`, `{{container_path}}`, `{{container_dir}}`, `{{extension}}`, `{{action}}`, `{{timestamp}}`, `{{watch_root}}`, `{{old_file}}`, `{{old_full_path}}`, `{{old_relative_path}}`, `{{old_container_path}}`; they expand per event before running Codex.
- Every update in the directory triggers `codex exec …` using the templated prompt (no manual scripting required).
- Combine with `radio_control` MCP tools (e.g., ask the prompt to call `transcribe_pending_recordings`) for end-to-end automation without writing new host scripts.
