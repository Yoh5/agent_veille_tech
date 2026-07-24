"""Mode veille continue : scan périodique des sources, flux live et
détection de « breaking news ».

Un scan récupère toutes les sources, ne garde que les articles nouveaux et
pertinents, en résume au plus `watch.max_per_scan` (coût LLM marginal), les
ajoute au flux live (output/live_feed.json) et les marque vus. Une annonce
issue d'une source officielle (OpenAI, Anthropic…) ou très populaire est
marquée `breaking: true` et mise en avant dans l'interface.

Le brief quotidien est généré à heure fixe à partir du flux live des
dernières 24 h — sans nouvel appel LLM, les résumés existent déjà.
"""
import hashlib
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List

from core import article_filter, brief_generator, fetcher, obs, summarize

_log = obs.get_logger("watcher")

LIVE_FEED_FILE = os.path.join(os.path.dirname(__file__), "..", "output", "live_feed.json")
LIVE_FEED_MAX = 200

_feed_lock = threading.Lock()


# ── Flux live ──────────────────────────────────────────────────

def load_feed() -> List[Dict]:
    try:
        with open(LIVE_FEED_FILE, "r", encoding="utf-8") as f:
            feed = json.load(f)
        # rétro-compatibilité : compléter l'id des anciens articles
        for a in feed:
            if not a.get("id"):
                a["id"] = _item_id(a)
        return feed
    except Exception:
        return []


def _save_feed(feed: List[Dict]) -> None:
    os.makedirs(os.path.dirname(LIVE_FEED_FILE), exist_ok=True)
    with open(LIVE_FEED_FILE, "w", encoding="utf-8") as f:
        json.dump(feed[:LIVE_FEED_MAX], f, ensure_ascii=False, indent=1)


def _item_id(art: Dict) -> str:
    base = f"{art.get('title', '')}|{art.get('url', '')}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def _append_to_feed(articles: List[Dict]) -> None:
    with _feed_lock:
        feed = load_feed()
        feed = articles + feed
        _save_feed(feed)


def delete_from_feed(item_id: str) -> bool:
    """Supprime un article du flux live par son id. Retourne True si trouvé."""
    with _feed_lock:
        feed = load_feed()
        kept = [a for a in feed if a.get("id") != item_id]
        if len(kept) == len(feed):
            return False
        _save_feed(kept)
        return True


# ── Breaking news ──────────────────────────────────────────────

def _is_breaking(art: Dict, watch_cfg: Dict) -> bool:
    official = set(watch_cfg.get("breaking_sources", []))
    if art.get("source") in official:
        return True
    threshold = int(watch_cfg.get("breaking_hn_points", 300))
    return (art.get("hn_points", 0) + art.get("reddit_score", 0)) >= threshold


# ── Scan périodique ────────────────────────────────────────────

def scan_once(config: dict) -> List[Dict]:
    """Un tour de veille : retourne les nouveaux articles ajoutés au flux."""
    watch_cfg = config.get("watch", {})
    max_per_scan = int(watch_cfg.get("max_per_scan", 5))

    config = dict(config)
    config.setdefault("period_days", 1)   # un scan ne regarde que le très récent

    raw, _stats = fetcher.fetch_all(config)
    if not raw:
        return []

    filtered, _meta = article_filter.filter_articles(
        raw, config["keywords"],
        dedup_window_days=config.get("dedup_window_days", 7),
    )
    if not filtered:
        return []

    fresh = filtered[:max_per_scan]
    summarized = summarize.summarize_batch(fresh, config)

    now = datetime.now().isoformat(timespec="seconds")
    for art in summarized:
        art["id"] = _item_id(art)
        art["seen_at"] = now
        art["breaking"] = _is_breaking(art, watch_cfg)
        art.pop("content", None)   # inutile dans le flux, allège le JSON

    _append_to_feed(summarized)
    article_filter.mark_seen(summarized, config.get("dedup_window_days", 7))

    n_breaking = sum(1 for a in summarized if a["breaking"])
    _log.info("+%d article(s) au flux live%s", len(summarized),
              f" dont {n_breaking} BREAKING" if n_breaking else "")
    return summarized


# ── Brief quotidien ────────────────────────────────────────────

def generate_daily_brief(config: dict, output_dir: str) -> str | None:
    """Consolide le flux live des dernières 24 h en un brief — sans appel LLM."""
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    articles = [a for a in load_feed() if a.get("seen_at", "") >= cutoff]
    if not articles:
        _log.info("Brief quotidien : rien de nouveau sur 24 h.")
        return None

    # breaking d'abord, puis score
    articles.sort(key=lambda a: (not a.get("breaking", False), -a.get("score", 0)))
    articles = articles[: config.get("max_articles", 12)]

    trends: Dict[str, int] = {}
    for a in articles:
        for kw in config.get("keywords", []):
            if kw.lower() in (a.get("title", "") + " " + a.get("summary", "")).lower():
                trends[kw] = trends.get(kw, 0) + 1
    trends = dict(sorted(trends.items(), key=lambda x: x[1], reverse=True)[:8])

    config = dict(config)
    config["period_days"] = 1
    path = brief_generator.generate(
        articles, config=config,
        # pas de llm_usage : le brief quotidien réutilise des résumés existants,
        # aucun appel LLM n'est fait ici (coût nul pour ce brief).
        meta={"trends": trends, "sources_stats": {}},
        output_dir=output_dir,
    )
    _log.info("Brief quotidien généré : %s", path)

    from core import notifier
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    notifier.send_brief(path, config_path, subject_prefix="📡 Brief quotidien")
    return path
