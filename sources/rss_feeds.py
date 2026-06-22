"""Source : Flux RSS génériques."""
import feedparser
import re
from datetime import datetime, timedelta
from typing import List, Dict


def _parse_date(s: str):
    if not s:
        return None
    import email.utils
    try:
        t = email.utils.parsedate(s)
        if t:
            return datetime(*t[:6])
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt).replace(tzinfo=None)
        except Exception:
            pass
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch(feeds: List[Dict], max_entries_per_feed: int = 8, since_days: int = 7) -> List[Dict]:
    articles = []
    cutoff = datetime.now() - timedelta(days=since_days)

    for feed_cfg in feeds:
        name = feed_cfg.get("name", "RSS")
        url = feed_cfg.get("url", "")
        weight = feed_cfg.get("weight", 1.0)

        if not url:
            continue

        try:
            parsed = feedparser.parse(url)
            count = 0

            for entry in parsed.entries[:max_entries_per_feed]:
                # Date filter
                pub_date = _parse_date(entry.get("published", "") or entry.get("updated", ""))
                if pub_date and pub_date < cutoff:
                    continue

                content = _strip_html(
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or (entry.get("content") or [{}])[0].get("value", "")
                    or entry.get("title", "")
                )[:3000]

                articles.append({
                    "source": name,
                    "title": entry.get("title", "Sans titre"),
                    "url": entry.get("link", ""),
                    "content": content,
                    "published": entry.get("published", ""),
                    "raw_weight": weight,
                })
                count += 1

            print(f"   ✓ [{name}] {count} articles")

        except Exception as e:
            print(f"   ⚠️  [RSS:{name}] Erreur : {e}")

    return articles
