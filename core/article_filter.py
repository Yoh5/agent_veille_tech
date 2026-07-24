"""Filtrage par mots-clés, déduplication persistante et scoring."""
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional, Set, Tuple

SEEN_FILE = os.path.join(os.path.dirname(__file__), "..", "output", "seen_articles.json")

# Seuil de similarité (Jaccard sur les mots du titre normalisé) au-delà duquel
# deux articles du même batch sont considérés comme la même actu.
_NEAR_DUP_THRESHOLD = 0.85


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


_SITE_SUFFIX_RE = re.compile(r"\s+[|\-–—]\s+[^|\-–—]{1,40}$")


def _strip_accents_lower(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()).split())


def _normalize_title(title: str) -> str:
    """Titre canonique pour la dédup : minuscules, sans accents, sans
    ponctuation, espaces compactés, et suffixe de site retiré
    (« … | Hacker News », « … - TechCrunch » — fréquent via Google News RSS).
    « GPT-5 lancé ! » et « GPT 5 lance » convergent ainsi vers la même forme.

    Garde-fou : on ne retire le suffixe que s'il reste ≥ 3 mots — évite de
    raboter un tiret de ponctuation (« Rust - une introduction »)."""
    base = _strip_accents_lower((title or "").strip())
    stripped = _strip_accents_lower(_SITE_SUFFIX_RE.sub("", (title or "").strip()))
    if stripped and len(stripped.split()) >= 3:
        return stripped
    return base


def _title_tokens(title: str) -> Set[str]:
    return set(_normalize_title(title).split())


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def _article_hash(article: dict) -> str:
    title = _normalize_title(article.get("title", ""))
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
    """Écarte les articles déjà vus lors de runs précédents ou en double dans
    le batch. NE persiste RIEN : seuls les articles réellement publiés dans un
    brief sont marqués vus, via mark_seen() appelée en fin de pipeline. Un
    article écarté par le filtre ou le plafond max_articles reste donc
    éligible pour les runs suivants."""
    seen = _load_seen(window_days)
    fresh = []
    skipped = 0
    seen_hashes: set = set()
    seen_urls: set = set()
    kept_token_sets: List[Set[str]] = []

    for art in articles:
        h = _article_hash(art)
        url = art.get("url", "")

        # Skip if seen in previous runs OR already seen in this batch (titre/URL exacts)
        if h in seen or h in seen_hashes or url in seen_urls:
            skipped += 1
            continue

        # Quasi-doublon : même actu reprise par une autre source (titre proche)
        tokens = _title_tokens(art.get("title", ""))
        if tokens and any(_jaccard(tokens, kept) >= _NEAR_DUP_THRESHOLD for kept in kept_token_sets):
            skipped += 1
            continue

        fresh.append(art)
        seen_hashes.add(h)
        kept_token_sets.append(tokens)
        if url:
            seen_urls.add(url)

    return fresh, skipped


def mark_seen(articles: List[Dict], window_days: int = 7) -> None:
    """Persiste les articles effectivement publiés dans un brief.
    À appeler APRÈS la génération du brief, avec la liste finale."""
    if not articles:
        return
    seen = _load_seen(window_days)
    now = datetime.now().isoformat()
    for art in articles:
        seen[_article_hash(art)] = now
    _save_seen(seen)


# ── Scoring ────────────────────────────────────────────────────

def _parse_published(raw: str) -> Optional[datetime]:
    """Parse tolérant des dates de publication (RFC 822 des flux RSS,
    ISO 8601 de HN/ArXiv/Dev.to). Retourne None si inconnu."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _freshness_bonus(article: dict) -> float:
    """Bonus de fraîcheur : une annonce d'aujourd'hui doit battre un article
    populaire de la semaine dernière. +40 % < 24 h, +25 % < 48 h, +10 % < 96 h."""
    dt = _parse_published(article.get("published", ""))
    if dt is None:
        return 0.0
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    age_h = (now - dt).total_seconds() / 3600.0
    if age_h < 0:       # horloge/timezone fantaisiste : pas de bonus
        return 0.0
    if age_h <= 24:
        return 0.40
    if age_h <= 48:
        return 0.25
    if age_h <= 96:
        return 0.10
    return 0.0


def _score(article: dict) -> float:
    """Score combiné : poids source × engagement × pertinence × fraîcheur."""
    w = article.get("raw_weight", 1.0)
    social = article.get("hn_points", 0) + article.get("reddit_score", 0)
    # Bonus social : jusqu'à +50 % pour les articles très populaires (500+ points)
    social_bonus = min(social, 500) / 1000.0
    # Bonus de pertinence : +10 % par mot-clé matché au-delà du premier (plafonné à +50 %)
    kw_bonus = 0.1 * min(article.get("kw_matches", 1) - 1, 5)
    return w * (1.0 + social_bonus) * (1.0 + kw_bonus) * (1.0 + _freshness_bonus(article))


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

    # 2. Filtrage par mots-clés (garde ≥1 match) — le nombre de matches
    #    est conservé sur l'article pour le bonus de pertinence du score
    filtered = []
    for art in fresh:
        kw = _keyword_score(art, keywords)
        if kw > 0:
            art["kw_matches"] = kw
            filtered.append(art)

    # 3. Tri par score combiné (poids source × engagement × pertinence)
    for art in filtered:
        art["score"] = round(_score(art), 3)
    filtered.sort(key=lambda a: a["score"], reverse=True)

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
