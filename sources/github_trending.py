"""Source : GitHub — repos récents et tendance via l'API de recherche publique."""
import requests
from typing import List, Dict
from datetime import datetime, timedelta

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "VeilleTech/2.0",
}


def fetch(query: str = "ai", per_page: int = 8, weight: float = 1.1, since_days: int = 7) -> List[Dict]:
    articles = []
    since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{query} created:>{since}",
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()

        for repo in resp.json().get("items", []):
            desc = repo.get("description", "") or ""
            topics = " ".join(repo.get("topics", []))
            title = f"{repo['full_name']} — {desc[:80]}" if desc else repo["full_name"]
            content = f"{desc} {topics}".strip()[:1500] or title

            articles.append({
                "source": "GitHub",
                "title": title,
                "url": repo["html_url"],
                "content": content,
                "published": repo.get("created_at", ""),
                "raw_weight": weight,
                "hn_points": repo.get("stargazers_count", 0),
                "hn_comments": repo.get("forks_count", 0),
            })

        print(f"   ✓ [GitHub] {len(articles)} repos ({since_days}j)")
    except Exception as e:
        print(f"   ⚠️  [GitHub] Erreur : {e}")

    return articles
