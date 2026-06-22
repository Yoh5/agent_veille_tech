"""Orchestrateur de la récupération des sources — fetch parallèle."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Tuple

from sources import hackernews, reddit, rss_feeds, devto, github_trending, lobsters, arxiv


def fetch_all(config: dict) -> List[Dict]:
    src_cfg = config.get("sources", {})
    since = config.get("period_days", 7)

    print(f"\n🔍 Profil : {config.get('profile_name', 'Veille')} — {since}j")

    # Build task list: (label, callable, kwargs)
    tasks: List[Tuple[str, Callable, dict]] = []

    hn = src_cfg.get("hackernews", {})
    if hn.get("enabled"):
        tasks.append(("Hacker News", hackernews.fetch, {
            "weight": hn.get("weight", 1.3),
            "query": hn.get("query", "AI"),
            "hits": hn.get("hits_per_page", 15),
            "since_days": since,
        }))

    rd = src_cfg.get("reddit", {})
    if rd.get("enabled"):
        subs = rd.get("subreddits", [])
        sq = rd.get("search_query", "")
        if subs:
            tasks.append(("Reddit", reddit.fetch, {
                "subreddits": subs,
                "limit": rd.get("limit", 10),
                "weight": rd.get("weight", 1.1),
                "since_days": since,
            }))
        elif sq:
            tasks.append(("Reddit", reddit.search_all, {
                "query": sq,
                "limit": rd.get("limit", 10),
                "weight": rd.get("weight", 1.1),
                "since_days": since,
            }))

    rss = src_cfg.get("rss_feeds", {})
    if rss.get("enabled"):
        tasks.append(("Flux RSS", rss_feeds.fetch, {
            "feeds": rss.get("feeds", []),
            "max_entries_per_feed": rss.get("max_entries_per_feed", 8),
            "since_days": since,
        }))

    dt = src_cfg.get("devto", {})
    if dt.get("enabled"):
        tasks.append(("Dev.to", devto.fetch, {
            "tags": dt.get("tags", []),
            "per_page": dt.get("per_page", 10),
            "weight": dt.get("weight", 1.2),
        }))

    gh = src_cfg.get("github", {})
    if gh.get("enabled"):
        tasks.append(("GitHub", github_trending.fetch, {
            "query": gh.get("query", ""),
            "per_page": gh.get("per_page", 8),
            "weight": gh.get("weight", 1.1),
            "since_days": since,
        }))

    lb = src_cfg.get("lobsters", {})
    if lb.get("enabled"):
        tasks.append(("Lobste.rs", lobsters.fetch, {
            "tags": lb.get("tags", []),
            "limit": lb.get("limit", 15),
            "weight": lb.get("weight", 1.25),
        }))

    ax = src_cfg.get("arxiv", {})
    if ax.get("enabled"):
        tasks.append(("ArXiv", arxiv.fetch, {
            "query": ax.get("query", ""),
            "max_results": ax.get("max_results", 8),
            "weight": ax.get("weight", 1.4),
        }))

    if not tasks:
        print("   ⚠️  Aucune source activée dans le profil.")
        return []

    all_articles: List[Dict] = []

    # Fetch all sources in parallel
    print(f"📡 Fetch parallèle de {len(tasks)} source(s)…")
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_label = {
            executor.submit(fn, **kwargs): label
            for label, fn, kwargs in tasks
        }
        for future in as_completed(future_to_label):
            label = future_to_label[future]
            try:
                results = future.result()
                all_articles.extend(results)
            except Exception as e:
                print(f"   ⚠️  [{label}] Exception : {e}")

    return all_articles
