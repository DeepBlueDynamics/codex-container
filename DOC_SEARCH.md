# Codex Search Agent Setup

Use Codex plus a few lightweight Python tools to build a solid search index — including PDFs with page numbers — without asking users to learn any APIs. People just say “save this page” or “search saved stuff for X,” and Codex handles crawling, indexing, and retrieval.

Before using search, install and run Codex using the container-based workflow in [`README.md`](README.md). You’ll need Docker running locally (e.g., Docker Desktop).

This doc covers the search/index workflow (URLs + content + embeddings) and how to start the crawler service.

## Overview
The search stack is built around a small set of MCP tools:
- `personal_search.save_page`: store a page (URL + text) in a JSONL index.
- `personal_search.save_url`: store URL bookmarks with optional notes.
- `personal_search.search_saved_pages`: semantic search over saved pages.
- `personal_search.search_saved_urls`: substring search over saved URLs/notes.
- `personal_search.count_saved_pages`, `personal_search.count_saved_urls`: counts.
- `personal_search.save_pdf_pages`: index PDF pages with page numbers.
- `gnosis-crawl.crawl_url`: fetch and clean web pages before indexing.
- `pdf-reader.split_pdf_pages`: render PDF pages to images for Claude Vision.

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

## Claude Vision (PDF page review)
For PDF page understanding via images, set a Claude API key and use the Claude Vision tool.

Set the key in your environment:
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
