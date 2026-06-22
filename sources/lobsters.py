"""Source : Lobste.rs — communauté tech à haut signal via API JSON publique."""
import requests
from typing import List, Dict, Optional

HEADERS = {"User-Agent": "VeilleTech/2.0"}


def fetch(tags: Optional[List[str]] = None, limit: int = 15, weight: float = 1.25) -> List[Dict]:
    """Fetch articles for ALL tags (not just the first one)."""
    if not tags:
        urls_to_fetch = ["https://lobste.rs/hottest.json"]
    else:
        urls_to_fetch = [f"https://lobste.rs/t/{tag}.json" for tag in tags]

    articles: List[Dict] = []
    seen_urls: set = set()

    for url in urls_to_fetch:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()

            for item in resp.json()[:limit]:
                article_url = item.get("url") or item.get("short_id_url", "")
                if not article_url or article_url in seen_urls:
                    continue
                seen_urls.add(article_url)

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

        except Exception as e:
            print(f"   ⚠️  [Lobste.rs {url.split('/')[-1]}] Erreur : {e}")

    print(f"   ✓ [Lobste.rs] {len(articles)} articles ({len(urls_to_fetch)} tag(s))")
    return articles
