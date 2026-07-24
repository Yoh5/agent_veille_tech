"""Interface Web FastAPI — Agent de Veille Tech."""
# Magasin de certificats système (antivirus/proxy TLS) — AVANT tout usage réseau,
# ici et pas seulement dans run_web.py pour couvrir `uvicorn web.app:app` direct
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# .env chargé ici aussi (pas seulement dans run_web.py) pour couvrir
# le lancement direct `uvicorn web.app:app`
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import glob
import html as html_mod
import json
import os
import re
import sys
import threading
from datetime import datetime

import markdown
from markupsafe import Markup
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)

from core import config_loader, fetcher, article_filter, summarize, brief_generator, watcher

app = FastAPI(title="Agent de Veille Tech", version="3.0")

# ── Scheduler (mode veille continue) ──────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_scheduler = BackgroundScheduler()
_last_scan: dict = {"at": None, "added": 0, "breaking": 0}


def _watch_scan_job():
    # ne pas scanner pendant un run manuel
    with _pipeline_lock:
        if _pipeline_state["running"]:
            print("[WATCH] Scan sauté (run manuel en cours)")
            return
    try:
        config = _load_config()
        config["period_days"] = 1
        added = watcher.scan_once(config)
        _last_scan["at"] = datetime.now().isoformat(timespec="seconds")
        _last_scan["added"] = len(added)
        _last_scan["breaking"] = sum(1 for a in added if a.get("breaking"))
    except Exception as e:
        print(f"[WATCH] Erreur de scan : {e}")


def _daily_brief_job():
    try:
        config = _load_config()
        watcher.generate_daily_brief(config, BRIEFS_DIR)
        _invalidate_briefs_cache()
    except Exception as e:
        print(f"[WATCH] Erreur brief quotidien : {e}")


def _configure_scheduler():
    """(Re)programme les jobs selon config.yaml → watch."""
    cfg = _load_config().get("watch", {})
    for job_id in ("watch_scan", "daily_brief"):
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
    if cfg.get("enabled"):
        minutes = max(5, int(cfg.get("interval_minutes", 30)))
        _scheduler.add_job(_watch_scan_job, IntervalTrigger(minutes=minutes),
                           id="watch_scan", max_instances=1, coalesce=True)
        raw_time = cfg.get("daily_brief_time", "08:00")
        if isinstance(raw_time, int):
            # PyYAML (YAML 1.1) lit « 08:00 » sans guillemets comme 480 minutes
            hh_i, mm_i = divmod(raw_time, 60)
        else:
            hh, _, mm = str(raw_time).partition(":")
            hh_i, mm_i = int(hh or 8), int(mm or 0)
        _scheduler.add_job(_daily_brief_job,
                           CronTrigger(hour=hh_i % 24, minute=mm_i % 60),
                           id="daily_brief")
        print(f"[WATCH] Veille continue ACTIVE — scan toutes les {minutes} min, "
              f"brief quotidien à {cfg.get('daily_brief_time', '08:00')}")
    else:
        print("[WATCH] Veille continue inactive")


@app.on_event("startup")
def _start_scheduler():
    _scheduler.start()
    _configure_scheduler()

# ── State ──────────────────────────────────────────────────────
_pipeline_lock = threading.Lock()
_pipeline_state: dict = {
    "running": False,
    "started_at": None,
    "step": None,
    "error": None,
    "message": None,       # info non bloquante (ex : « aucun article »)
    "last_result": None,   # "ok" | "error"
    "llm_usage": None,     # {in, out, cost_usd, model} du dernier run
}

_PERIOD_DAYS = {"day": 1, "week": 7, "month": 15}
_BRIEF_FILENAME_RE = re.compile(r"^brief_veille_\d{4}-\d{2}-\d{2}(_\d{4})?\.md$")

