# Codex Search Agent Setup

Use Codex plus a few lightweight Python tools to build a solid search index — including PDFs with page numbers — without making you learn any APIs. Just say “save this page” or “search saved stuff for X,” and Codex handles crawling, indexing, and retrieval.

Before using search, install and run Codex using the container-based workflow in [`README.md`](../../README.md). You’ll need Docker running locally (e.g., Docker Desktop).

This doc covers the search/index workflow (URLs + content + embeddings) and how to start the crawler service.

Custom configs: this directory includes a minimal `.codex-mcp.config`, `.serpapi.env`, and `.codex-container.toml`. Copy those into your workspace if you want a lightweight tool set focused on search.

Recommended workflow: `cd` into `examples/personal_search` and run the container from there so the local configs are picked up:
```powershell
cd examples/personal_search
pwsh ../../scripts/gnosis-container.ps1 -Install
pwsh ../../scripts/gnosis-container.ps1 -Exec "save this page: https://news.ycombinator.com/newest"
pwsh ../../scripts/gnosis-container.ps1 -Exec "from HN newest, find the top AI-related stories (titles containing AI/LLM/ML), crawl each linked article, and save each page with a short note; skip Ask HN and job posts"
pwsh ../../scripts/gnosis-container.ps1 -Exec "summarize the AI stories you just saved and list the saved URLs"
```

## Overview
The search stack is built around a small set of MCP tools:
- `personal_search.save_page`: store a page (URL + text) in a JSONL index.
- `personal_search.save_url`: store URL bookmarks with optional notes.
- `personal_search.save_crawled_page`: crawl a URL and save it into the page index in one step.
- `personal_search.search_saved_pages`: semantic search over saved pages.
- `personal_search.search_saved_urls`: substring search over saved URLs/notes.
- `personal_search.count_saved_pages`, `personal_search.count_saved_urls`: counts.
- `personal_search.save_pdf_pages`: index PDF pages with page numbers.
- `gnosis-crawl.crawl_url`: fetch and clean web pages before indexing.
- `pdf-reader.split_pdf_pages`: render PDF pages to images for Claude Vision.

Implementation note: `personal_search.save_page` lives in `MCP/personal_search.py`. You can read it, modify it, and customize the behavior if you want. Same goes for any tool in `MCP/`.

Default index files:
- Pages: `temp/page_index.jsonl`
- URLs: `temp/url_index.jsonl`

Embeddings are optional. If no embedding backend is available, the tools fall back to a deterministic hash embedding (works, but less semantic).

## Embeddings Service (Instructor)
The preferred embedding backend is `instructor-xl` via the Instructor service container.
You don’t need to call it directly — Codex uses it automatically when saving/searching content.

1) Ensure the Docker network exists:
```bash
docker network create codex-network
```

2) From the codex-container repo root, start the instructor service:
```bash
docker compose -f docker-compose.instructor.yml up -d
```

CPU-only hosts (no GPU/WSL):
```bash
docker compose -f docker-compose.instructor.cpu.yml up -d
```

Note: the container name is `gnosis-instructor-service`, so the default service URL is:
`http://gnosis-instructor-service:8787/embed`

Quick check (optional): ask Codex to run a tiny save with embeddings and confirm it reports an `embedding_summary` (no vector output).

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

### Standalone Setup (in its own directory)
If you want to run the crawler independently, check it out into its own folder and build/run it locally. Docker Desktop is required.

```powershell
git clone https://github.com/deepbluedynamics/gnosis-crawl
cd gnosis-crawl
cp .env.example .env
./deploy.ps1 -Target local
```

## Claude Vision (PDF page review)
For PDF page understanding via images, set a Claude API key and use the Claude Vision tool.

Set the key in your environment:
Windows (PowerShell):
```powershell
$env:ANTHROPIC_API_KEY="your_key_here"
```

macOS/Linux:
```bash
export ANTHROPIC_API_KEY=your_key_here
```

Example flow (plain language):
- “Read page 7 of `QC503F211839v3.pdf` and summarize it.”

Behind the scenes, Codex:
1) Renders the PDF page to an image (PDF tool).
2) Sends the image to Claude Vision with your prompt.

## Tool Installation (MCP)
Users do not need to manage tools. They can use plain language and the Codex container will route and configure the right tools automatically.

## SerpAPI Key (optional search)
If you want Google search, set a SerpAPI key:

Windows (PowerShell):
```powershell
$env:SERPAPI_API_KEY="your_key_here"
```

macOS/Linux:
```bash
export SERPAPI_API_KEY=your_key_here
```

Or drop it into `examples/personal_search/.serpapi.env`.

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

Notes:
- URL bookmarks (`save_url`) are for quick recall and are searched by URL/note only.
- Page saves (`save_page` / `save_pdf_pages`) are searched semantically by content.

## PDF Indexing (with page numbers)
Store PDFs in the `/workspace/pdf` directory. Codex can index specific pages or entire documents, keeping page numbers in the index. Behind the scenes it indexes per-page text (page numbers preserved).

User-friendly examples:
- “Index the PDF `QC503F211839v3.pdf`.”
- “Index pages 10–25 of `QC503F211839v3.pdf`.”
- “Search saved stuff for ‘magnecrystallic action’ and show the page numbers.”

If PDF indexing fails, ask Codex to enable the PDF tools.

## Notes
- If the embedding service is down, the tools will still work but will fall back to hash embeddings.
- You can override index paths via `log_path` for per-project indexes.
