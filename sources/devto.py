"""Source : Dev.to via API publique (sans authentification)."""
import requests
from typing import List, Dict

HEADERS = {"User-Agent": "VeilleTech/2.0", "Accept": "application/json"}


def fetch(tags: List[str] = [], per_page: int = 10, weight: float = 1.2) -> List[Dict]:
    articles = []
    tag = tags[0] if tags else ""

    try:
        params: dict = {"per_page": per_page, "state": "rising"}
        if tag:
            params["tag"] = tag

        resp = requests.get("https://dev.to/api/articles", params=params,
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()

        for item in resp.json():
            title = item.get("title", "")
            if not title:
                continue
            articles.append({
                "source": "Dev.to",
                "title": title,
                "url": item.get("url", ""),
                "content": (item.get("description", "") or title)[:2000],
                "published": item.get("published_at", ""),
                "raw_weight": weight,
                "hn_points": item.get("positive_reactions_count", 0),
                "hn_comments": item.get("comments_count", 0),
            })

        print(f"   ✓ [Dev.to] {len(articles)} articles")
    except Exception as e:
        print(f"   ⚠️  [Dev.to] Erreur : {e}")

    return articles
