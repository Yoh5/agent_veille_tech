"""Source : Reddit via endpoints JSON publics, avec repli RSS.

Reddit bloque de plus en plus le JSON public (403) mais continue de servir
les flux RSS : en cas de 403/404 sur le JSON, on bascule automatiquement
sur le flux .rss (sans score ni compteur de commentaires)."""
import html
import re
import time
import requests
from typing import List, Dict

HEADERS = {
    "User-Agent": "Mozilla/5.0 VeilleAgent/2.0 (compatible; +https://github.com)"
}
_BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}
_EXT_LINK_RE = re.compile(r'href="([^"]+)"\s*>\s*\[link\]', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

_PERIOD_MAP = {1: "day", 7: "week", 15: "month", 30: "month"}


def _period_to_t(since_days: int) -> str:
    for days, t in sorted(_PERIOD_MAP.items()):
        if since_days <= days:
            return t
    return "month"


def fetch(subreddits: List[str], limit: int = 10, weight: float = 1.1, since_days: int = 7) -> List[Dict]:
    articles = []
    t = _period_to_t(since_days)

    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(3)  # espacer les requêtes : Reddit renvoie 429 en rafale
        sub = sub.strip().lstrip("/").replace("r/", "")
        result = _fetch_subreddit(sub, limit, weight, t)
        articles.extend(result)

    return articles


def _fetch_subreddit(sub: str, limit: int, weight: float, t: str = "week") -> List[Dict]:
    for sort in ("top", "new"):
        try:
            params = f"limit={limit}" + (f"&t={t}" if sort == "top" else "")
            url = f"https://www.reddit.com/r/{sub}/{sort}.json?{params}"
            resp = requests.get(url, headers=HEADERS, timeout=15)

            if resp.status_code in (403, 404):
                print(f"   ⚠️  [Reddit] r/{sub} JSON bloqué ({resp.status_code}) — repli RSS")
                return _fetch_rss(
                    f"https://www.reddit.com/r/{sub}/top/.rss?t={t}&limit={limit}",
                    f"Reddit r/{sub}", limit, weight,
                )

            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])

            articles = []
            for post in posts:
                p = post["data"]
                if p.get("distinguished") == "moderator":
                    continue

                # Prefer external URL for link posts
                is_self = p.get("is_self", False)
                ext_url = p.get("url", "")
                url = (
                    ext_url
                    if (not is_self and ext_url and not ext_url.startswith("https://www.reddit.com"))
                    else f"https://reddit.com{p['permalink']}"
                )

                content = p.get("selftext", "") or p["title"]
                if is_self and len(content) < 30:
                    content = p["title"]

                articles.append({
                    "source": f"Reddit r/{sub}",
                    "title": p["title"],
                    "url": url,
                    "content": content[:3000],
                    "published": "",
                    "raw_weight": weight,
                    "reddit_score": p.get("score", 0),
                    "reddit_comments": p.get("num_comments", 0),
                })

            print(f"   ✓ [Reddit r/{sub}] {len(articles)} posts")
            return articles

        except Exception as e:
            print(f"   ⚠️  [Reddit r/{sub}] Erreur ({sort}) : {e}")
            continue

    return []


def _fetch_rss(rss_url: str, source_label: str, limit: int, weight: float) -> List[Dict]:
    """Repli RSS quand le JSON Reddit est bloqué. Pas de score ni de
    compteur de commentaires dans le flux — champs laissés à 0."""
    try:
        import feedparser
        resp = requests.get(rss_url, headers=_BROWSER_UA, timeout=15)
        if resp.status_code == 429:  # rate limit : une seule nouvelle tentative
            time.sleep(10)
            resp = requests.get(rss_url, headers=_BROWSER_UA, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        articles = []
        for e in feed.entries[:limit]:
            summary = getattr(e, "summary", "") or ""
            # le HTML du flux contient le lien externe sous la forme <a href="…">[link]</a>
            m = _EXT_LINK_RE.search(summary)
            ext = m.group(1) if m else ""
            url_art = ext if ext and "reddit.com" not in ext else getattr(e, "link", "")
            content = html.unescape(_TAG_RE.sub(" ", summary))
            content = re.sub(r"\s+", " ", content).strip()

            articles.append({
                "source": source_label,
                "title": getattr(e, "title", "").strip(),
                "url": url_art,
                "content": content[:3000] or getattr(e, "title", ""),
                "published": getattr(e, "published", ""),
                "raw_weight": weight,
                "reddit_score": 0,
                "reddit_comments": 0,
            })

        print(f"   ✓ [{source_label}] {len(articles)} posts (via RSS)")
        return articles
    except Exception as e:
        print(f"   ⚠️  [{source_label}] Repli RSS échoué : {e}")
        return []


def search_all(query: str, limit: int = 10, weight: float = 1.1, since_days: int = 7) -> List[Dict]:
    """Recherche globale sur Reddit — utilisé pour les domaines libres."""
    articles = []
    t = _period_to_t(since_days)
    try:
        url = (
            "https://www.reddit.com/search.json"
            f"?q={requests.utils.quote(query)}&sort=top&t={t}&limit={limit}&type=link"
        )
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 403:
            print("   ⚠️  [Reddit Search] JSON bloqué (403) — repli RSS")
            return _fetch_rss(
                "https://www.reddit.com/search.rss"
                f"?q={requests.utils.quote(query)}&sort=top&t={t}&limit={limit}",
                "Reddit", limit, weight,
            )
        resp.raise_for_status()

        for post in resp.json().get("data", {}).get("children", []):
            p = post["data"]
            if p.get("distinguished") == "moderator":
                continue
            is_self = p.get("is_self", False)
            ext_url = p.get("url", "")
            url_art = (
                ext_url
                if (not is_self and ext_url and not ext_url.startswith("https://www.reddit.com"))
                else f"https://reddit.com{p['permalink']}"
            )
            content = p.get("selftext", "") or p["title"]
            articles.append({
                "source": "Reddit",
                "title": p["title"],
                "url": url_art,
                "content": content[:3000],
                "published": "",
                "raw_weight": weight,
                "reddit_score": p.get("score", 0),
                "reddit_comments": p.get("num_comments", 0),
            })

        print(f"   ✓ [Reddit Search] {len(articles)} posts")
    except Exception as e:
        print(f"   ⚠️  [Reddit Search] Erreur : {e}")
    return articles
