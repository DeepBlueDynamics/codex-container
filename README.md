# Gnosis Container (OpenAI-first, local-friendly)

A safe, auditable agent runtime that turns LLMs (OpenAI or local/Ollama) into reliable automations—containerized, observable, and PR-first. Built for individuals and teams needing repeatable workflows with strict guardrails, reproducible images, and controlled web ingress.

## What & Why
- OpenAI-first, local-friendly: run OpenAI or swap to local/Ollama models without changing the pattern.
- Personal + team automation that is observable, reversible, and permissioned (PR-only writes by default).
- Controlled ingestion: gnosis-crawl (markdown-only, caps/allowlists) and low-count SerpAPI with post-filters.
- Proven in noisy pipelines (alerting/extraction): job state machine, retries, nudge/timeout handling, URL dedup, batch APIs.

## Pillars
1) **Safety/Audit**: allow/deny lists, rate & concurrency caps, depth/size/time caps, PR-first writes, session/tool-call logs, diff/backup.
2) **Reproducibility**: containerized Codex CLI + MCP tools; deterministic configs; optional GPU services.
3) **Controlled Web Ingress**: gnosis-crawl (enhanced markdown, JS optional) + SerpAPI wrapper (small `num`, filters).
4) **Automation Runtime**: scheduler/monitor with interval/daily/once triggers, stuck/timeout detection, nudges, retries/backoff.
5) **Pre-filtered Search**: term-graph tools with oracle_walk_hint + sample_urls for deduped, allowlisted URL sets before crawling.
6) **Model Flexibility**: OpenAI or local/Ollama endpoints; swap without redesigning automations.

## What’s Included (MCP highlights)
- Files: read/write/diff/backup/search/tree.
- Web: gnosis-crawl (markdown/HTML), SerpAPI search.
- Scheduling: monitor-scheduler (create/update/toggle triggers, clock utilities).
- Orchestration: agent_to_agent, check_with_agent, recommend_tool.
- Term graph tools: build/update graph, propose queries, filter URLs, summarize signals, oracle-guided sampling + Monte Carlo sampler.
- Extras: Gmail/Calendar/Drive, Slack, sticky notes, marketbot, time, etc.

## Optional Services
- **GPU Whisper transcription** (cached large-v3) on 8765.
- **Instructor-XL embedding service** on 8787.  
  - In-container: `INSTRUCTOR_SERVICE_URL=http://instructor-service:8787/embed`  
  - Host: `http://localhost:8787/embed`

## Quick Start
```bash
# Serve the gateway (default port 4000)
./scripts/codex_container.sh --serve

# Run a prompt once
./scripts/codex_container.sh --exec "list markdown files"

# Start transcription (GPU)
./scripts/start_transcription_service_docker.sh --build

# Start Instructor-XL (GPU)
./scripts/start_instructor_service_docker.sh --build
```

## Safety & Audit Levers
- Allow/deny lists; rate/concurrency caps; crawl depth/size/time caps.
- Full logs & session history; trigger file with `last_fired`; file backups/diffs.
- PR-first ethos for code/config changes; explicit approvals for writes.

## Demo Recipe (for skeptics)
- Show a single bounded automation: read-only crawl + summarize with visible caps/logs.
- Show failure handling: stuck/timeout/nudge/retry surfaced in logs.
- Show control: allowlist, off-switch, PR-only writes, audit export.
