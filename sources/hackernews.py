"""Source : Hacker News via Algolia API."""
import requests
from datetime import datetime, timedelta
from typing import List, Dict


def fetch(weight: float = 1.3, query: str = "AI OR LLM", hits: int = 15, since_days: int = 7) -> List[Dict]:
    articles = []
    try:
        ts = int((datetime.now() - timedelta(days=since_days)).timestamp())
        url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            f"?query={requests.utils.quote(query)}"
            f"&tags=story"
            f"&hitsPerPage={hits}"
            f"&numericFilters=created_at_i>{ts}"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for hit in data.get("hits", []):
            url_link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            content = hit.get("story_text", "") or hit["title"]

            articles.append({
                "source": "Hacker News",
                "title": hit["title"],
                "url": url_link,
                "content": content[:3000],
                "published": hit.get("created_at", ""),
                "raw_weight": weight,
                "hn_points": hit.get("points", 0),
                "hn_comments": hit.get("num_comments", 0),
            })

        print(f"   ✓ [Hacker News] {len(articles)} articles ({since_days}j)")

    except Exception as e:
        print(f"   ⚠️  [HackerNews] Erreur : {e}")

    return articles