# ── i18n de l'interface ────────────────────────────────────────
UI_STRINGS = {
    "fr": {
        "run": "Lancer la veille", "running": "En cours…", "analyzing": "Analyse en cours…",
        "period": "Période", "lang": "Langue", "day": "Hier", "week": "Cette semaine", "month": "15 jours",
        "free_search": "Recherche libre", "analyze": "Analyser",
        "free_placeholder": "Ex : quantum computing, Rust systems, blockchain DeFi, biotech CRISPR…",
        "free_hint": "Entrez n'importe quel sujet — toutes les sources sont interrogées automatiquement",
        "recent": "Récemment :", "profile": "Profil de veille", "active": "Actif",
        "briefs": "Briefs générés", "articles": "articles",
        "empty_briefs": "Aucun brief pour l'instant.<br>Lance ta première veille →",
        "locked": "Les briefs sont verrouillés<br>jusqu'à la fin de l'analyse",
        "steps": ["Collecte", "Filtre", "LLM", "Brief"],
        "toast_profile": "Profil mis à jour", "toast_started": "Veille lancée — le brief sera disponible à la fin de l'analyse",
        "toast_lang": "Langue appliquée", "toast_deleted": "Supprimé",
        "live": "Flux Live", "online": "EN LIGNE", "offline": "HORS LIGNE",
        "watch_active": "veille continue active (scan toutes les {n} min)", "watch_inactive": "veille continue inactive",
        "scan_now": "Scanner maintenant", "watch_on": "Veille continue ON", "watch_off": "Activer la veille continue",
        "last_scan": "dernier scan", "seen_at": "vu à", "delete": "Supprimer",
        "empty_live": "Le flux est vide pour l'instant.<br>Active la veille continue ou clique sur « Scanner maintenant » — les nouveaux articles apparaîtront ici au fil de l'eau, résumés automatiquement.",
        "stat_today": "aujourd'hui", "stat_breaking": "breaking", "stat_total": "au flux", "stat_interval": "intervalle",
        "back": "← Retour au dashboard", "brief_of": "Brief du",
        "key_points": "Points clés",
    },
    "en": {
        "run": "Run watch", "running": "Running…", "analyzing": "Analysis in progress…",
        "period": "Period", "lang": "Language", "day": "Yesterday", "week": "This week", "month": "15 days",
        "free_search": "Free search", "analyze": "Analyze",
        "free_placeholder": "E.g.: quantum computing, Rust systems, blockchain DeFi, biotech CRISPR…",
        "free_hint": "Enter any topic — every source is queried automatically",
        "recent": "Recent:", "profile": "Watch profile", "active": "Active",
        "briefs": "Generated briefs", "articles": "articles",
        "empty_briefs": "No brief yet.<br>Run your first watch →",
        "locked": "Briefs are locked<br>until the analysis completes",
        "steps": ["Fetch", "Filter", "LLM", "Brief"],
        "toast_profile": "Profile updated", "toast_started": "Watch started — the brief will be available when the analysis completes",
        "toast_lang": "Language applied", "toast_deleted": "Deleted",
        "live": "Live Feed", "online": "ONLINE", "offline": "OFFLINE",
        "watch_active": "continuous watch active (scan every {n} min)", "watch_inactive": "continuous watch inactive",
        "scan_now": "Scan now", "watch_on": "Continuous watch ON", "watch_off": "Enable continuous watch",
        "last_scan": "last scan", "seen_at": "seen at", "delete": "Delete",
        "empty_live": "The feed is empty for now.<br>Enable continuous watch or click “Scan now” — new articles will appear here as they come, automatically summarized.",
        "stat_today": "today", "stat_breaking": "breaking", "stat_total": "in feed", "stat_interval": "interval",
        "back": "← Back to dashboard", "brief_of": "Brief of",
        "key_points": "Key points",
    },
}


def _lang_and_t():
    lang = _load_config().get("language", "fr")
    if lang not in UI_STRINGS:
        lang = "fr"
    return lang, UI_STRINGS[lang]


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _rich(text: str) -> Markup:
    """Texte LLM → HTML sûr : échappé, puis **gras** rendu en <strong>."""
    escaped = html_mod.escape(text or "")
    return Markup(_BOLD_RE.sub(r"<strong>\1</strong>", escaped))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

BRIEFS_DIR = os.path.join(parent, "output", "briefs")
CONFIG_PATH = os.path.join(parent, "config.yaml")
RECENT_TOPICS_PATH = os.path.join(parent, "output", "recent_topics.json")

# Simple briefs cache (invalidated after each run)
_briefs_cache: list | None = None


# ── Helpers ────────────────────────────────────────────────────

_config_lock = threading.Lock()


def _load_config():
    return config_loader.load(CONFIG_PATH)


