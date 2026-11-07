# Verdict Research

Paste a link (or type a search query) and get a researched Markdown report. Pages are fetched with the **Oxylabs Web Scraper API**, stripped down to readable text, summarized by **free OpenRouter models**, and assembled into a report with citations.

```
link/query -> Oxylabs scrape -> clean text -> OpenRouter summarize -> report.md
```

## Features

- **Paste a link** in interactive mode and get a structured report saved to `reports/`.
- **Product review mode**: paste a product URL, and Verdict derives search keywords, gathers independent reviews, and writes a structured 100-point Verdict report.
- **Web search** by scraping Yahoo, Brave, DuckDuckGo, Bing, or Google through Oxylabs, then scraping and comparing the top results.
- **Free-model fallback**: tries several `:free` OpenRouter models automatically when one is busy, rate limited, or unavailable.
- **Long-page support**: map-reduce chunking so large pages still fit in model context windows.
- **Partial results**: if a page cannot be scraped during a search, its search snippet is used and flagged in the report.
- **Extract-only mode** (`--no-ai`) if you do not have an OpenRouter key yet.
- **Saved reports**: timestamped Markdown files with a sources appendix and model attribution.
- **Prompt-injection guardrail**: scraped pages are treated as untrusted data in every prompt.

## Quick start

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

test -f .env || cp .env.example .env   # keep the existing .env if present
# edit .env and add OXYLABS_API_KEY and GEMINI_API_KEY (OPENROUTER_API_KEY optional fallback)
python app.py models        # list currently available free OpenRouter models
python app.py review        # research a product and write a Verdict report
python app.py interactive   # paste a link or type a search
```

`.env` needs these values:

```dotenv
OXYLABS_API_KEY=your_oxylabs_bearer_token
GEMINI_API_KEY=your_gemini_key
OPENROUTER_API_KEY=your_openrouter_key   # fallback
```

Get a Gemini key at <https://aistudio.google.com/apikey> and an OpenRouter key at <https://openrouter.ai/keys>. A free account can use models whose id ends in `:free`, plus the `openrouter/free` auto-router used by default.

The included `.env` already contains the Oxylabs key you supplied. It is gitignored. If that key has been shared anywhere else, rotate it in the Oxylabs dashboard.

## AI providers

The AI chain is **NVIDIA NIM → Gemini → OpenRouter**. Each request goes to NVIDIA first; if it errors, is rate limited, or returns nothing, the same request is retried on Gemini, then on OpenRouter free models. If a provider's key is rejected, that provider is skipped for the rest of the run.

```
NVIDIA_API_KEY=...        # https://build.nvidia.com  (primary)
NVIDIA_MODELS=meta/muse-glimmer-30b   # optional, comma-separated
GEMINI_API_KEY=...        # https://aistudio.google.com/apikey  (fallback 1)
GEMINI_MODELS=gemini-flash-latest   # optional, comma-separated, tried in order
OPENROUTER_API_KEY=...    # fallback 2
```

Any one key alone works. With neither, the tool runs in extract-only mode. Reports list which model wrote them in the footer. Google changes model names often, so the default is the `gemini-flash-latest` alias; pin an exact id in `GEMINI_MODELS` if you want a fixed model.

## Website (Flask)

```bash
pip install -r requirements.txt
python web.py            # http://127.0.0.1:5000
```

Pick a mode (**Product review**, **Summarize a link**, or **Web search**), paste a URL or query, and watch progress update live. The finished report renders on the page, with **Copy Markdown** and **Download .md** buttons.

How it works: `POST /api/research` starts a background job and returns an id; the page polls `GET /api/jobs/<id>` for new progress steps and the final report. Jobs live in memory and are dropped an hour after they finish. `VERDICT_WEB_CONCURRENCY` (default 3) caps how many run at once; extra jobs wait in the queue.

For production, run it behind a real server and keep to **one worker process** (jobs are held in memory, so multiple processes would not see each other's jobs):

```bash
pip install gunicorn
gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 web:app
```

API keys stay on the server and are never sent to the browser. Scraped and AI text is rendered with raw HTML disabled. There is no login or per-user limit yet, so put it behind auth before exposing it publicly, since every run spends Oxylabs credits.

## Usage

### Interactive (recommended)

```bash
python app.py interactive
```

Then paste a link:

```
verdict › https://www.amazon.com/s?k=vans+knu+skool
```

Or type a search:

```
verdict › best trail running shoes 2026
```

Commands inside the loop:

| Command | Action |
| --- | --- |
| `/review <url>` | Research a product and write a 100-point Verdict report |
| `/focus <topic>` | Steer summaries toward a topic |
| `/clearfocus` | Clear the focus |
| `/models` | List free OpenRouter models |
| `/help` | Show help |
| `/quit` | Exit |

### One-shot CLI

```bash
# Scrape one link
python app.py scrape "https://www.amazon.com/s?k=vans+knu+skool"

