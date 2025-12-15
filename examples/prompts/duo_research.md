### Inputs (filled)
- Competitor Name: Duo Security
- Website URL: https://duo.com
- Competitor ID: (none)

### Workflow (minimal, tool-first, resilient)
1. Primary crawl (gnosis-crawl)
   - Crawl https://duo.com.
   - Extract all available details (overview, summary, HQ, socials, logo, founding, headcount, funding). If sufficient, stop.

2. Optional SERP (serpapi-search) — only if key fields are missing
   - Query: "Duo Security" about company information funding site:duo.com
   - Take top 5–7 results; keep only duo.com about/company/team/funding pages. Skip third-party/review/news/social.
   - Crawl at most 3 of those URLs with gnosis-crawl. If still missing, you may run one more tightly scoped SERP for social links (LinkedIn/Twitter) and one for logo, but stay minimal.

3. Extract fields (no guessing; null if absent)
   - name, overview (2–3 short paragraphs), summary (1 sentence), industry, tags[]
   - logo_url, founded_year, employee_count, headquarters, funding, revenue
   - social_links: linkedin/twitter/github/facebook (omit keys if not found)
   - processed_urls: include https://duo.com plus any crawled pages
   - If a value cannot be found with the allowed steps, set it to null so another agent can research it later. Do not get stuck; move on.

4. Produce JSON (schema intact)
```
{
  "name": "Duo Security",
  "overview": "...",
  "summary": "...",
  "industry": "...",
  "tags": ["..."],
  "logo_url": null,
  "founded_year": null,
  "employee_count": null,
  "headquarters": null,
  "funding": null,
  "revenue": null,
  "social_links": {
    "linkedin": "...",
    "twitter": "...",
    "github": "...",
    "facebook": "..."
  },
  "processed_urls": [
    "https://duo.com"
  ]
}
```
- Keep existing keys; fill what you can. Use null when not found.

5. Write the JSON to the ./temp/ directory to an appropriately named file.

### Notes
- Keep total crawls ≤5 URLs; skip SERP if the main site is sufficient.
- Avoid timeouts: minimal crawls, warm worker if possible.
- Don’t use heavy HTML fetch; prefer light, targeted calls.
- Write your JSON file to ./temp and name it after the company.
- Identity: act as a concise, resource-aware research agent; go wide enough to find data but move on and set null if it’s not available.
