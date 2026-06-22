"""Source : Lobste.rs — communauté tech à haut signal via API JSON publique."""
import requests
from typing import List, Dict

HEADERS = {"User-Agent": "VeilleTech/2.0"}


def fetch(tags: List[str] = [], limit: int = 15, weight: float = 1.25) -> List[Dict]:
    articles = []
    try:
        if tags:
            url = f"https://lobste.rs/t/{tags[0]}.json"
        else:
            url = "https://lobste.rs/hottest.json"

        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        for item in resp.json()[:limit]:
            article_url = item.get("url") or item.get("short_id_url", "")
            content = item.get("description", "") or item.get("title", "")
            tags_str = " ".join(item.get("tags", []))
            if tags_str:
                content = f"{content} [{tags_str}]"

            articles.append({
                "source": "Lobste.rs",
                "title": item.get("title", ""),
                "url": article_url,
                "content": content[:2000],
                "published": item.get("created_at", ""),
                "raw_weight": weight,
                "hn_points": item.get("score", 0),
                "hn_comments": item.get("comment_count", 0),
            })

        print(f"   ✓ [Lobste.rs] {len(articles)} articles")
    except Exception as e:
        print(f"   ⚠️  [Lobste.rs] Erreur : {e}")

    return articles
