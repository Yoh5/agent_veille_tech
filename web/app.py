"""Interface Web FastAPI — Agent de Veille Tech."""
import json
import os
import sys
import glob
import markdown
from datetime import datetime

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)

from core import config_loader, fetcher, filter, summarize, brief_generator

app = FastAPI(title="Agent de Veille Tech", version="2.0")

_pipeline_state: dict = {"running": False, "started_at": None}

_PERIOD_DAYS = {"day": 1, "week": 7, "month": 15}

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

BRIEFS_DIR = os.path.join(parent, "output", "briefs")
CONFIG_PATH = os.path.join(parent, "config.yaml")
RECENT_TOPICS_PATH = os.path.join(parent, "output", "recent_topics.json")


# ── Helpers ────────────────────────────────────────────────────

def _load_config():
    return config_loader.load(CONFIG_PATH)


def _list_briefs() -> list:
    pattern = os.path.join(BRIEFS_DIR, "brief_veille_*.md")
    files = sorted(glob.glob(pattern), reverse=True)
    briefs = []
    for f in files:
        name = os.path.basename(f)
        date_str = name.replace("brief_veille_", "").replace(".md", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            date_fmt = dt.strftime("%d %B %Y")
        except Exception:
            date_fmt = date_str
        try:
            with open(f, "r", encoding="utf-8") as fp:
                content = fp.read()
            article_count = content.count("### ")
        except Exception:
            article_count = 0
        briefs.append({"filename": name, "date": date_fmt, "path": f, "article_count": article_count})
    return briefs


def _load_recent_topics() -> list:
    try:
        with open(RECENT_TOPICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_recent_topic(topic: str, period: str, lang: str):
    recent = _load_recent_topics()
    # Dédupliquer (move to front si déjà présent)
    recent = [r for r in recent if r.get("topic", "").lower() != topic.lower()]
    recent.insert(0, {
        "topic": topic,
        "period": period,
        "lang": lang,
        "timestamp": datetime.now().isoformat(),
    })
    recent = recent[:8]
    os.makedirs(os.path.dirname(RECENT_TOPICS_PATH), exist_ok=True)
    with open(RECENT_TOPICS_PATH, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=2)


def _build_custom_config(topic: str, base_config: dict, period_days: int = 7, lang: str = "fr") -> dict:
    words = [w.strip() for w in topic.replace(",", " ").split() if len(w.strip()) > 2]
    hn_query = " OR ".join(words[:6]) if words else topic
    devto_tags = [w.lower() for w in words[:2]] if words else []

    return {
        "profile_name": topic.title(),
        "profile_icon": "🔍",
        "profile_description": f"Veille personnalisée : {topic}",
        "keywords": [topic.lower()] + [w.lower() for w in words],
        "period_days": period_days,
        "language": lang,
        "sources": {
            "hackernews": {"enabled": True, "query": hn_query, "hits_per_page": 15, "weight": 1.3},
            "reddit": {"enabled": True, "subreddits": [], "search_query": hn_query, "limit": 10, "weight": 1.1},
            "rss_feeds": {"enabled": False, "feeds": [], "max_entries_per_feed": 8},
            "devto": {"enabled": True, "tags": devto_tags, "per_page": 10, "weight": 1.2},
            "github": {"enabled": True, "query": hn_query, "per_page": 8, "weight": 1.1},
            "lobsters": {"enabled": True, "tags": [], "limit": 10, "weight": 1.25},
            "arxiv": {"enabled": False, "query": hn_query, "max_results": 6, "weight": 1.4},
        },
        "max_articles": base_config.get("max_articles", 12),
        "dedup_window_days": base_config.get("dedup_window_days", 3),
        "llm": base_config.get("llm", {}),
        "active_profile_key": "custom",
        "all_profiles": base_config.get("all_profiles", {}),
    }


def _run_pipeline(config: dict):
    raw_articles = fetcher.fetch_all(config)
    if not raw_articles:
        print("[WEB] Aucun article récupéré.")
        return
    filtered, meta = filter.filter_articles(
        raw_articles,
        config["keywords"],
        dedup_window_days=config.get("dedup_window_days", 3),
    )
    if not filtered:
        print("[WEB] Aucun article pertinent.")
        return
    top = filtered[:config["max_articles"]]
    summarized = summarize.summarize_batch(top, config)
    brief_generator.generate(summarized, config=config, meta=meta, output_dir=BRIEFS_DIR)
    print("[WEB] ✅ Veille terminée.")


def _run_veille_sync(period_days: int = 7, lang: str = "fr"):
    _pipeline_state["running"] = True
    _pipeline_state["started_at"] = datetime.now().isoformat()
    try:
        config = _load_config()
        config["period_days"] = period_days
        config["language"] = lang
        _run_pipeline(config)
    except Exception as e:
        import traceback
        print(f"[WEB] ❌ Erreur : {e}")
        traceback.print_exc()
    finally:
        _pipeline_state["running"] = False


def _run_custom_sync(topic: str, period_days: int = 7, lang: str = "fr", period_key: str = "week"):
    _pipeline_state["running"] = True
    _pipeline_state["started_at"] = datetime.now().isoformat()
    try:
        base_config = _load_config()
        config = _build_custom_config(topic, base_config, period_days, lang)
        _run_pipeline(config)
        _save_recent_topic(topic, period_key, lang)
    except Exception as e:
        import traceback
        print(f"[WEB] ❌ Erreur custom : {e}")
        traceback.print_exc()
    finally:
        _pipeline_state["running"] = False


# ── Routes ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, msg: str = ""):
    config = _load_config()
    briefs = _list_briefs()
    return templates.TemplateResponse(request, "index.html", {
        "briefs": briefs,
        "count": len(briefs),
        "profile_name": config["profile_name"],
        "profile_icon": config["profile_icon"],
        "profile_desc": config["profile_description"],
        "profile_key": config["active_profile_key"],
        "all_profiles": config["all_profiles"],
        "running": _pipeline_state["running"],
        "recent_topics": _load_recent_topics(),
        "msg": msg,
    })


@app.post("/profile")
def switch_profile(profile: str = Form(...)):
    import yaml
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if profile not in raw.get("profiles", {}):
        raise HTTPException(status_code=400, detail=f"Profil '{profile}' inconnu")
    raw["active_profile"] = profile
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, sort_keys=False)
    return RedirectResponse(url="/?msg=profile_changed", status_code=303)


@app.post("/run")
def run_veille(
    background_tasks: BackgroundTasks,
    period: str = Form("week"),
    lang: str = Form("fr"),
):
    if _pipeline_state["running"]:
        return RedirectResponse(url="/?msg=veille_started", status_code=303)
    days = _PERIOD_DAYS.get(period, 7)
    background_tasks.add_task(_run_veille_sync, days, lang)
    return RedirectResponse(url="/?msg=veille_started", status_code=303)


@app.post("/run-custom")
def run_custom(
    background_tasks: BackgroundTasks,
    topic: str = Form(...),
    period: str = Form("week"),
    lang: str = Form("fr"),
):
    if _pipeline_state["running"]:
        return RedirectResponse(url="/?msg=veille_started", status_code=303)
    topic = topic.strip()
    if not topic:
        return RedirectResponse(url="/", status_code=303)
    days = _PERIOD_DAYS.get(period, 7)
    background_tasks.add_task(_run_custom_sync, topic, days, lang, period)
    return RedirectResponse(url="/?msg=veille_started", status_code=303)


@app.get("/brief/{filename}", response_class=HTMLResponse)
def read_brief(request: Request, filename: str):
    if _pipeline_state["running"]:
        return RedirectResponse(url="/?msg=veille_locked", status_code=303)
    filepath = os.path.join(BRIEFS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Brief non trouvé")
    with open(filepath, "r", encoding="utf-8") as f:
        md_content = f.read()
    html_content = markdown.markdown(md_content, extensions=["extra", "nl2br", "tables"])
    date_raw = filename.replace("brief_veille_", "").replace(".md", "")
    try:
        date_fmt = datetime.strptime(date_raw, "%Y-%m-%d").strftime("%d %B %Y")
    except Exception:
        date_fmt = date_raw
    return templates.TemplateResponse(request, "brief.html", {
        "filename": filename,
        "html_content": html_content,
        "date": date_fmt,
    })


@app.get("/api/status")
def api_status():
    config = _load_config()
    briefs = _list_briefs()
    return {
        "status": "ok",
        "profile": config["profile_name"],
        "llm_model": config["llm"].get("model"),
        "briefs_count": len(briefs),
        "latest_brief": briefs[0]["filename"] if briefs else None,
        "running": _pipeline_state["running"],
    }
