# Codex Gateway API

HTTP service implemented by `scripts/codex_gateway.js`. Default bind is `0.0.0.0:4000` (override with `CODEX_GATEWAY_PORT` and `CODEX_GATEWAY_BIND`). All endpoints speak JSON. Large requests are limited by `CODEX_GATEWAY_MAX_BODY_BYTES` (default 1 MiB).

## Authentication
The gateway does not enforce authentication by default. You can front it with your own auth proxy or use the secure session directory/token (`CODEX_GATEWAY_SECURE_SESSION_DIR`, `CODEX_GATEWAY_SECURE_TOKEN`) for session replays.

## Endpoints

### `GET /health`
- Returns `{ "status": "ok" }`.
- Useful for container liveness checks.

### `GET /`
- Returns gateway metadata:
  - watcher configuration (if file watcher active)
  - webhook configuration summary
  - current environment highlights (session dirs, sandbox flags)
  - list of available endpoints

Example response:
```json
{
  "status": "codex-gateway",
  "watcher": { "enabled": false, ... },
  "webhook": { "configured": false, ... },
  "env": { "CODEX_GATEWAY_SESSION_DIRS": ["/opt/codex-home/.codex/sessions"], ... },
  "endpoints": {
    "health": "/health",
    "status": "/status",
    "completion": { "path": "/completion", "method": "POST" },
    "sessions": {
      "list": { "path": "/sessions", "method": "GET" },
      "detail": { "path": "/sessions/:id", "method": "GET" },
      "search": { "path": "/sessions/:id/search", "method": "GET" },
      "prompt": { "path": "/sessions/:id/prompt", "method": "POST" },
      "nudge": { "path": "/sessions/:id/nudge", "method": "POST" }
    }
  }
}
```

### `GET /status`
- Includes concurrency stats, uptime, memory usage, and same watcher/webhook/env summary as `/`.
- Response includes:
  - `concurrency.active`, `concurrency.max`, `concurrency.available`
  - `uptime` (seconds)
  - `memory` (NodeJS memoryUsage output)

### `POST /completion`
Launches a Codex job.

**Request body:**
```json
{
  "prompt": "<string>",
  "model": "<optional model override>",
  "workspace": "<path inside container, default /workspace>",
  "session_id": "<optional existing session>",
  "system_prompt": "<optional system message>",
  "env": { "MY_VAR": "value" },
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "timeout_ms": 120000,
  "json_mode": false,
  "metadata": { ... }
}
```
Fields:
- `prompt`: plain string prompt (ignored if `messages` provided).
- `messages`: optional chat-style conversation. If provided, overrides `prompt`.
- `system_prompt`: optional instructions prepended to the conversation.
- `workspace`: directory to use as Codex working dir (default `/workspace`).
- `model`: override default model (falls back to `CODEX_GATEWAY_DEFAULT_MODEL`).
- `session_id`: reuse existing session (otherwise new session is created).
- `env`: optional per-run environment overrides (applies only to this Codex/MCP subprocess; does not persist).
- `timeout_ms`: overrides request timeout (capped by `CODEX_GATEWAY_MAX_TIMEOUT_MS`).
- `json_mode`: when true, adds `CODEX_GATEWAY_JSON_FLAG` (defaults to `--experimental-json`).
- `metadata`: arbitrary object persisted with the run.

**Response:**
```json
{
  "session_id": "session-123...",
  "gateway_session_id": "session-123...",
  "model": "gpt-4o-mini",
  "output": "...",
  "messages": [...],
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 321,
    "cached_input_tokens": 0,
    "total_tokens": 1555
  },
  "logs_path": "/opt/codex-home/.codex/sessions/gateway/session-...",
  "metadata": { ... }
}
```
Errors:
- `400` invalid payload or body too large.
- `408` timeout (job exceeded timeout).
- `429` concurrency limiter triggered (controlled by `CODEX_GATEWAY_MAX_CONCURRENT`).
- `500` Codex execution failure.

### `GET /sessions`
Lists known gateway sessions. Query params:
- `limit` (default 50, max 200)
- `since` (ISO timestamp to filter sessions modified after time)

