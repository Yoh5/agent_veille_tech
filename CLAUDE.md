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

```bash
# Run tests (no network, no API key needed)
python -m pytest tests/ -q
```

Required environment variable (loaded automatically from `.env` via python-dotenv) — depends on `llm.provider` in config.yaml (`openai` is the current active provider):
```
OPENAI_API_KEY=sk-...        # if llm.provider: openai (current)
ANTHROPIC_API_KEY=sk-ant-... # if llm.provider: anthropic
GITHUB_TOKEN=ghp_...         # optional — raises GitHub from 60 to 5000 req/h
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
    → core/summarize.py         calls the configured LLM — OpenAI or Anthropic (3 retries on rate limit), parses structured response
    → core/brief_generator.py   writes output/briefs/brief_veille_YYYY-MM-DD.md (no overwrite)
    → core/og_image.py          enriches articles with og:image + favicon in parallel
```

`main.py` runs this pipeline as a CLI. `web/app.py` exposes the same pipeline via FastAPI, running in a background task on `POST /run` or `POST /run-custom`.

## Continuous watch mode (veille continue)

`core/watcher.py` + APScheduler in `web/app.py`. Config under `watch:` in config.yaml (`enabled`, `interval_minutes`, `max_per_scan`, `daily_brief_time`, `breaking_sources`, `breaking_hn_points`).

- `scan_once()`: fetch (period 1 day) → filter → summarize at most `max_per_scan` new articles → append to `output/live_feed.json` (capped 200) → `mark_seen`. Skipped while a manual run is in progress.
- **Breaking detection**: article from an official source (`breaking_sources` list) or with social score ≥ `breaking_hn_points` gets `breaking: true` and a red highlight in the UI.
- `generate_daily_brief()`: cron at `daily_brief_time` — consolidates the last 24 h of the live feed into a normal brief WITHOUT new LLM calls (summaries already exist), then emails it if notifications are enabled.
- Routes: `GET /live` (feed page, 60 s auto-refresh, stat tiles, per-item delete), `GET /api/live?since=…`, `POST /watch/toggle` (persists `watch.enabled` in config.yaml and reprograms the scheduler), `POST /watch/scan-now`, `POST /live/delete` (item_id), `POST /brief/delete` (filename, validated by the brief regex).
- **UI language**: top-level `language:` in config.yaml drives BOTH the interface labels (UI_STRINGS dict in web/app.py, fr/en) and the pipeline output language (watch scans + runs). The FR/EN switcher lives in the navbar (`base.html`), available on every page: it POSTs `/language` with a hidden `next` = current path, validated against a safelist (`/`, `/live`, `/brief/<valid filename>`) before redirect — anything else falls back to `/`. Deletion buttons use an inline arm-then-confirm pattern (first click arms for 2.5 s, second click submits) — no browser confirm() dialogs.
- **Live feed rendering**: `GET /live` enriches each feed item via `_enrich_live_item` (web/app.py) — `_rich()` escapes HTML then renders `**bold**` as `<strong>` (Markup, rendered without `| safe` filters in the template), `highlights_html` list, and `actor_tags` (name + Google s2 favicon resolved through `brief_generator._KNOWN_DOMAINS`). Cards show og:image thumbnail, key points, takeaway box and actor chips — the on-disk `live_feed.json` is never mutated (copies only).
- YAML gotcha: `daily_brief_time: 08:00` unquoted is parsed by PyYAML as the integer 480 (sexagesimal) — `_configure_scheduler` handles both int and "HH:MM" string.
- **Startup requirements**: `web/app.py` itself injects truststore AND loads `.env` at import time, so `uvicorn web.app:app` works without going through `run_web.py`. Don't remove those blocks.

## Email notification

`core/notifier.py:send_brief(path)` — driven by `notifications.email` in config.yaml (disabled by default; 465 = implicit SSL, otherwise STARTTLS). Called after CLI briefs (main.py) and daily watch briefs.

## Configuration

