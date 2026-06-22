"""Orchestrateur de la récupération des sources selon le profil actif."""
from typing import List, Dict
from sources import hackernews, reddit, rss_feeds, devto, github_trending, lobsters, arxiv


def fetch_all(config: dict) -> List[Dict]:
    all_articles = []
    src_cfg = config.get("sources", {})
    since = config.get("period_days", 7)

    print(f"\n🔍 Profil : {config.get('profile_name', 'Veille')} — {since}j")

    # 1. Hacker News
    hn = src_cfg.get("hackernews", {})
    if hn.get("enabled"):
        print("📡 [Hacker News]")
        all_articles.extend(hackernews.fetch(
            weight=hn.get("weight", 1.3),
            query=hn.get("query", "AI"),
            hits=hn.get("hits_per_page", 15),
            since_days=since,
        ))

    # 2. Reddit
    rd = src_cfg.get("reddit", {})
    if rd.get("enabled"):
        print("📡 [Reddit]")
        subs = rd.get("subreddits", [])
        sq = rd.get("search_query", "")
        if subs:
            all_articles.extend(reddit.fetch(
                subreddits=subs, limit=rd.get("limit", 10),
                weight=rd.get("weight", 1.1), since_days=since,
            ))
        elif sq:
            all_articles.extend(reddit.search_all(
                query=sq, limit=rd.get("limit", 10),
                weight=rd.get("weight", 1.1), since_days=since,
            ))

    # 3. Flux RSS
    rss = src_cfg.get("rss_feeds", {})
    if rss.get("enabled"):
        print("📡 [Flux RSS]")
        all_articles.extend(rss_feeds.fetch(
            feeds=rss.get("feeds", []),
            max_entries_per_feed=rss.get("max_entries_per_feed", 8),
            since_days=since,
        ))

    # 4. Dev.to
    dt = src_cfg.get("devto", {})
    if dt.get("enabled"):
        print("📡 [Dev.to]")
        all_articles.extend(devto.fetch(
            tags=dt.get("tags", []),
            per_page=dt.get("per_page", 10),
            weight=dt.get("weight", 1.2),
        ))

    # 5. GitHub
    gh = src_cfg.get("github", {})
    if gh.get("enabled"):
        print("📡 [GitHub]")
        all_articles.extend(github_trending.fetch(
            query=gh.get("query", ""),
            per_page=gh.get("per_page", 8),
            weight=gh.get("weight", 1.1),
            since_days=since,
        ))

    # 6. Lobste.rs
    lb = src_cfg.get("lobsters", {})
    if lb.get("enabled"):
        print("📡 [Lobste.rs]")
        all_articles.extend(lobsters.fetch(
            tags=lb.get("tags", []),
            limit=lb.get("limit", 15),
            weight=lb.get("weight", 1.25),
        ))

    # 7. ArXiv
    ax = src_cfg.get("arxiv", {})
    if ax.get("enabled"):
        print("📡 [ArXiv]")
        all_articles.extend(arxiv.fetch(
            query=ax.get("query", ""),
            max_results=ax.get("max_results", 8),
            weight=ax.get("weight", 1.4),
        ))

    return all_articles