def _update_config(mutator):
    """Modifie config.yaml de façon sérialisée et atomique.

    `mutator(raw)` reçoit le dict YAML brut, le modifie en place (ou renvoie un
    dict). Verrou = pas de read-modify-write concurrents ; save_atomic = pas de
    fichier corrompu. Retourne le dict écrit."""
    import yaml
    with _config_lock:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        result = mutator(raw)
        if result is not None:
            raw = result
        config_loader.save_atomic(CONFIG_PATH, raw)
        return raw


def _invalidate_briefs_cache():
    global _briefs_cache
    _briefs_cache = None


def _list_briefs() -> list:
    global _briefs_cache
    if _briefs_cache is not None:
        return _briefs_cache

    pattern = os.path.join(BRIEFS_DIR, "brief_veille_*.md")
    files = sorted(glob.glob(pattern), reverse=True)
    briefs = []
    for f in files:
        name = os.path.basename(f)
        date_str = name.replace("brief_veille_", "").replace(".md", "")
        try:
            # Handle both YYYY-MM-DD and YYYY-MM-DD_HHMM formats
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
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

    _briefs_cache = briefs
    return briefs


def _load_recent_topics() -> list:
    try:
        with open(RECENT_TOPICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_recent_topic(topic: str, period: str, lang: str):
    recent = _load_recent_topics()
    recent = [r for r in recent if r.get("topic", "").lower() != topic.lower()]
    recent.insert(0, {
        "topic": topic, "period": period, "lang": lang,
        "timestamp": datetime.now().isoformat(),
    })
    recent = recent[:8]
    os.makedirs(os.path.dirname(RECENT_TOPICS_PATH), exist_ok=True)
    with open(RECENT_TOPICS_PATH, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=2)


def _build_custom_config(topic: str, base_config: dict, period_days: int = 7, lang: str = "fr") -> dict:
    words = [w.strip() for w in topic.replace(",", " ").split() if len(w.strip()) > 2]
    hn_query = " OR ".join(words[:6]) if words else topic
    devto_tags = [w.lower() for w in words[:3]] if words else []

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
        "dedup_window_days": base_config.get("dedup_window_days", 7),
        "llm": base_config.get("llm", {}),
        "active_profile_key": "custom",
        "all_profiles": base_config.get("all_profiles", {}),
    }


def _run_pipeline(config: dict, state: dict):
    state["step"] = "fetch"
    raw_articles, source_stats = fetcher.fetch_all(config)
    if not raw_articles:
        state["message"] = "Aucun article récupéré depuis les sources."
        print("[WEB] Aucun article récupéré.")
        return

    state["step"] = "filter"
    filtered, meta = article_filter.filter_articles(
        raw_articles,
        config["keywords"],
        dedup_window_days=config.get("dedup_window_days", 7),
    )
    if not filtered:
        state["message"] = "Aucun article nouveau ne correspond aux mots-clés."
        print("[WEB] Aucun article pertinent.")
        return

    state["step"] = "summarize"
    top = filtered[:config["max_articles"]]
    summarized = summarize.summarize_batch(top, config)
    usage = summarize.get_last_usage()

    state["step"] = "generate"
    meta["sources_stats"] = source_stats
    meta["llm_usage"] = usage
    state["llm_usage"] = usage
    brief_generator.generate(summarized, config=config, meta=meta, output_dir=BRIEFS_DIR)
    # seuls les articles publiés dans le brief sont marqués « vus »
    article_filter.mark_seen(summarized, config.get("dedup_window_days", 7))
    _invalidate_briefs_cache()
    print("[WEB] ✅ Veille terminée.")


def _run_veille_sync(period_days: int = 7, lang: str = "fr"):
    with _pipeline_lock:
        _pipeline_state["running"] = True
        _pipeline_state["started_at"] = datetime.now().isoformat()
        _pipeline_state["error"] = None
        _pipeline_state["message"] = None
        _pipeline_state["step"] = None
        _pipeline_state["last_result"] = None
    try:
        config = _load_config()
        config["period_days"] = period_days
        config["language"] = lang
        _run_pipeline(config, _pipeline_state)
        _pipeline_state["last_result"] = "ok"
    except Exception as e:
        import traceback
        msg = str(e)
        print(f"[WEB] ❌ Erreur : {msg}")
        traceback.print_exc()
        _pipeline_state["error"] = msg
        _pipeline_state["last_result"] = "error"
    finally:
        _pipeline_state["running"] = False
        _pipeline_state["step"] = None


