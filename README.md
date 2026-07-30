# 🤖 Tech Watch Agent — Autonomous LLM agent for technology intelligence

An autonomous agent that scans **7+ tech sources in parallel**, lets an **LLM judge which stories actually matter**, **fetches the full text of the important ones itself** (with SSRF protection), writes structured summaries, and produces a **cross-article synthesis of the emerging trends** — delivered as a daily Markdown brief or a live web feed.

> Not a fixed script: the agent *decides what to read*, *acts on its environment* (tool-use to fetch full articles), and *analyses instead of juxtaposing*. Every LLM step fails open — no API key or an LLM error degrades gracefully back to the deterministic pipeline.

**Stack:** Python · FastAPI · OpenAI / Anthropic (config-driven) · APScheduler · Jinja2 · ThreadPoolExecutor · 63 unit tests (no network, no API key)

---

## ✨ What makes it an *agent*, not a scraper

| Capability | How it works | Code |
|---|---|---|
| 🧠 **Relevance judgment** | Instead of a raw keyword filter, the LLM reads the pre-filtered candidates and *selects & ranks* the ones that matter for the watch goal (novelty, impact, signal), attaching a `relevance` score + reason. | `core/agent.py:judge_relevance` |
| 🔎 **Tool use (deep-dive)** | Articles the LLM flags as major get their **full page text fetched** so the summariser works on real substance, not a truncated excerpt. Concurrent, bounded. | `core/agent.py:deep_dive` + `core/tools.py` |
| 🧩 **Cross-article synthesis** | A final pass distils **2–3 underlying trends** connecting the day's articles, placed at the top of the brief. | `core/agent.py:synthesize` |
| 💸 **Cost tracking** | Token usage + estimated USD cost per run (per model), shown in the brief footer and `GET /api/status`. | `core/obs.py` |
| 🛡️ **SSRF-safe fetching** | The deep-dive tool blocks private / loopback / link-local IPs (incl. `169.254.169.254` cloud metadata), rejects non-HTTP schemes, and **re-validates every redirect hop** (DNS-rebinding defence). | `core/tools.py` |

All three agentic capabilities are **toggleable** in `config.yaml`:

```yaml
agent:
  enable_relevance: true   # LLM judges relevance/importance (vs raw keyword filter)
  enable_deepdive: true    # fetches full text of articles judged major
  enable_synthesis: true   # cross-article synthesis (2-3 trends) at brief top
  relevance_pool: 25       # nb of pre-filtered candidates submitted to the LLM
```

---

## 🏗️ Pipeline

```
config.yaml (active profile)
  → fetcher.py        7+ sources fetched IN PARALLEL (ThreadPoolExecutor)
      HackerNews · Reddit · RSS feeds · Dev.to · Lobste.rs · GitHub · ArXiv
  → article_filter.py cheap pre-filter: dedup (normalised-title + Jaccard near-dup), keyword match, score & sort
  → 🧠 agent.judge_relevance   LLM selects/ranks what matters, flags deep-dive
  → 🔎 agent.deep_dive         fetches full text of flagged articles (SSRF-safe)
  → summarize.py      structured LLM summary (JSON, 3 retries on rate-limit)
  → 🧩 agent.synthesize        2-3 cross-cutting trends → top of brief
  → obs.merge_usage   token + cost accounting
  → brief_generator.py writes output/briefs/brief_veille_YYYY-MM-DD.md
```

`main.py` runs it as a CLI; `web/app.py` exposes the same pipeline over FastAPI.

## 🔁 Continuous watch mode

A scheduler (APScheduler) scans every *N* minutes, streams new items to a **live web feed**, flags **breaking** stories (official sources or high social score), and consolidates a **daily brief** at a fixed time — reusing existing summaries so the daily digest costs **zero** extra LLM calls. Full FR/EN i18n (interface + output language) switchable from the navbar.

---

## 🚀 Quickstart

```bash
python -m venv venv && venv\Scripts\activate      # Windows (source venv/bin/activate on Unix)
pip install -r requirements.txt
copy .env.example .env                             # then set OPENAI_API_KEY (or ANTHROPIC_API_KEY)

python main.py            # CLI → output/briefs/
python run_web.py         # web UI + live feed → http://localhost:8000
```

```bash
python -m pytest tests/ -q     # 63 tests, no network / no API key required
```

The LLM provider is chosen in `config.yaml` (`llm.provider: openai | anthropic`). Without a key, the agentic steps degrade to the plain pipeline instead of failing.

## 🧪 Engineering notes

- **Fails open everywhere:** each agentic step returns its input unchanged on any error → the brief always ships.
- **Two-phase dedup:** filters against a rolling `seen_articles.json` window; only *published* articles are marked seen, so filtered-out ones stay eligible later.
- **Atomic config writes** + a lock guard the web routes that rewrite `config.yaml`.
- **Robustness details:** `truststore` for corporate TLS interception, Reddit `.rss` fallback on 403, ArXiv `https` + `quote_plus`, path-traversal guard on brief filenames.
- **Tested:** `article_filter` (dedup/scoring/Jaccard), `summarize` JSON parsing + text fallback, `agent` (judge/deep-dive/synthesis, monkeypatched — no network), `tools` (SSRF classification, DNS-rebinding case, HTML→text), `obs` (cost estimation), `config_loader`, `watcher`.

## 🗂️ Layout

```
core/     agent.py · llm.py · tools.py · obs.py · fetcher.py · article_filter.py
          summarize.py · brief_generator.py · watcher.py · notifier.py · config_loader.py
sources/  one module per source (hackernews, reddit, rss_feeds, devto, lobsters, github, arxiv)
web/      FastAPI app + Jinja2 templates (dashboard, live feed, brief viewer)
tests/    63 unit tests
config.yaml   profiles (AI, DevOps, Cybersecurity, Web, Data Science) + agent/watch settings
```

---

*Built by [Axel AHO](https://github.com/Yoh5) — AI/Agent engineering, automation, Python.*
