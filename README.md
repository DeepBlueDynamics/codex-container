# Codex Agent Ops Stack (OpenAI-first)

Safe, auditable agent runtime that wraps OpenAI models with strict guardrails, reproducible containers, and controlled web ingress. Built to ship dependable personal and team automations that enterprises will accept (PR-only changes, allow/deny lists, rate caps, full logs).

## Why this exists
- Teams resent “AI mandates” because the tools were unreliable and opaque. Codex makes automations observable, reversible, and permissioned.
- OpenAI-first: we turn your models into safe, supervised agents with bounded tools, reproducible images, and audit trails.
- Proven in noisy tasks (MarketBot-style alerting and extraction): job state machine, retries, nudge/timeout handling, URL dedup, structured outputs, and batch APIs.

## What you get
- **Safe agent runtime**: Dockerized Codex CLI + MCP tools; explicit tool scopes; allow/deny lists; rate/concurrency caps; PR-only writes.
- **Controlled web ingress**: gnosis-crawl (markdown extraction, timeouts, size caps, allowlists), SerpAPI wrapper with low result counts and filters.
- **Scheduler + monitor**: interval/daily/once triggers, debounced file watchers, stuck/timeout detection, nudge/resume, retries with backoff.
- **Personal/Team automations**: opt-in, read-first (summaries/digests) then low-risk actions with approvals. Everything logged and replayable.
- **Observability**: session logs, tool-call history, trigger file with `last_fired`, diff/backup tools, exportable audit trails.
- **Optional services**: GPU Whisper transcription (cached large-v3) on 8765; Instructor XL embedding service on 8787.

## High-signal defaults
- Web: enhanced markdown only, no assets, size/time caps, depth 0/1, allowlists, per-domain caps, backoff on 429/5xx.
- Search: SerpAPI with small `num`, no auto-fetch; post-filter by allowlist and per-domain cap.
- Writes: favor PR-only; otherwise require explicit approval paths.
- Failure policy: stuck/timeout detection, nudges (capped), retries with backoff, loud errors.

## Modes
- **Terminal**: `./scripts/codex_container.sh --exec "…"` or `--session-id <id>`.
- **API Gateway**: `./scripts/codex_container.sh --serve --gateway-port 4000` (session listing, prompt, search, nudge). Secure access enforced.
- **Monitor/Scheduler**: `--monitor --watch-path …` plus time-based triggers (interval/daily/once) sharing the same queue.

## Key tools (MCP)
- Files: read/write/diff/backup/search/tree.
- Web: gnosis-crawl (markdown/HTML), SerpAPI search.
- Scheduling: monitor-scheduler (create/update/toggle triggers, clock utilities).
- Agent orchestration: agent_to_agent, check_with_agent, recommend_tool.
- Extras: Gmail/Calendar/Drive, Slack, sticky notes, time, marketbot, etc.
- Term graph tools: build/update graphs, propose queries, filter URLs, summarize signals; **oracle-guided sampling (`oracle_walk_hint`) and Monte Carlo sampler (`sample_urls`)** when enabled.

## Optional services (compose helpers)
- Transcription (Whisper large-v3, GPU): `./scripts/start_transcription_service_docker.sh --build` (port 8765).
- Instructor XL embedding: `./scripts/start_instructor_service_docker.sh --build` (port 8787).  
  - Inside the Codex container, set `INSTRUCTOR_SERVICE_URL=http://instructor-service:8787/embed` (service DNS on `codex-network`).  
  - From the host, use `http://localhost:8787/embed`.

## Quick start
```bash
# Serve the gateway (default port 4000)
./scripts/codex_container.sh --serve

# Run a prompt once
./scripts/codex_container.sh --exec "list markdown files"

# Start transcription service (GPU)
./scripts/start_transcription_service_docker.sh --build

# Start Instructor XL service (GPU)
./scripts/start_instructor_service_docker.sh --build
```

## Safety & audit levers
- Allow/deny lists per tool; rate/concurrency caps; depth/size/time caps for crawling.
- Full logs and session history; trigger file with `last_fired`; file backups/diffs.
- PR-first ethos for code/config changes; explicit approvals for writes.

## What to demo to OpenAI (or AI-skeptical orgs)
- A single, bounded automation: read-only crawl + summarize with visible logs and caps.
- Show failure modes: stuck/timeout/nudge/retry, and how they are surfaced.
- Prove control: allowlist, off-switch, PR-only changes, audit export.
