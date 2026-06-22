"""Génère le brief Markdown final — bilingue FR/EN."""
import os
from datetime import datetime
from typing import List, Dict

# ── Traductions statiques ─────────────────────────────────────
_STATIC = {
    "fr": {
        "title":         "Brief de Veille",
        "period_labels": {1: "Hier", 7: "Cette semaine", 15: "15 derniers jours"},
        "days_suffix":   "jours",
        "trends":        "## 📈 Tendances du jour",
        "articles":      "## 📰 Articles",
        "takeaway":      "💡 **À retenir :**",
        "footer_at":     "à",
    },
    "en": {
        "title":         "Tech Watch Brief",
        "period_labels": {1: "Yesterday", 7: "This week", 15: "Last 15 days"},
        "days_suffix":   "days",
        "trends":        "## 📈 Top Trends",
        "articles":      "## 📰 Articles",
        "takeaway":      "💡 **Key takeaway:**",
        "footer_at":     "at",
    },
}

# ── Acteurs connus → domaine pour favicon ─────────────────────
_KNOWN_DOMAINS: dict[str, str] = {
    "google": "google.com", "alphabet": "abc.xyz",
    "openai": "openai.com", "microsoft": "microsoft.com",
    "meta": "meta.com", "facebook": "facebook.com",
    "instagram": "instagram.com", "apple": "apple.com",
    "amazon": "amazon.com", "aws": "aws.amazon.com",
    "nvidia": "nvidia.com", "anthropic": "anthropic.com",
    "mistral": "mistral.ai", "mistral ai": "mistral.ai",
    "hugging face": "huggingface.co", "huggingface": "huggingface.co",
    "deepmind": "deepmind.com", "google deepmind": "deepmind.com",
    "tesla": "tesla.com", "spacex": "spacex.com",
    "cloudflare": "cloudflare.com", "github": "github.com",
    "vercel": "vercel.com", "netflix": "netflix.com",
    "twitter": "x.com", "x": "x.com", "linkedin": "linkedin.com",
    "samsung": "samsung.com", "intel": "intel.com",
    "amd": "amd.com", "qualcomm": "qualcomm.com",
    "ibm": "ibm.com", "oracle": "oracle.com",
    "salesforce": "salesforce.com", "adobe": "adobe.com",
    "stripe": "stripe.com", "databricks": "databricks.com",
    "snowflake": "snowflake.com", "hashicorp": "hashicorp.com",
    "docker": "docker.com", "red hat": "redhat.com",
    "canonical": "canonical.com", "mozilla": "mozilla.org",
    "linux foundation": "linuxfoundation.org",
    "arxiv": "arxiv.org", "mit": "mit.edu", "stanford": "stanford.edu",
    "deepseek": "deepseek.com", "cohere": "cohere.com",
    "groq": "groq.com", "together ai": "together.ai",
    "perplexity": "perplexity.ai", "cursor": "cursor.sh",
    "replit": "replit.com", "huawei": "huawei.com",
    "baidu": "baidu.com", "alibaba": "alibaba.com",
    "tencent": "tencent.com", "bytedance": "bytedance.com",
    "tiktok": "tiktok.com", "palantir": "palantir.com",
    "atlassian": "atlassian.com",
}

# ── Badges type ───────────────────────────────────────────────
_TYPE_META: dict[str, tuple] = {
    #            emoji  css_class     FR label      EN label
    "Innovation": ("🚀", "innovation", "Innovation", "Innovation"),
    "Alerte":     ("⚠️",  "alerte",    "Alerte",     "Alert"),
    "Analyse":    ("📊", "analyse",   "Analyse",    "Analysis"),
    "Recherche":  ("🔬", "recherche", "Recherche",  "Research"),
    "Sécurité":   ("🛡️",  "securite",  "Sécurité",   "Security"),
    "Actualité":  ("📢", "actualite", "Actualité",  "News"),
}


def _type_badge(article_type: str, lang: str = "fr") -> str:
    emoji, css, fr_lbl, en_lbl = _TYPE_META.get(article_type, ("📰", "actualite", "Actualité", "News"))
    label = en_lbl if lang == "en" else fr_lbl
    return f'<span class="type-badge type-badge--{css}">{emoji} {label}</span>'


