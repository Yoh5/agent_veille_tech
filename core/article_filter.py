"""Filtrage par mots-clés, déduplication persistante et scoring."""
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

SEEN_FILE = os.path.join(os.path.dirname(__file__), "..", "output", "seen_articles.json")


# ── Déduplication ──────────────────────────────────────────────

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


def _url_domain(url: str) -> str:
    """Extract domain from URL for cross-source dedup."""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        return p.netloc.replace("www.", "")
    except Exception:
        return ""


def _deduplicate(articles: List[Dict], window_days: int) -> Tuple[List[Dict], int]:
    seen = _load_seen(window_days)
    now = datetime.now().isoformat()
    fresh = []
    skipped = 0
    seen_hashes: set = set()
    seen_urls: set = set()

    for art in articles:
        h = _article_hash(art)
        url = art.get("url", "")

        # Skip if seen in previous runs OR already seen in this batch
        if h in seen or h in seen_hashes or url in seen_urls:
            skipped += 1
            continue

        fresh.append(art)
        seen[h] = now
        seen_hashes.add(h)
        if url:
            seen_urls.add(url)

    _save_seen(seen)
    return fresh, skipped


# ── Scoring ────────────────────────────────────────────────────

def _score(article: dict) -> float:
    """Combined score: source weight × social engagement bonus."""
    w = article.get("raw_weight", 1.0)
    social = article.get("hn_points", 0) + article.get("reddit_score", 0)
    # Social bonus: up to +50% for very popular articles (500+ points)
    bonus = min(social, 500) / 1000.0
    return w * (1.0 + bonus)


# ── Filtrage par mots-clés ─────────────────────────────────────

def _keyword_score(article: dict, keywords: List[str]) -> int:
    """Count how many keywords appear in title+content (0 = no match)."""
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    return sum(1 for kw in keywords if kw.lower() in text)


def _detect_trends(articles: List[Dict], keywords: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for art in articles:
        text = f"{art.get('title', '')} {art.get('content', '')}".lower()
        for kw in keywords:
            if kw.lower() in text:
                counts[kw] = counts.get(kw, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8])


# ── Point d'entrée ─────────────────────────────────────────────

def filter_articles(
    articles: List[Dict],
    keywords: List[str],
    dedup_window_days: int = 7,
) -> Tuple[List[Dict], Dict]:
    """
    1. Déduplication inter-runs (titre complet, pas tronqué)
    2. Filtrage : garde les articles avec ≥1 mot-clé
    3. Tri par score = weight × (1 + engagement_bonus)
    4. Détection de tendances

    Retourne (articles_filtrés_triés, metadata)
    """
    if not articles:
        return [], {
            "total_fetched": 0, "deduped_skipped": 0,
            "fresh_fetched": 0, "passed_filter": 0, "trends": {}
        }

    # 1. Déduplication
    fresh, skipped = _deduplicate(articles, dedup_window_days)
    if skipped > 0:
        print(f"   🔁 {skipped} articles déjà vus ignorés (fenêtre {dedup_window_days}j)")

    # 2. Filtrage par mots-clés (garde ≥1 match)
    filtered = [art for art in fresh if _keyword_score(art, keywords) > 0]

    # 3. Tri par score combiné (weight + engagement)
    filtered.sort(key=_score, reverse=True)

    # 4. Tendances
    trends = _detect_trends(fresh, keywords)

    meta = {
        "total_fetched": len(articles),
        "deduped_skipped": skipped,
        "fresh_fetched": len(fresh),
        "passed_filter": len(filtered),
        "trends": trends,
    }

    return filtered, meta