# Render JavaScript for sites that need it (slower, uses more Oxylabs credits)
python app.py scrape "https://example.com/spa-app" --render

# Research a product; press Enter to accept the derived search keywords
python app.py review "https://www.amazon.com/dp/B09XS7JWHH"

# Supply your own keywords and skip the confirmation prompt
python app.py review "https://www.amazon.com/dp/B09XS7JWHH" \
  --keywords "Sony WH-1000XM5" --yes

# Search, scrape the top 3 hits, and compare them
python app.py search "vans knu skool sizing" --limit 8 --scrape 3

# Auto-detect whether the input is a URL or a query
python app.py run "https://example.com/article"
python app.py run "latest battery recycling rules"

# Focus the analysis on pricing
python app.py search "mechanical keyboard" --focus "price vs durability"

# Use a specific free model, then fall back to the configured list
python app.py scrape "https://example.com" --model "openrouter/free"

# Extract only, no AI call
python app.py scrape "https://example.com" --no-ai

# List free models
python app.py models
```

Reports are written to `reports/` by default. Use `--out DIR` to change that or `--no-save` to skip writing.

## Example report structure

```markdown
# Research Report: vans knu skool sizing

## Executive Summary
...

## Key Findings
- ... [1]
- ... [2]

## Detailed Analysis
### Fit and sizing
... [1]

## Contradictions and Gaps
...

## Bottom Line
...