def _run_custom_sync(topic: str, period_days: int = 7, lang: str = "fr", period_key: str = "week"):
    with _pipeline_lock:
        _pipeline_state["running"] = True
        _pipeline_state["started_at"] = datetime.now().isoformat()
        _pipeline_state["error"] = None
        _pipeline_state["message"] = None
        _pipeline_state["step"] = None
        _pipeline_state["last_result"] = None
    try:
        base_config = _load_config()
        config = _build_custom_config(topic, base_config, period_days, lang)
        _run_pipeline(config, _pipeline_state)
        _save_recent_topic(topic, period_key, lang)
        _pipeline_state["last_result"] = "ok"
    except Exception as e:
        import traceback
        msg = str(e)
        print(f"[WEB] ❌ Erreur custom : {msg}")
        traceback.print_exc()
        _pipeline_state["error"] = msg
        _pipeline_state["last_result"] = "error"
    finally:
        _pipeline_state["running"] = False
        _pipeline_state["step"] = None


# ── Routes ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, msg: str = ""):
    config = _load_config()
    briefs = _list_briefs()
    lang, t = _lang_and_t()
    return templates.TemplateResponse(request, "index.html", {
        "briefs": briefs,
        "count": len(briefs),
        "profile_name": config["profile_name"],
        "profile_icon": config["profile_icon"],
        "profile_desc": config["profile_description"],
        "profile_key": config["active_profile_key"],
        "all_profiles": config["all_profiles"],
        "running": _pipeline_state["running"],
        "pipeline_step": _pipeline_state.get("step"),
        "pipeline_error": _pipeline_state.get("error"),
        "last_result": _pipeline_state.get("last_result"),
        "recent_topics": _load_recent_topics(),
        "watch_enabled": bool(config.get("watch", {}).get("enabled")),
        "lang": lang, "t": t,
        "msg": msg,
    })


_LANG_NEXT_SAFE = {"/", "/live"}


@app.post("/language")
def switch_language(lang: str = Form(...), next: str = Form("/")):
    """Change la langue de l'interface ET du pipeline (persisté dans config.yaml).

    `next` = page d'origine (le sélecteur est dans la navbar, accessible partout) ;
    validé contre un safelist pour éviter toute redirection ouverte.
    """
    if lang not in UI_STRINGS:
        raise HTTPException(status_code=400, detail=f"Langue '{lang}' non supportée")

    def _set_lang(raw):
        raw["language"] = lang

    _update_config(_set_lang)
    target = "/"
    if next in _LANG_NEXT_SAFE:
        target = next
    elif next.startswith("/brief/") and _BRIEF_FILENAME_RE.match(next[len("/brief/"):]):
        target = next
    return RedirectResponse(url=f"{target}?msg=lang_changed", status_code=303)


@app.post("/profile")
def switch_profile(profile: str = Form(...)):
    def _set_profile(raw):
        if profile not in raw.get("profiles", {}):
            raise HTTPException(status_code=400, detail=f"Profil '{profile}' inconnu")
        raw["active_profile"] = profile

    _update_config(_set_profile)
    return RedirectResponse(url="/?msg=profile_changed", status_code=303)


@app.post("/run")
def run_veille(
    background_tasks: BackgroundTasks,
    period: str = Form("week"),
    lang: str = Form("fr"),
):
    with _pipeline_lock:
        if _pipeline_state["running"]:
            return RedirectResponse(url="/?msg=veille_started", status_code=303)
        # réservation DANS le lock : deux POST simultanés ne peuvent pas
        # lancer deux pipelines (le second voit running=True)
        _pipeline_state["running"] = True
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
    topic = topic.strip()
    if not topic:
        return RedirectResponse(url="/", status_code=303)
    with _pipeline_lock:
        if _pipeline_state["running"]:
            return RedirectResponse(url="/?msg=veille_started", status_code=303)
        _pipeline_state["running"] = True
    days = _PERIOD_DAYS.get(period, 7)
    background_tasks.add_task(_run_custom_sync, topic, days, lang, period)
    return RedirectResponse(url="/?msg=veille_started", status_code=303)


