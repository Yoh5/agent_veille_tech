# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Run CLI pipeline
python main.py
python main.py --config config.yaml

# Run web interface (http://localhost:8000)
python run_web.py
```

Required environment variable (set before running):
```bash
set ANTHROPIC_API_KEY=sk-ant-...
```

## Architecture

The pipeline is linear and stateless between runs except for `output/seen_articles.json`:

```
config.yaml (active_profile)
    → core/config_loader.py   resolves active profile into a flat config dict
    → core/fetcher.py         dispatches to sources/ based on profile.sources
        → sources/hackernews.py   (Algolia API, no auth)
        → sources/reddit.py       (Reddit JSON API, no auth)
        → sources/rss_feeds.py    (feedparser)
    → core/filter.py          dedup against output/seen_articles.json, keyword match, trend count
    → core/summarize.py       calls Anthropic API, parses structured text response
    → core/brief_generator.py writes output/briefs/brief_veille_YYYY-MM-DD.md
```

`main.py` runs this pipeline as a CLI. `web/app.py` exposes the same pipeline via FastAPI, running step 2–5 in a background task on `POST /run`.

## Configuration

`config.yaml` has two levels:

**Global** (top-level): `active_profile`, `llm` (model/temperature/max_tokens), `max_articles`, `dedup_window_days`.

**Per-profile** (under `profiles.<key>`): `name`, `icon`, `description`, `keywords` (list), `sources` (hackernews/reddit/rss_feeds with enabled/weight/query/subreddits/feeds).

The active profile is set by `active_profile: <key>`. The web UI's `/profile` POST endpoint rewrites `config.yaml` in place to change this.

## Key Implementation Details

- **Deduplication state** lives in `output/seen_articles.json` (MD5 of lowercased title). It's a rolling window controlled by `dedup_window_days`; entries older than the window are dropped on each load.
- **Scoring/ranking** happens implicitly via `raw_weight` on each article (set per-source in config). Articles are sorted by `filter.py` before returning; `max_articles` from config caps the LLM batch.
- **LLM summarizer** (`core/summarize.py`) currently only implements Anthropic despite the README listing OpenAI/Ollama as options — those providers are not wired up. The parsed output format is `RÉSUMÉ:` / `POINTS_CLÉS:` / `À_RETENIR:` plaintext blocks.
- **Web routes**: `GET /` dashboard, `GET /brief/{filename}` renders MD→HTML, `POST /run` triggers background task, `POST /profile` switches profile, `GET /api/status` returns JSON for n8n/webhooks.
- **No tests** exist in this project.
