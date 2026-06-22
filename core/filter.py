"""Filtrage par mots-clés et déduplication persistante."""
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

SEEN_FILE = os.path.join(os.path.dirname(__file__), "..", "output", "seen_articles.json")


# ── Déduplication ─────────────────────────────────────────────

def _load_seen(window_days: int) -> dict:
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
        return {k: v for k, v in data.items() if v >= cutoff}
    except Exception:
        return {}


def _save_seen(seen: dict) -> None:
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)


def _article_hash(article: dict) -> str:
    title = article.get("title", "").lower().strip()
    return hashlib.md5(title.encode("utf-8")).hexdigest()[:16]


def _deduplicate(articles: List[Dict], window_days: int) -> Tuple[List[Dict], int]:
    seen = _load_seen(window_days)
    now = datetime.now().isoformat()
    fresh = []
    skipped = 0
    seen_urls: set = set()
    seen_titles: set = set()

    for art in articles:
        h = _article_hash(art)
        url = art.get("url", "")
        title_norm = art.get("title", "").lower().strip()[:80]

        if h in seen or url in seen_urls or title_norm in seen_titles:
            skipped += 1
            continue

        fresh.append(art)
        seen[h] = now
        seen_urls.add(url)
        seen_titles.add(title_norm)

    _save_seen(seen)
    return fresh, skipped


# ── Filtrage par mots-clés ────────────────────────────────────

def _matches_keywords(article: dict, keywords: List[str]) -> bool:
    """Retourne True si au moins un mot-clé est présent dans le titre ou le contenu."""
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    return any(kw.lower() in text for kw in keywords)


def _detect_trends(articles: List[Dict], keywords: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for art in articles:
        text = f"{art.get('title', '')} {art.get('content', '')}".lower()
        for kw in keywords:
            if kw.lower() in text:
                counts[kw] = counts.get(kw, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8])


# ── Point d'entrée ────────────────────────────────────────────

def filter_articles(
    articles: List[Dict],
    keywords: List[str],
    dedup_window_days: int = 3,
) -> Tuple[List[Dict], Dict]:
    """
    1. Déduplication inter-runs
    2. Filtrage : garde uniquement les articles avec au moins 1 mot-clé
    3. Détection de tendances

    Retourne (articles_filtrés, metadata)
    """
    if not articles:
        return [], {"total_fetched": 0, "deduped_skipped": 0, "fresh_fetched": 0, "passed_filter": 0, "trends": {}}

    # 1. Déduplication
    fresh, skipped = _deduplicate(articles, dedup_window_days)
    if skipped > 0:
        print(f"   🔁 {skipped} articles déjà vus ignorés (fenêtre {dedup_window_days}j)")

    # 2. Filtrage par mots-clés
    filtered = [art for art in fresh if _matches_keywords(art, keywords)]

    # 3. Tendances
    trends = _detect_trends(fresh, keywords)

    meta = {
        "total_fetched": len(articles),
        "deduped_skipped": skipped,
        "fresh_fetched": len(fresh),
        "passed_filter": len(filtered),
        "trends": trends,
    }

    return filtered, meta
