"""Source : GitHub — repos récents et tendance via l'API de recherche."""
import os
import requests
from typing import List, Dict
from datetime import datetime, timedelta


def _get_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "VeilleTech/2.0",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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
            headers=_get_headers(),
            timeout=15,
        )

        # Log rate limit status
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        if resp.status_code == 403:
            print(f"   ⚠️  [GitHub] Rate limit atteint (set GITHUB_TOKEN pour 5000 req/h)")
            return []
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

        auth_status = "authentifié" if os.getenv("GITHUB_TOKEN") else f"non-auth, {remaining} req restantes"
        print(f"   ✓ [GitHub] {len(articles)} repos — {auth_status}")
    except Exception as e:
        print(f"   ⚠️  [GitHub] Erreur : {e}")

    return articles