@app.get("/brief/{filename}", response_class=HTMLResponse)
def read_brief(request: Request, filename: str):
    # Security: validate filename to prevent path traversal
    if not _BRIEF_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    filepath = os.path.join(BRIEFS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Brief non trouvé")
    with open(filepath, "r", encoding="utf-8") as f:
        md_content = f.read()
    html_content = markdown.markdown(md_content, extensions=["extra", "nl2br", "tables"])
    date_raw = filename.replace("brief_veille_", "").replace(".md", "")[:10]
    try:
        date_fmt = datetime.strptime(date_raw, "%Y-%m-%d").strftime("%d %B %Y")
    except Exception:
        date_fmt = date_raw
    lang, t = _lang_and_t()
    return templates.TemplateResponse(request, "brief.html", {
        "filename": filename,
        "html_content": html_content,
        "date": date_fmt,
        "watch_enabled": bool(_load_config().get("watch", {}).get("enabled")),
        "lang": lang, "t": t,
    })


def _enrich_live_item(a: dict) -> dict:
    """Copie enrichie d'un item du flux pour le rendu (gras, points clés, acteurs)."""
    from core.brief_generator import _KNOWN_DOMAINS
    item = dict(a)
    item["summary_html"] = _rich(a.get("summary", ""))
    item["takeaway_html"] = _rich(a.get("takeaway", ""))
    item["highlights_html"] = [_rich(h) for h in a.get("highlights", []) if h]
    tags = []
    for name in a.get("actors", [])[:5]:
        domain = _KNOWN_DOMAINS.get(str(name).lower().strip())
        favicon = f"https://www.google.com/s2/favicons?domain={domain}&sz=32" if domain else ""
        tags.append({"name": name, "favicon": favicon})
    item["actor_tags"] = tags
    return item


@app.get("/live", response_class=HTMLResponse)
def live_page(request: Request):
    config = _load_config()
    watch_cfg = config.get("watch", {})
    feed = [_enrich_live_item(a) for a in watcher.load_feed()[:60]]
    lang, t = _lang_and_t()
    today = datetime.now().strftime("%Y-%m-%d")
    return templates.TemplateResponse(request, "live.html", {
        "feed": feed,
        "watch_enabled": bool(watch_cfg.get("enabled")),
        "interval": watch_cfg.get("interval_minutes", 30),
        "last_scan": _last_scan,
        "profile_name": config["profile_name"],
        "profile_icon": config["profile_icon"],
        "stat_today": sum(1 for a in feed if a.get("seen_at", "").startswith(today)),
        "stat_breaking": sum(1 for a in feed if a.get("breaking")),
        "lang": lang, "t": t,
    })


@app.post("/live/delete")
def live_delete(item_id: str = Form(...)):
    """Supprime un article du flux live."""
    if not re.match(r"^[0-9a-f]{12}$", item_id):
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    watcher.delete_from_feed(item_id)
    return RedirectResponse(url="/live", status_code=303)


@app.post("/brief/delete")
def brief_delete(filename: str = Form(...)):
    """Supprime un brief généré."""
    if not _BRIEF_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    filepath = os.path.join(BRIEFS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        _invalidate_briefs_cache()
    return RedirectResponse(url="/?msg=deleted", status_code=303)


@app.get("/api/live")
def api_live(since: str = ""):
    """Flux live (JSON). `since` = ISO seen_at pour ne recevoir que le delta."""
    feed = watcher.load_feed()
    if since:
        feed = [a for a in feed if a.get("seen_at", "") > since]
    watch_cfg = _load_config().get("watch", {})
    return {
        "watch_enabled": bool(watch_cfg.get("enabled")),
        "interval_minutes": watch_cfg.get("interval_minutes", 30),
        "last_scan": _last_scan,
        "count": len(feed),
        "articles": feed[:60],
    }


@app.post("/watch/toggle")
def watch_toggle():
    """Active/désactive la veille continue (persisté dans config.yaml)."""
    def _toggle(raw):
        watch = raw.setdefault("watch", {})
        watch["enabled"] = not bool(watch.get("enabled"))

    _update_config(_toggle)
    _configure_scheduler()
    return RedirectResponse(url="/live", status_code=303)


@app.post("/watch/scan-now")
def watch_scan_now(background_tasks: BackgroundTasks):
    """Déclenche un scan immédiat (sans attendre l'intervalle)."""
    background_tasks.add_task(_watch_scan_job)
    return RedirectResponse(url="/live?msg=scan_started", status_code=303)


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
        "step": _pipeline_state.get("step"),
        "last_result": _pipeline_state.get("last_result"),
        "error": _pipeline_state.get("error"),
        "message": _pipeline_state.get("message"),
        "llm_usage": _pipeline_state.get("llm_usage"),
    }
