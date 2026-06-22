"""Source : Dev.to via API publique (sans authentification)."""
import requests
from typing import List, Dict, Optional

HEADERS = {"User-Agent": "VeilleTech/2.0", "Accept": "application/json"}


def fetch(tags: Optional[List[str]] = None, per_page: int = 10, weight: float = 1.2) -> List[Dict]:
    """Fetch articles for ALL tags (not just the first one)."""
    if not tags:
        tags = [""]

    articles: List[Dict] = []
    seen_urls: set = set()

    for tag in tags:
        try:
            params: dict = {"per_page": per_page, "state": "rising"}
            if tag:
                params["tag"] = tag

            resp = requests.get(
                "https://dev.to/api/articles", params=params, headers=HEADERS, timeout=15
            )
            resp.raise_for_status()

            for item in resp.json():
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or url in seen_urls:
                    continue
                seen_urls.add(url)
                articles.append({
                    "source": "Dev.to",
                    "title": title,
                    "url": url,
                    "content": (item.get("description", "") or title)[:2000],
                    "published": item.get("published_at", ""),
                    "raw_weight": weight,
                    "hn_points": item.get("positive_reactions_count", 0),
                    "hn_comments": item.get("comments_count", 0),
                })

        except Exception as e:
            label = f"tag={tag}" if tag else "top"
            print(f"   ⚠️  [Dev.to {label}] Erreur : {e}")

    print(f"   ✓ [Dev.to] {len(articles)} articles ({len(tags)} tag(s))")
    return articles
