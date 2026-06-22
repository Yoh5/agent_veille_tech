"""Récupération og:image et favicon pour enrichir visuellement les briefs."""
import re
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from urllib.parse import urlparse

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_OG_PATTERNS = [
    r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
    r'<meta[^>]+name=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
]


def favicon_url(url: str) -> str:
    try:
        domain = urlparse(url).netloc
        if domain:
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
    except Exception:
        pass
    return ""


def _fetch_og_image(url: str) -> str:
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(
            url, timeout=9,
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr,en;q=0.9",
            },
            allow_redirects=True,
            stream=True,
        )
        # Read first 40 KB — og:image is always in <head>
        chunk = b""
        for c in resp.iter_content(chunk_size=8192):
            chunk += c
            if len(chunk) >= 40960:
                break

        text = chunk.decode("utf-8", errors="ignore")
        for pat in _OG_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                img = m.group(1).strip()
                if img.startswith("http"):
                    return img
    except Exception:
        pass
    return ""


def _get_image(article: Dict) -> str:
    source = article.get("source", "")
    url = article.get("url", "")

    # GitHub: social card générée instantanément sans HTTP call
    if source == "GitHub" and "github.com/" in url:
        path = url.replace("https://github.com/", "").split("?")[0].strip("/")
        if "/" in path:
            return f"https://opengraph.githubassets.com/1/{path}"

    return _fetch_og_image(url)


def _process_one(article: Dict) -> Dict:
    article["og_image"] = _get_image(article)
    article["favicon_url"] = favicon_url(article.get("url", ""))
    return article


def enrich(articles: List[Dict], max_workers: int = 8) -> List[Dict]:
    """Ajoute og_image et favicon_url à chaque article en parallèle."""
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_process_one, articles))
