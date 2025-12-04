# Gnosis Container (agent ops stack)

[![License](https://img.shields.io/badge/license-BSD%20%2F%20Gnosis%20AI--Sovereign%20v1.3-blue.svg)](LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Security](https://img.shields.io/badge/security-reproducible%20%7C%20secured%20%7C%20auditable-brightgreen.svg)](#safety--audit-levers)
[![GPU](https://img.shields.io/badge/GPU-CUDA%20enabled-brightgreen.svg)](vibe/TRANSCRIPTION_SERVICE.md)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-219-green.svg)](MCP/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Shell](https://img.shields.io/badge/shell-PowerShell%20%7C%20Bash-orange.svg)]()

**Automate anything, anywhere.** Codex in a container with cron jobs, file monitors, URL fetch/index, search, speech, and hundreds of tools.

**Why it matters:** This is an “AI infra you can actually run” package—reproducible Docker images, safety levers, and hundreds of MCP tools (currently **219** detectable `@mcp.tool` functions) so you can ship cron jobs, file monitors, URL pipelines, and search/indexing workflows without glue-code sprawl.

- **Models:** OpenAI or local/Ollama (OSS bridge included)
- **Ingress:** gnosis-crawl (markdown/HTML, JS optional, caps/allowlists) + low-count SerpAPI wrapper
- **Automation:** monitor + scheduler (interval/daily/once), unified queue, stuck/timeout/nudge/retry/backoff
- **Noise-cutting:** term-graph `oracle_walk_hint` + `sample_urls` for allowlisted, deduped URL batches pre-crawl
- **Safety:** allow/deny, rate/concurrency caps, depth/size/time caps, logs, backups/diffs
- **Optional services:** GPU Whisper (8765), Instructor-XL (8787)

## Requirements
- Docker (Desktop/Engine). Create the network once: `docker network create codex-network` (idempotent).
- Bash or PowerShell. No local Node/Python needed beyond Docker.
- For Ollama/local: keep your daemon running; the helper bridges `127.0.0.1:11434` into the container unless you set custom `OSS_SERVER_URL`.
- For GPU services: NVIDIA + CUDA drivers installed on host.

## Quick start (Bash)
```bash
# install/update image, register MCP tools
./scripts/codex_container.sh --install

# run a one-off prompt
./scripts/codex_container.sh --exec "list markdown files"

# serve an HTTP gateway (chat-completions style) on port 4000
./scripts/codex_container.sh --serve --gateway-port 4000

# monitor a folder and react to file changes using MONITOR.md
./scripts/codex_container.sh --monitor --watch-path ./recordings

# start optional services
./scripts/start_transcription_service_docker.sh --build   # Whisper GPU @8765
./scripts/start_instructor_service_docker.sh --build       # Instructor-XL @8787
```

PowerShell equivalents live in `scripts/codex_container.ps1` (`-Install`, `-Exec`, `-Serve`, `-Monitor`, etc.).

## Operating modes
1) **Terminal / Exec** — `--exec "..."` or `--session-id <id>` to resume. Good for CI, scripts, quick runs.
2) **API Gateway** — `--serve --gateway-port 4000` exposes `/completion` and `/health` for external callers.
3) **Monitor** — `--monitor --watch-path ... [--monitor-prompt MONITOR.md]` for event-driven agents reacting to file changes.
4) **Scheduler** — via `monitor-scheduler.*` MCP tools: interval/daily/once triggers stored in `.codex-monitor-triggers.json` with `last_fired` metadata; same queue as monitor events.

## Model flexibility
- OpenAI default; pass `--oss` (or PowerShell `-Oss`) to use local/Ollama. The helper bridges host `127.0.0.1:11434` into the container; disable bridge with `OSS_DISABLE_BRIDGE=1`.
- Override model: `--model <name>` (implies `--oss`) or `--codex-model <name>` (hosted). Env vars honored: `OSS_SERVER_URL`, `OLLAMA_HOST`, `OSS_API_KEY`, `CODEX_DEFAULT_MODEL`.

## Safety levers
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

## Optional services
- **Whisper transcription (GPU)**: port 8765. REST + `transcribe-wav` MCP.
- **Instructor-XL embeddings**: port 8787. Set `INSTRUCTOR_SERVICE_URL=http://instructor-service:8787/embed` inside the container (host: `http://localhost:8787/embed`).

## Examples
- `examples/run_codex_stream.py` — stream Codex CLI output using `--json-e`.
- `monitor_prompts/MONITOR.md` — template for file-event agents (moustache vars like `{{file}}`, `{{container_path}}`).

## Setup notes (Bash)
- `--install` builds the image, registers MCP servers from `MCP/`, and places a runner on PATH.
- `--login` refreshes Codex auth if needed.
- Override Codex home: `--codex-home /path/to/state`. Default: `$HOME/.codex-service` (PowerShell: `%USERPROFILE%\.codex-service`).
- Common flags: `--workspace <path>`, `--tag <image>`, `--push`, `--skip-update`, `--no-auto-login`, `--json` / `--json-e`, `--shell`, `--transcription-service-url <url>`, `--monitor-prompt <file>`.

## Gateway usage
```bash
./scripts/codex_container.sh --serve --gateway-port 4000
# POST /completion with {"prompt": "...", "model": "...", "workspace": "/workspace"}
```
Env tweaks: `CODEX_GATEWAY_DEFAULT_MODEL`, `CODEX_GATEWAY_TIMEOUT_MS`, `CODEX_GATEWAY_EXTRA_ARGS`.

## Troubleshooting
- `permission denied` to Docker: add your user to `docker` group, restart shell; verify `docker ps`.
- `network codex-network not found`: run `docker network create codex-network` once.
- Ollama tools error: pick a model with tool support or disable tool use.
- Agent not firing on changes: check `--watch-path` and prompt file readability.
- Reset: remove Codex home (e.g., `~/.codex-service`) and rerun `--install`/`--login`.

---
This stack is for semi-technical operators who want AI agents to do real work—crawling, scheduling, deduping URLs, and shipping outputs—without fighting dependencies or losing control. Everything runs in containers, every action is logged, and you can swap between OpenAI and local models as needed.
