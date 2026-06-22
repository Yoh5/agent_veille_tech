"""Résumé des articles via LLM — bilingue FR/EN. Supporte OpenAI et Anthropic."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict

from core import og_image

_EN_TO_FR_TYPE = {
    "Innovation": "Innovation",
    "Alert":      "Alerte",
    "Analysis":   "Analyse",
    "Research":   "Recherche",
    "Security":   "Sécurité",
    "News":       "Actualité",
}

_VALID_TYPES = {"Innovation", "Alerte", "Analyse", "Recherche", "Sécurité", "Actualité"}

CONTENT_MAX_CHARS = 6000
DEFAULT_MAX_TOKENS = 1200


# ── Prompt ─────────────────────────────────────────────────────

def _build_prompt(art: dict, profile: str, lang: str) -> str:
    title   = art["title"]
    source  = art["source"]
    content = art.get("content", "")[:CONTENT_MAX_CHARS]

    if lang == "en":
        return (
            f"You are a {profile} monitoring expert. Summarize this article completely and informatively.\n\n"
            "EXACT Format (respect every field, no extra text):\n"
            "SUMMARY: [3-4 sentences. Precise context and main facts. "
            "Use **bold** for company/people names and key numbers.]\n"
            "KEY_POINTS:\n"
            "- [verifiable fact with **number**, **name** or date]\n"
            "- [verifiable fact with **number**, **name** or date]\n"
            "- [verifiable fact with **number**, **name** or date]\n"
            "TAKEAWAY: [1 sentence: the most important strategic implication or lesson]\n"
            "ACTORS: [Org1, Person2, ...] (key organizations or people cited, max 4 — or leave empty)\n"
            "TYPE: [choose ONE from: Innovation | Alert | Analysis | Research | Security | News]\n\n"
            f"Title: {title}\nSource: {source}\nContent: {content}\n\n"
            "Reply ONLY with this format."
        )
    else:
        return (
            f"Tu es un expert en veille {profile}. Résume cet article de façon complète et informative.\n\n"
            "Format EXACT (respecte chaque champ, aucun texte supplémentaire) :\n"
            "RÉSUMÉ: [3-4 phrases. Contexte précis, faits principaux. "
            "Mets en **gras** les noms d'entreprises, de personnes et les chiffres importants.]\n"
            "POINTS_CLÉS:\n"
            "- [fait vérifiable avec **chiffre**, **nom** ou date]\n"
            "- [fait vérifiable avec **chiffre**, **nom** ou date]\n"
            "- [fait vérifiable avec **chiffre**, **nom** ou date]\n"
            "À_RETENIR: [1 seule phrase : l'implication stratégique ou la leçon la plus importante]\n"
            "ACTEURS: [Org1, Personne2, ...] (organisations ou personnes clés, max 4 — ou laisser vide)\n"
            "TYPE: [choisir UN parmi : Innovation | Alerte | Analyse | Recherche | Sécurité | Actualité]\n\n"
            f"Titre : {title}\nSource : {source}\nContenu : {content}\n\n"
            "Réponds UNIQUEMENT avec ce format."
        )


# ── Providers ──────────────────────────────────────────────────

def _call_openai(client, model: str, max_tokens: int, temperature: float, prompt: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _call_anthropic(client, model: str, max_tokens: int, temperature: float, prompt: str) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return any(kw in s for kw in ("rate_limit", "rate limit", "overloaded", "529", "too many requests"))


def _build_client(provider: str, llm_cfg: dict):
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY") or llm_cfg.get("openai_api_key", "")
        if not api_key:
            return None, "Clé OPENAI_API_KEY introuvable"
        try:
            from openai import OpenAI
            return OpenAI(api_key=api_key), None
        except ImportError:
            return None, "Package 'openai' non installé — pip install openai"

    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY") or llm_cfg.get("anthropic_api_key", "")
        if not api_key:
            return None, "Clé ANTHROPIC_API_KEY introuvable"
        try:
            import anthropic
            return anthropic.Anthropic(api_key=api_key), None
        except ImportError:
            return None, "Package 'anthropic' non installé — pip install anthropic"

    return None, f"Provider inconnu : '{provider}' (valeurs acceptées : openai | anthropic)"


# ── Point d'entrée ─────────────────────────────────────────────

def summarize_batch(articles: List[Dict], config: dict) -> List[Dict]:
    if not articles:
        return []

    llm_cfg     = config.get("llm", {})
    provider    = llm_cfg.get("provider", "openai")
    model       = llm_cfg.get("model", "gpt-4o-mini")
    temperature = llm_cfg.get("temperature", 0.3)
    max_tokens  = llm_cfg.get("max_tokens", DEFAULT_MAX_TOKENS)
    profile     = config.get("profile_name", "Tech")
    lang        = config.get("language", "fr")

    # Images + favicons en parallèle
    print("   → Récupération des aperçus images…")
    articles = og_image.enrich(articles, max_workers=8)

    client, err = _build_client(provider, llm_cfg)
    if client is None:
        print(f"   ⚠️  [Summarize] {err}")
        for art in articles:
            _defaults(art)
        return articles

    print(f"   → Provider : {provider} | Modèle : {model} | {len(articles)} articles [{lang.upper()}]")

    call_fn = _call_openai if provider == "openai" else _call_anthropic

    def _one(art: dict) -> dict:
        for attempt in range(3):
            try:
                prompt = _build_prompt(art, profile, lang)
                raw = call_fn(client, model, max_tokens, temperature, prompt)
                art.update(_parse(raw))
                return art
            except Exception as e:
                if _is_rate_limit(e):
                    wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    print(f"   ⏳ Rate limit — attente {wait}s (tentative {attempt + 1}/3)…")
                    time.sleep(wait)
                else:
                    print(f"   ⚠️  '{art['title'][:45]}…' : {e}")
                    break
        _defaults(art)
        return art

    # 3 appels LLM en parallèle max pour éviter les rate limits
    with ThreadPoolExecutor(max_workers=3) as ex:
        articles = list(ex.map(_one, articles))

    return articles


# ── Helpers ────────────────────────────────────────────────────

def _defaults(art: dict):
    art.setdefault("summary",      art.get("content", "")[:500])
    art.setdefault("highlights",   [])
    art.setdefault("takeaway",     "")
    art.setdefault("actors",       [])
    art.setdefault("article_type", "Actualité")


def _parse(raw: str) -> dict:
    lines = raw.split("\n")
    summary, highlights, takeaway, actors, article_type = "", [], "", [], ""
    section = None

    _SECTION_PREFIXES = [
        "RÉSUMÉ:", "RESUME:", "SUMMARY:",
        "POINTS_CLÉS:", "POINTS_CLES:", "KEY_POINTS:", "KEYPOINTS:",
        "À_RETENIR:", "A_RETENIR:", "TAKEAWAY:",
        "ACTEURS:", "ACTORS:",
        "TYPE:",
    ]

    for line in lines:
        s = line.strip()
        u = s.upper()

        if u.startswith(("RÉSUMÉ:", "RESUME:", "SUMMARY:")):
            summary = s.split(":", 1)[1].strip()
            section = "summary"

        elif u.startswith(("POINTS_CLÉS:", "POINTS_CLES:", "KEY_POINTS:", "KEYPOINTS:")):
            section = "highlights"

        elif u.startswith(("À_RETENIR:", "A_RETENIR:", "TAKEAWAY:")):
            takeaway = s.split(":", 1)[1].strip()
            section = "takeaway"

        elif u.startswith(("ACTEURS:", "ACTORS:")):
            raw_actors = s.split(":", 1)[1].strip().strip("[]")
            actors = [
                a.strip() for a in raw_actors.split(",")
                if a.strip() and a.strip().lower() not in ("vide", "aucun", "n/a", "none", "")
            ][:4]
            section = "actors"

        elif u.startswith("TYPE:"):
            raw_type = s.split(":", 1)[1].strip().strip("[]").strip().capitalize()
            article_type = _EN_TO_FR_TYPE.get(raw_type, raw_type)
            section = "type"

        elif s.startswith("-") and section == "highlights":
            highlights.append(s[1:].strip())

        elif section == "summary" and not any(u.startswith(p) for p in _SECTION_PREFIXES):
            if s:
                summary += " " + s

        elif section == "takeaway" and not any(u.startswith(p) for p in _SECTION_PREFIXES):
            if s:
                takeaway += " " + s

    if article_type not in _VALID_TYPES:
        article_type = "Actualité"

    return {
        "summary":      summary.strip() or raw[:600],
        "highlights":   highlights[:4],
        "takeaway":     takeaway.strip(),
        "actors":       actors,
        "article_type": article_type,
    }