## Sources
1. [Article title](https://example.com/article)
2. [Another source](https://example.org/page)

---
*Generated by Verdict on 2026-10-31 12:30 EDT · AI: openrouter/free · Scraping: Oxylabs.*
*AI summaries can be wrong. Verify critical facts against the linked sources.*
```

`review` reports follow the Verdict format instead: an overall score and recommendation, product overview, positives, problems and red flags, customer feedback, claims vs reality, value for money, brand trustworthiness, alternatives, who should buy or avoid it, and a final recommendation. The score, recommendation, and confidence are explicitly tied to the strength of the collected evidence.

## How it works

1. **Scrape** — `verdict/oxylabs_client.py` posts to `https://webapi.oxylabs.io/v1/scrape` with `{"url": ..., "output": ["html"], "run_js": false}` and a Bearer token, exactly like the Oxylabs example. Transient `429`/`5xx` responses are retried with backoff.
2. **Search** — the same Oxylabs client scrapes a search-engine results page (Yahoo by default, with Brave, DuckDuckGo, Bing, and Google as alternatives). `verdict/search.py` parses organic results, unwraps redirect links, drops ads and internal links, and normalizes tracking parameters. If one engine yields nothing, the others are tried. Yahoo is the default because it is the most reliable through Oxylabs' generic scraper.
3. **Extract** — `verdict/extract.py` uses Trafilatura (with a BeautifulSoup fallback) to isolate article text and pull title, author, description, and publish date.
4. **Summarize** — `verdict/summarizer.py` creates a per-source summary. Pages that exceed `VERDICT_MAX_CHARS` are chunked, each chunk is summarized, and the notes are reduced into one summary.
5. **Report** — a final OpenRouter call produces the report with inline `[n]` citations. Verdict appends the numbered sources and model attribution so citations always line up.
6. **Review** — `review` scrapes the product page, asks the AI for a concise product query (with a deterministic fallback if the AI is unavailable), searches for independent coverage, filters out the product page itself, summarizes each source for product evidence, and writes the 100-point Verdict report.
7. **Save** — Markdown is rendered in the terminal and written to `reports/`.

### OpenRouter model fallback

The client tries models in order. On `429` or `5xx` it retries once, then moves to the next model. On `404` (model retired) or other client errors it moves on immediately. A `401` stops immediately because the key is invalid.

Run `python app.py models` to see what is free today. Free model availability changes frequently.

## Configuration

All settings can live in `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OXYLABS_API_KEY` | — | Oxylabs Bearer token |
| `NVIDIA_API_KEY` | — | NVIDIA NIM API key (primary AI) |
| `NVIDIA_MODELS` | `meta/muse-glimmer-30b` | Comma-separated NVIDIA models, tried in order |
| `GEMINI_API_KEY` | — | Gemini API key (fallback 1) |
| `GEMINI_MODELS` | `gemini-flash-latest` | Comma-separated Gemini models, tried in order |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (fallback 2) |
| `OPENROUTER_MODELS` | curated free list | Comma-separated OpenRouter fallback models |
| `OPENROUTER_MODEL` | — | Single model; appends the curated list as fallback |
| `VERDICT_MAX_CHARS` | `30000` | Max characters per source sent to the AI |
| `VERDICT_TIMEOUT` | `120` | HTTP timeout in seconds |
| `VERDICT_WORKERS` | `3` | Concurrent scrapes for multiple pasted links |
| `VERDICT_REPORT_DIR` | `reports/` | Output directory |
| `OXYLABS_ENDPOINT` | Oxylabs web API | Override for testing/proxies |
| `OPENROUTER_ENDPOINT` | OpenRouter chat API | Override for testing/proxies |

CLI flags `--oxylabs-key`, `--openrouter-key`, `--model`, `--out`, `--max-chars`, and `--workers` override the environment.

## Project layout

```
app.py                       CLI and interactive loop
web.py                       Flask website (jobs + progress polling)
templates/index.html         website UI
verdict/
  config.py                  env loading and settings
  errors.py                  shared exceptions
  extract.py                 HTML -> text, metadata, chunking, URL helpers
  models.py                  Source / SourceSummary / SearchResult
  openrouter_client.py       chat completions + free-model fallback
  oxylabs_client.py          scrape + search through Oxylabs
  pipeline.py                UI-agnostic flows with progress callbacks (website)
  product.py                 product keyword fallbacks and URL matching
  report.py                  sources, footers, raw fallback, saving
  search.py                  SERP URL builders and parsers
  summarizer.py              map-reduce summaries and final reports
  verdict_prompt.py          the Verdict product-report instructions
tests/                       offline unit tests
reports/                     generated Markdown reports (gitignored)
```

## Tests

The tests are offline and do not touch your Oxylabs or OpenRouter credits.

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Oxylabs HTTP 401` | The token is wrong or expired. Recheck `OXYLABS_API_KEY`. |
| `Oxylabs returned no results` | The target blocked the request or returned an empty page. Try another URL. |
| `Search failed on every engine` | Search engines may be rate limiting. Wait, or try `--engine brave` / `--engine yahoo`. |
| `Every configured OpenRouter model failed` | Free models are busy. Retry, or run `python app.py models` and set `OPENROUTER_MODELS`. |
| Report is short or says "partial" | A page could not be scraped and the search snippet was used instead. |
| `review` finds no independent results | The product query may be too specific. Pass a broader `--keywords "brand model"` or try `--engine brave`. |
| No OpenRouter key | Everything still works with `--no-ai` or automatically falls back to extract-only. |

## Security and limitations

- `.env` is gitignored. Do not commit API keys or paste them into issue trackers.
- Scraped content is untrusted. Prompts explicitly tell the model to ignore instructions found in page text, but no prompt-injection defense is perfect. Treat generated reports as drafts.
- AI summaries can be wrong or omit context. The report always links its sources; verify important claims.
- Respect Oxylabs' terms of service, target-site terms, robots directives, and applicable law when scraping.
- Search result quality depends on the scraped engine's HTML. The parsers cover the common DuckDuckGo/Bing/Google layouts and are covered by unit tests, but search engines change markup regularly.
