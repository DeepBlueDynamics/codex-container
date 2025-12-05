# Hacker News Crawl → Graph → Index Prompt

```
# Task
Run a full Hacker News sweep and index it, prioritizing speed and reliability (no raw HTML output—use markdown/structured text only):
- Crawl HN front page → extract {title, url} items
- Build a term graph on the extracted text
- Propose/search queries → sample follow-on URLs (bounded)
- Crawl the sampled URLs (bounded)
- Index everything locally with embeddings for later recall/search

# Inputs
- FRONT_PAGE_URL: https://news.ycombinator.com/
- MAX_FRONT_ITEMS: 60
- MAX_FOLLOWUP_URLS: 15
- MAX_CRAWL: 20 (total URLs to crawl including front-page links)
- GRAPH_TOP_TERMS: 50
- GRAPH_MAX_EDGES: 120
- EMBEDDING_INSTRUCTION: "Represent the page for semantic recall and link analysis"
- SAVE_LOG_PATH (optional): leave blank to use default
- SEED: 2025-12-03-hn
- ALLOWLIST: ["news.ycombinator.com", "github.com", "medium.com", "substack.com", "techcrunch.com", "theverge.com", "arxiv.org", "wikipedia.org", "blog."]

# Tools to use (order of operations)
1) gnosis-crawl.crawl_url
   - url: FRONT_PAGE_URL
   - markdown_extraction: "enhanced"
   - take_screenshot: false
   - timeout: 20
   - Output in markdown/clean text only; no raw HTML.

2) term_graph_tools.build_term_graph
   - docs: [{"url": FRONT_PAGE_URL, "text": <front_page_markdown>}]
   - top_terms: GRAPH_TOP_TERMS
   - max_edges: GRAPH_MAX_EDGES
   - window: 4
   - embedding_backend: "hash" (fast) or "instructor-xl" if available
   - embedding_path: optional

3) term_graph_tools.propose_queries
   - graph: <graph_from_step_2>
   - max_queries: 8
   - focus_terms: optional (pick 2-3 strongest terms)

4) term_graph_tools.sample_urls
   - urls: <filtered front-page URLs>
   - scores: optional (rank by HN position)
   - allowlist: ALLOWLIST
   - max_total: MAX_FOLLOWUP_URLS
   - max_per_domain: 3
   - explore_ratio: 0.35
   - domain_diversity: true
   - drop_params: true
   - seed: SEED

5) gnosis-crawl.crawl_batch (or crawl_url loop)
   - urls: combined set of selected URLs (respect MAX_CRAWL total)
   - collate: false
   - markdown_extraction: "enhanced"
   - take_screenshot: false
   - timeout: 25

6) term_graph_tools.save_page
   For each crawled page:
   - url: <page_url>
   - text: <page_markdown_trimmed>
   - note: "hn-frontpage" or "hn-followup"
   - embed: true
   - embedding_backend: "instructor-xl" (preferred) or "hash"
   - max_store_chars: 12000

7) term_graph_tools.summarize_signals (optional)
   - docs: <all crawled docs>
   - graph: <updated graph with merged docs>
   - top_k: 20

# Step-by-step plan
- Step A: Crawl HN front page (Tool 1). Extract link list (title + url); discard non-HTTP and dupes.
- Step B: Build term graph on front-page markdown (Tool 2).
- Step C: Propose 5–8 queries from graph (Tool 3).
- Step D: Sample follow-on URLs from HN links (Tool 4) with ALLOWLIST and caps.
- Step E: Crawl selected URLs (Tool 5), keeping total crawls ≤ MAX_CRAWL.
- Step F: Save + embed each crawled page (Tool 6) with instruction EMBEDDING_INSTRUCTION.
- Step G (optional): Summarize signals (Tool 7).
- Output: a compact report: counts, sampled URLs, any crawl failures, top terms, and where data was saved.

# Guardrails
- Enforce caps: MAX_CRAWL total, MAX_FOLLOWUP_URLS sampled.
- If embeddings fail, still save pages without embed.
- Skip dead/redirect loops; if >3 failures, continue with remaining set.
- Strip/trim pages >12k chars before save_page.
- Avoid social spam; prefer allowlisted, reliable domains; skip slow/untrusted sources.
- No raw HTML output—keep everything in markdown/clean text for parsing and indexing.

# Deliverable
- List of crawled URLs (front + follow-up), noting failures.
- Top terms/queries from graph.
- Location of saved pages/embeddings.
- 3–5 bullet takeaways on themes from the batch.

# Ready to execute
Begin at Step A with `gnosis-crawl.crawl_url` on FRONT_PAGE_URL.
```
