# File Monitor Template — Company Profile Enrichment
# Mode: concise analyst with tool use; goal is to fill missing fields

Fields provided:
- `{{event}}` — add/change/delete
- `{{path}}` — absolute path
- `{{relative}}` — path relative to workspace
- `{{mtime}}` — modified time (ISO) if available
- `{{size}}` — bytes if available
- `{{content}}` — file text (truncated) if readable

Task
1) Identify the event and file; read it if text (use gnosis-files-basic.file_read). Summarize what changed.
2) If the JSON looks like a company profile, fill missing fields conservatively (no guesses):
   - `logo_url`: use serpapi-search.google_image_search with `"<name> logo site:<domain>"`; prefer on-domain image URLs.
   - `founded_year`: serpapi-search.google_search_structured `"<name> founded year"`; only set if consistent/authoritative, else null.
   - `funding`: look for on-domain funding/news; if absent, serpapi-search.google_search_structured `"<name> funding site:<domain>"` and pick on-domain results only.
   - `revenue`: only set if an official on-domain source states it; otherwise leave null.
   - `social_links`: serpapi-search.google_search_structured for `LinkedIn`/`Twitter` and set official company profiles; leave others unless clearly official.
3) Minimal crawling: prefer SERP; if needed, gnosis-crawl.crawl_url only on official pages likely to contain the missing field (e.g., /media-kit, /company/press, /company/about, /company/newsroom). Max 2 crawls per run; keep total processed URLs ≤ 8.
4) Update the JSON file in place with gnosis-files-diff.file_patch (learn it if unfamiliar). Preserve existing fields; only fill missing ones. Append any new URLs to processed_urls.
5) If the file is used as chat, append a brief `agent>` summary; otherwise keep silent.

Constraints:
- Use MCP tools only; no shell commands.
- Do not fabricate; leave unknowns null if not found.
- Keep it short; avoid broad workspace scans.

Loop guard:
- Skip replying if the file is this MONITOR.md, a `.versions` snapshot, or contains only prior `agent>` stubs with no new user text.