`config.yaml` has two levels:

**Global** (top-level): `active_profile`, `llm` (model/temperature/max_tokens: 1200), `max_articles`, `dedup_window_days: 7`.

**Per-profile** (under `profiles.<key>`): `name`, `icon`, `description`, `keywords` (list), `sources` (hackernews/reddit/rss_feeds/devto/github/lobsters/arxiv with enabled/weight/tags/query).

The active profile is set by `active_profile: <key>`. The web UI's `/profile` POST endpoint rewrites `config.yaml` in place.

## Key Implementation Details

- **Module name**: the filter module is `article_filter.py` (named to avoid shadowing Python's builtin `filter()`). Always import as `from core import article_filter`.
- **TLS interception (antivirus/proxy)**: `main.py` and `run_web.py` call `truststore.inject_into_ssl()` at startup so Python uses the Windows/macOS certificate store. Without it, ALL HTTPS fetches fail with CERTIFICATE_VERIFY_FAILED on machines with Avast-style TLS interception.
- **Parallel fetch**: `core/fetcher.py` uses `ThreadPoolExecutor` — all enabled sources fetch simultaneously. `fetch_all()` returns `(articles, stats)` where stats maps source label → count or error; stats end up in `meta["sources_stats"]` and in the brief footer.
- **Deduplication (two-phase)**: `filter_articles()` only FILTERS against `output/seen_articles.json` (MD5 of full lowercased title, rolling `dedup_window_days` window, plus in-batch title/URL dedup) — it persists nothing. `mark_seen(articles)` persists ONLY the articles actually published in a brief; both `main.py` and `web/app.py` call it after `brief_generator.generate()`. Articles cut by the keyword filter or the `max_articles` cap therefore stay eligible for future runs.
- **Scoring/sorting**: `score = raw_weight × (1 + social_bonus) × (1 + 0.1 × min(kw_matches − 1, 5))` — source weight, social engagement (capped +50%), keyword-relevance bonus (capped +50%). `kw_matches` and `score` are stored on each article. `max_articles` then caps the LLM batch.
- **Reddit**: public JSON returns 403 on many networks; `sources/reddit.py` automatically falls back to the still-served `.rss` feeds (no score/comment counts). Subreddit fetches are spaced 1.5 s apart and retry once on 429.
- **LLM**: provider is config-driven (`openai` | `anthropic`), both wired in `core/summarize.py`. Retries up to 3× on rate limit / overloaded (10s, 20s, 40s backoff). Content truncated at 6000 chars. max_tokens: 1200. Concurrency limited to 3 parallel LLM calls. og:image/favicon enrichment runs in a background thread DURING the LLM calls (disjoint dict keys, no race).
- **Brief overwrite protection**: `brief_generator.py` appends `_HHMM` suffix if a brief already exists for today.
- **Path traversal guard**: `/brief/{filename}` validates against regex `^brief_veille_\d{4}-\d{2}-\d{2}(_\d{4})?\.md$` before reading.
- **Pipeline state**: `web/app.py` exposes `_pipeline_state` with `running`, `step` (fetch/filter/summarize/generate), `error`, `last_result`. Protected by `threading.Lock`. Visible at `GET /api/status`.
- **RSS feeds**: Use `requests.get(..., timeout=15)` then pass content to `feedparser.parse()` — avoids feedparser's no-timeout urllib behavior.
- **ArXiv**: Uses `https://` (not http) and `urllib.parse.quote_plus()` for query encoding.
- **Web routes**: `GET /` dashboard, `GET /brief/{filename}`, `POST /run`, `POST /run-custom` (custom topic), `POST /profile`, `GET /api/status`. The run endpoints reserve `running=True` inside the lock before scheduling (no double-launch on rapid double POST); "nothing found" outcomes are reported via `_pipeline_state["message"]`.
- **Tests**: `tests/` covers article_filter (two-phase dedup, scoring), summarize `_parse`, and config_loader. Pure unit tests — no network, no API key.
