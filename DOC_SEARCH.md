# Codex Search Agent Setup

The goal: users can speak in plain language (e.g., “save this page” or “search saved stuff for X”) and Codex will infer what to crawl, index, and retrieve.

This doc explains how to set up and use the page search/index tools (URL and content) with embeddings, plus how to start the crawler service.

## Overview
The search stack is built around the MCP personal search tools:
- `personal_search.save_page`: store a page (URL + text) in a JSONL index.
- `personal_search.save_url`: store URL bookmarks with optional notes.
- `personal_search.search_saved_pages`: semantic search over saved pages.
- `personal_search.search_saved_urls`: substring search over saved URLs/notes.
- `personal_search.count_saved_pages`, `personal_search.count_saved_urls`: counts.

Default index files:
- Pages: `temp/page_index.jsonl`
- URLs: `temp/url_index.jsonl`

Embeddings are optional. If no embedding backend is available, the tools fall back to a deterministic hash embedding (works, but less semantic).

## Embeddings Service (Instructor)
The preferred embedding backend is `instructor-xl` via the Instructor service container.

1) Ensure the Docker network exists:
```bash
docker network create codex-network
```

2) Start the instructor service:
```bash
docker compose -f docker-compose.instructor.yml up -d
```

3) Set the service URL (only if you need to override defaults):
- Default inside Docker network: `http://instructor-service:8787/embed`
- If running tools from host: `http://localhost:8787/embed`

Example env override:
```bash
export INSTRUCTOR_SERVICE_URL=http://localhost:8787/embed
```

Health check:
```bash
curl http://localhost:8787/health
```

## Crawler Service (gnosis-crawl)
The crawler is used to fetch and clean web pages before indexing.

Repo: https://github.com/deepbluedynamics/gnosis-crawl

The MCP tool defaults to the local service at `http://gnosis-crawl:8080`.
Make sure the service is running on the `codex-network`.

If you need a quick status check:
```
crawl status?
```
Tool: `gnosis-crawl.crawl_status`

## Tool Installation (MCP)
Users do not need to manage tools. They can use plain language and Codex container will route and configure the right tools automatically.

```ensure the gnosis crawl tool is added for mcp```

If you need Google search for things, sign up for [SerpAPI](https://serpapi.com), get a key then do this:

```ensure the serpapi tool is added for mcp and take this key to configure: [pasted key]```

## Indexing Pages (URLs + Content)
Users only need to speak plainly. Examples:
- “Save this page.” (Codex will crawl, clean, and index it.)
- “Bookmark this URL with a note about budget.” (Codex will save the URL + note.)
- “Save the last 3 pages I opened.” (Codex will crawl and index each.)

Behind the scenes, Codex handles:
1) Identify the target URL(s).
2) Crawl/clean content.
3) Save with embeddings.
4) Confirm with a short summary.

## Searching the Index
Users only need to ask. Examples:
- “Search saved stuff for bradycardia on amlodipine.”
- “Find anything I saved about vector search.”
- “Show me the top 5 most relevant saved pages about Microsoft.”

## Notes
- If the embedding service is down, the tools will still work but will fall back to hash embeddings.
- You can override index paths via `log_path` for per-project indexes.
- If you ingest PDFs, use `pdf-reader` to split/convert pages to text before saving with `save_page`.
