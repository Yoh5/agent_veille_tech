"""Source : ArXiv — preprints de recherche via l'API Atom publique."""
import feedparser
from typing import List, Dict


def fetch(query: str = "artificial intelligence", max_results: int = 8, weight: float = 1.4) -> List[Dict]:
    articles = []
    try:
        safe_q = query.replace(" ", "+")
        url = (
            "http://export.arxiv.org/api/query"
            f"?search_query=ti:{safe_q}+OR+abs:{safe_q}"
            f"&start=0&max_results={max_results}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )
        parsed = feedparser.parse(url)

        for entry in parsed.entries:
            title = entry.get("title", "").replace("\n", " ").strip()
            if not title:
                continue

            abstract = entry.get("summary", "").replace("\n", " ").strip()
            authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])[:3])
            content = f"Auteurs : {authors}\n\n{abstract}" if authors else abstract

            # Utiliser l'URL de la page abstraite (og:image disponible, lecteur accessible)
            # Conserver le lien PDF dans le contenu
            abstract_url = entry.get("link", "")  # https://arxiv.org/abs/{id}
            pdf_url = ""
            for link in entry.get("links", []):
                if link.get("type") == "application/pdf":
                    pdf_url = link.get("href", "")
                    break
            if pdf_url:
                content = f"{content}\n\n📄 PDF : {pdf_url}"

            articles.append({
                "source": "ArXiv",
                "title": title,
                "url": abstract_url,  # page abstraite → og:image fonctionnel
                "content": content[:2500],
                "published": entry.get("published", ""),
                "raw_weight": weight,
            })

        print(f"   ✓ [ArXiv] {len(articles)} preprints")
    except Exception as e:
        print(f"   ⚠️  [ArXiv] Erreur : {e}")

    return articles
