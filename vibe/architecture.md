# Architecture Overview

This workspace hosts multiple projects and utilities that together power an agent-driven api proxy ecosystem:

1. **Codex Ollama proxy (`pi-share/codex-ollama-proxy`)**
   - Axum + Reqwest-based proxy that normalizes OpenAI-style requests and forwards them to an Ollama backend (default `qwen3:8b`).
   - Supports streaming and non-streaming completions, optional auth, and environment-driven configuration (`UPSTREAM`, `MODEL`, `BIND`, `DISABLE_AUTH`, `AUTH_TOKEN`).
   - Includes a PowerShell run helper (`run-proxy.ps1`) that can either build/run locally or build/run the container via the Dockerfile.
   - Plans are in place to extend this proxy with Qdrant-backed tracking of “dreamed” endpoints and scheduling logic that spins up Codex agent runs via the node gateway (`codex_gateway.js` exposes Codex on port 4000).

2. **Codex gateway (`/workspace/codex_gateway.js` & scripts)**
   - Node-based HTTP service listening on port 4000 that launches `codex exec` runs with JSON output.
   - Manages sessions, triggers (time/file-based), worker pools, logging, and optional watcher-based scheduling.
   - Provides endpoints for completions, session discovery, prompts, nudges, and leverages `.codex-monitor-triggers.json` plus session-specific trigger files.

3. **Gnosis Forge (`/workspace/ffmpeg`)**
   - Example embodied service: a Dockerized FastAPI wrapper around FFmpeg 7.1, demonstrating how to convert synthetic API definitions into production-ready containers.
   - Contains docs, benchmarks, scripts, and examples highlighting how agents interact via multipart, JSON/base64, or binary FFmpeg calls.

4. **Auxiliary tooling**
   - Various scripts (`codex_container.*`, monitor, transcription, cleanup helpers) that configure the Codex container runtime, install MCP servers, and manage workflows.
   - Node scripts like `codex_gateway.js` expose the Codex CLI over HTTP.

Flows:

- **Agentic endpoint lifecycle**
  1. Clients `GET /endpoints` (new route to be implemented) to generate and cache handler descriptions.
  2. `POST /endpoints` queues an agent run via the Codex gateway; results are stored in Qdrant and optionally sent to callbacks.
  3. Monitoring endpoints expose cached metadata so clients can poll status or observe updates.

- **Request path**
  - Codex → gateway `/completion` POST → Rust proxy (`/v1/chat/completions`) → Ollama (via `UPSTREAM`).  
  - Proxy also intends to integrate with Qdrant for caching plans, schedule agent runs when caches expire, and eventually “dream” new endpoints programmatically.

Current goals:

- Integrate Qdrant collection in the proxy for tracking “dreamed” endpoints.
- Have the proxy consult Qdrant before invoking Codex Gateway runs, supporting callback URLs and cache monitoring.
- Keep Forge/FFmpeg docs around as reference for synthesizing future endpoints and agent workflows.
