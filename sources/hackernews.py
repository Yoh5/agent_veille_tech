"""Source : Hacker News via Algolia API.

L'API Algolia ne comprend pas l'opérateur « OR » : une requête
« AI OR LLM OR agent » est cherchée comme une phrase et ne matche rien.
On découpe donc la requête sur " OR " et on lance une recherche par terme,
puis on fusionne (dédup par objectID) et on trie par points."""
import requests
from datetime import datetime, timedelta
from typing import List, Dict


def fetch(weight: float = 1.3, query: str = "AI OR LLM", hits: int = 15, since_days: int = 7) -> List[Dict]:
    terms = [t.strip() for t in query.split(" OR ") if t.strip()] or [query]
    ts = int((datetime.now() - timedelta(days=since_days)).timestamp())

    merged: dict[str, dict] = {}
    errors = 0
    for term in terms[:8]:
        try:
            url = (
                "https://hn.algolia.com/api/v1/search"  # tri par pertinence/points
                f"?query={requests.utils.quote(term)}"
                f"&tags=story"
                f"&hitsPerPage={hits}"
                f"&numericFilters=created_at_i>{ts}"
            )
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                merged.setdefault(hit["objectID"], hit)
        except Exception as e:
            errors += 1
            print(f"   ⚠️  [HackerNews] terme '{term}' : {e}")

    # top `hits` par points, toutes recherches confondues
    top = sorted(merged.values(), key=lambda h: h.get("points", 0), reverse=True)[:hits]

    articles = []
    for hit in top:
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

    print(f"   ✓ [Hacker News] {len(articles)} articles ({len(terms)} terme(s), {since_days}j)")
    return articles