Response is a JSON array of session summaries (`session_id`, `dir`, `modified`, `metadata`, etc.).

### `GET /sessions/:id`
Returns detailed info for one session, including metadata, run history, and file paths. Accepts `tail_lines` query param (default `CODEX_GATEWAY_DEFAULT_TAIL_LINES`).

### `GET /sessions/:id/search`
Search within a session’s logs. Query params:
- `q` (required search string)
- `fuzzy=true` (optional)
- `tail_lines` (cap log snippet length)

Response lists matching log segments with context and file references.

### `POST /sessions/:id/prompt`
Send a follow-up prompt to an existing session. Request body:
```json
{
  "prompt": "...",
  "system_prompt": "optional",
  "timeout_ms": 60000
}
```
Response mirrors `/completion`.

### `POST /sessions/:id/nudge`
Re-run a session’s last prompt with optional updated metadata or messages. Body can include `prompt`, `messages`, or `metadata` to override.

### `GET /sessions/:id/files` *(legacy)*
If enabled in your config, this lists files under the session directory. Disabled by default.

### Watcher Events
If `CODEX_GATEWAY_WATCH_PATHS` is set, the gateway monitors those paths (using either Node watchers or polling). File events spawn `/completion` requests using `WATCH_PROMPT_FILE` or a built-in prompt. Watcher status is exposed via `/` and `/status`.

### Session Webhooks
If `SESSION_WEBHOOK_URL` is set, the gateway posts JSON payloads when sessions complete. Payload includes `session_id`, `workspace`, `prompt`, `output`, `usage`, and any metadata. Configure headers via `SESSION_WEBHOOK_HEADERS_JSON`, bearer token via `SESSION_WEBHOOK_AUTH_BEARER`, timeout via `SESSION_WEBHOOK_TIMEOUT_MS`.

## Environment Variables Summary
- `CODEX_GATEWAY_PORT`, `CODEX_GATEWAY_BIND`
- `CODEX_GATEWAY_TIMEOUT_MS`, `CODEX_GATEWAY_MAX_TIMEOUT_MS`
- `CODEX_GATEWAY_DEFAULT_MODEL`, `CODEX_GATEWAY_EXTRA_ARGS`, `CODEX_GATEWAY_JSON_FLAG`
- `CODEX_GATEWAY_SESSION_DIRS`, `CODEX_GATEWAY_SECURE_SESSION_DIR`, `CODEX_GATEWAY_SECURE_TOKEN`
- `CODEX_GATEWAY_MAX_BODY_BYTES`, `CODEX_GATEWAY_MAX_CONCURRENT`
- `CODEX_GATEWAY_WATCH_*` (paths, pattern, prompt file, debounce, poll, watchdog toggle)
- `SESSION_WEBHOOK_URL`, `SESSION_WEBHOOK_TIMEOUT_MS`, `SESSION_WEBHOOK_AUTH_BEARER`, `SESSION_WEBHOOK_HEADERS_JSON`
- `CODEX_SANDBOX_NETWORK_DISABLED` (passed through to Codex CLI)

Refer to `scripts/codex_gateway.js` for complete options and defaults.

## CLI REPL (`scripts/codex-repl.py`)

Interactive helper for calling the gateway:
```bash
python scripts/codex-repl.py http://localhost:4000
```

Commands:
- `run <prompt>` — call `/completion`
- `list` — list sessions
- `show <id> events|triggers` — fetch a session (with events or trigger extraction)
- `search <id> <phrase> [--f]` — search a session
- `prompt <id> <text>` — resume a session
- `use <id>` — pin a session for subsequent runs
- `timeout <seconds>` — adjust default timeout
- `mode <full|compact>` — toggle compact output (shows reasoning/agent messages and command output)
- `watch <keys...>` — in compact mode, also show these top-level response keys (e.g., `watch usage model`); `watch clear` to reset
- `help`, `clear`, `exit|quit`

Examples:
```
codex> mode compact
codex> watch usage model
codex> run hello world
```
Compact mode prints reasoning/agent messages (and command outputs) instead of full JSON; watched keys are shown as a summary.