def _actor_badge(name: str) -> str:
    domain = _KNOWN_DOMAINS.get(name.lower().strip())
    if domain:
        fav = f"https://www.google.com/s2/favicons?domain={domain}&sz=16"
        return (
            f'<span class="actor-tag">'
            f'<img src="{fav}" class="actor-favicon" alt="" onerror="this.remove()">'
            f' {name}</span>'
        )
    return f'<span class="actor-tag">{name}</span>'


def _reading_time(art: dict, lang: str = "fr") -> str:
    if art.get("source") == "ArXiv":
        return "~15 min"
    words = len(art.get("content", "").split()) if art.get("content") else 80
    minutes = max(2, min(12, round(words / 120)))
    return f"~{minutes} min"


def generate(
    articles: List[Dict],
    config: dict,
    meta: dict = None,
    output_dir: str = "output/briefs",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    meta = meta or {}

    lang = config.get("language", "fr")
    s    = _STATIC.get(lang, _STATIC["fr"])

    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    filepath = os.path.join(output_dir, f"brief_veille_{date_str}.md")

    profile_name = config.get("profile_name", "Tech")
    profile_icon = config.get("profile_icon", "📡")
    profile_desc = config.get("profile_description", "")
    model        = config.get("llm", {}).get("model", "—")
    period_days  = config.get("period_days", 7)
    period_label = s["period_labels"].get(period_days, f"{period_days} {s['days_suffix']}")

    lines = [
        f"# {profile_icon} {s['title']} — {profile_name}",
        "",
        f"> {profile_desc}",
        f">",
        f"> **{len(articles)} articles** · {datetime.now().strftime('%d/%m/%Y')} {s['footer_at']} {time_str} · {period_label}",
        "",
        "---",
        "",
    ]

    # Tendances
    trends = meta.get("trends", {})
    if trends:
        lines += [s["trends"], ""]
        for kw, count in list(trends.items())[:6]:
            bar = "█" * min(count, 10)
            lines.append(f"- **{kw}** {bar} {count}")
        lines += ["", "---", ""]

    lines += [s["articles"], ""]

    for i, art in enumerate(articles, 1):
        # En-tête
        favicon = art.get("favicon_url", "")
        fav_html = (
            f'<img src="{favicon}" class="src-favicon" alt="" onerror="this.remove()">'
            if favicon else ""
        )

        meta_parts = [f"[{art['source']}]({art['url']})"]
        if art.get("hn_points"):
            meta_parts.append(f"⬆ {art['hn_points']}")
        if art.get("reddit_score"):
            meta_parts.append(f"⬆ {art['reddit_score']}")
        nb_comments = art.get("hn_comments") or art.get("reddit_comments")
        if nb_comments:
            meta_parts.append(f"💬 {nb_comments}")
        meta_parts.append(_reading_time(art, lang))

        badge_html = _type_badge(art.get("article_type", "Actualité"), lang)

        lines += [
            f"### {i}. {art['title']}",
            "",
            f"{badge_html}  {fav_html} {'  ·  '.join(meta_parts)}",
            "",
        ]

        # Image (float-right, le texte s'enroule)
        og = art.get("og_image", "")
        if og:
            lines += [
                f'<div class="article-img-wrap"><img src="{og}" class="article-img" alt="" onerror="this.parentElement.remove()"></div>',
                "",
            ]

        # Résumé
        if art.get("summary"):
            lines += [art["summary"], ""]

        # Points clés
        if art.get("highlights"):
            for point in art["highlights"]:
                lines.append(f"- {point}")
            lines.append("")

        # À retenir / Takeaway
        if art.get("takeaway"):
            lines += [f"> {s['takeaway']} {art['takeaway']}", ""]

        # Acteurs avec logos
        actors = art.get("actors", [])
        if actors:
            badges = "".join(_actor_badge(a) for a in actors)
            lines += [f'<div class="actors-row">{badges}</div>', ""]

        lines += ["---", ""]

    lines += [
        f"*{s['title']} · {datetime.now().strftime('%d/%m/%Y %H:%M')} · {profile_icon} {profile_name} · {model} · {period_label} · {lang.upper()}*",
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filepath
