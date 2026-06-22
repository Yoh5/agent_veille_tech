# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # then fill ANTHROPIC_API_KEY

# Run CLI pipeline
python main.py
python main.py --config config.yaml

# Run web interface (http://localhost:8000)
python run_web.py
```

Required environment variable (loaded automatically from `.env` via python-dotenv):
```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...   # optional — raises GitHub from 60 to 5000 req/h
```

## Architecture

The pipeline is linear and stateless between runs except for `output/seen_articles.json`:

```
config.yaml (active_profile)
    → core/config_loader.py     resolves active profile into a flat config dict
    → core/fetcher.py           dispatches to sources/ in PARALLEL (ThreadPoolExecutor)
        → sources/hackernews.py       (Algolia API, no auth)
        → sources/reddit.py           (Reddit JSON API, no auth)
        → sources/rss_feeds.py        (feedparser, fetched via requests for timeout)
        → sources/devto.py            (Dev.to public API — all tags, not just first)
        → sources/lobsters.py         (Lobste.rs JSON — all tags, not just first)
        → sources/github_trending.py  (GitHub search API, supports GITHUB_TOKEN)
        → sources/arxiv.py            (ArXiv Atom API — https, quote_plus encoding)
    → core/article_filter.py    dedup (full title MD5), keyword match, score+sort, trend count
    → core/summarize.py         calls Anthropic API (3 retries on rate limit), parses structured response
    → core/brief_generator.py   writes output/briefs/brief_veille_YYYY-MM-DD.md (no overwrite)
    → core/og_image.py          enriches articles with og:image + favicon in parallel
```

`main.py` runs this pipeline as a CLI. `web/app.py` exposes the same pipeline via FastAPI, running in a background task on `POST /run` or `POST /run-custom`.

## Configuration

`config.yaml` has two levels:

**Global** (top-level): `active_profile`, `llm` (model/temperature/max_tokens: 1200), `max_articles`, `dedup_window_days: 7`.

**Per-profile** (under `profiles.<key>`): `name`, `icon`, `description`, `keywords` (list), `sources` (hackernews/reddit/rss_feeds/devto/github/lobsters/arxiv with enabled/weight/tags/query).

The active profile is set by `active_profile: <key>`. The web UI's `/profile` POST endpoint rewrites `config.yaml` in place.

## Key Implementation Details

- **Module name**: `filter.py` was renamed to `article_filter.py` to avoid shadowing Python's builtin `filter()`. Always import as `from core import article_filter`.
- **Parallel fetch**: `core/fetcher.py` uses `ThreadPoolExecutor` — all enabled sources fetch simultaneously. Previous version was sequential.
- **Deduplication**: `output/seen_articles.json` stores MD5 of the full lowercased title (not truncated). Rolling window = `dedup_window_days` (default 7). In-batch URL dedup prevents same article appearing twice from different sources.
- **Scoring/sorting**: `article_filter.py` sorts articles by `score = raw_weight × (1 + engagement_bonus)` before returning. `max_articles` then caps the LLM batch.
- **LLM**: Only Anthropic is wired up despite the README mentioning OpenAI/Ollama. Retries up to 3× on rate limit / overloaded (10s, 20s, 40s backoff). Content truncated at 6000 chars (not 2500). max_tokens: 1200 (not 700). Concurrency limited to 3 parallel LLM calls.
- **Brief overwrite protection**: `brief_generator.py` appends `_HHMM` suffix if a brief already exists for today.
- **Path traversal guard**: `/brief/{filename}` validates against regex `^brief_veille_\d{4}-\d{2}-\d{2}(_\d{4})?\.md$` before reading.
- **Pipeline state**: `web/app.py` exposes `_pipeline_state` with `running`, `step` (fetch/filter/summarize/generate), `error`, `last_result`. Protected by `threading.Lock`. Visible at `GET /api/status`.
- **RSS feeds**: Use `requests.get(..., timeout=15)` then pass content to `feedparser.parse()` — avoids feedparser's no-timeout urllib behavior.
- **ArXiv**: Uses `https://` (not http) and `urllib.parse.quote_plus()` for query encoding.
- **Web routes**: `GET /` dashboard, `GET /brief/{filename}`, `POST /run`, `POST /run-custom` (custom topic), `POST /profile`, `GET /api/status`.
- **No tests** exist in this project.
