"""Source : Reddit via endpoints JSON publics."""
import requests
from typing import List, Dict

HEADERS = {
    "User-Agent": "Mozilla/5.0 VeilleAgent/2.0 (compatible; +https://github.com)"
}

_PERIOD_MAP = {1: "day", 7: "week", 15: "month", 30: "month"}


def _period_to_t(since_days: int) -> str:
    for days, t in sorted(_PERIOD_MAP.items()):
        if since_days <= days:
            return t
    return "month"


def fetch(subreddits: List[str], limit: int = 10, weight: float = 1.1, since_days: int = 7) -> List[Dict]:
    articles = []
    t = _period_to_t(since_days)

    for sub in subreddits:
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
                print(f"   ⚠️  [Reddit] r/{sub} inaccessible ({resp.status_code})")
                return []

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
            print("   ⚠️  [Reddit Search] Bloqué (403)")
            return []
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
