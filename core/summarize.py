"""Résumé des articles via Anthropic Claude — bilingue FR/EN."""
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict

from core import og_image

# Normalise les types retournés en anglais vers les valeurs FR internes
_EN_TO_FR_TYPE = {
    "Innovation": "Innovation",
    "Alert":      "Alerte",
    "Analysis":   "Analyse",
    "Research":   "Recherche",
    "Security":   "Sécurité",
    "News":       "Actualité",
}

_VALID_TYPES = {"Innovation", "Alerte", "Analyse", "Recherche", "Sécurité", "Actualité"}


def _get_api_key(llm_cfg: dict) -> str:
    return os.getenv("ANTHROPIC_API_KEY") or llm_cfg.get("anthropic_api_key", "")


def _build_prompt(art: dict, profile: str, lang: str) -> str:
    title   = art["title"]
    source  = art["source"]
    content = art.get("content", "")[:2500]

    if lang == "en":
        return (
            f"You are a {profile} monitoring expert. Summarize this article completely and informatively.\n\n"
            "EXACT Format (respect every field, no extra text):\n"
            "SUMMARY: [3-4 sentences. Precise context and main facts. "
            "Use **bold** for company/people names and key numbers (e.g. **OpenAI**, **$1.2B**).]\n"
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


def summarize_batch(articles: List[Dict], config: dict) -> List[Dict]:
    if not articles:
        return []

    llm_cfg = config.get("llm", {})
    profile = config.get("profile_name", "Tech")
    lang    = config.get("language", "fr")
    api_key = _get_api_key(llm_cfg)

    # Étape 1 : images + favicons en parallèle
    print("   → Récupération des aperçus images…")
    articles = og_image.enrich(articles, max_workers=8)

    # Étape 2 : résumés LLM
    if not api_key:
        print("   ⚠️  [Summarize] Clé ANTHROPIC_API_KEY introuvable.")
        for art in articles:
            _defaults(art)
        return articles

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        print(f"   ⚠️  [Summarize] Init Anthropic : {e}")
        for art in articles:
            _defaults(art)
        return articles

    model       = llm_cfg.get("model", "claude-sonnet-4-6")
    temperature = llm_cfg.get("temperature", 0.3)
    max_tokens  = llm_cfg.get("max_tokens", 700)
    print(f"   → Modèle : {model} — {len(articles)} articles [{lang.upper()}]")

    def _one(art: dict) -> dict:
        try:
            prompt = _build_prompt(art, profile, lang)
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            art.update(_parse(resp.content[0].text.strip()))
        except Exception as e:
            print(f"   ⚠️  '{art['title'][:45]}…' : {e}")
            _defaults(art)
        return art

    with ThreadPoolExecutor(max_workers=5) as ex:
        articles = list(ex.map(_one, articles))

    return articles


def _defaults(art: dict):
    art.setdefault("summary", art.get("content", "")[:500])
    art.setdefault("highlights", [])
    art.setdefault("takeaway", "")
    art.setdefault("actors", [])
    art.setdefault("article_type", "Actualité")


def _parse(raw: str) -> dict:
    lines = raw.split("\n")
    summary, highlights, takeaway, actors, article_type = "", [], "", [], ""
    section = None

    for line in lines:
        s = line.strip()
        u = s.upper()

        # ── Champs FR + EN ──────────────────────────────────────
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
            raw_type = s.split(":", 1)[1].strip().strip("[]").strip()
            # Normalise: 1re lettre capitale, puis traduction EN→FR si besoin
            raw_type = raw_type.capitalize()
            article_type = _EN_TO_FR_TYPE.get(raw_type, raw_type)
            section = "type"

        elif s.startswith("-") and section == "highlights":
            highlights.append(s[1:].strip())

        elif section == "summary" and not any(u.startswith(p) for p in
                ["POINTS", "À_RETENIR", "A_RETENIR", "TAKEAWAY", "ACTEURS", "ACTORS", "TYPE"]):
            if s:
                summary += " " + s

        elif section == "takeaway" and not any(u.startswith(p) for p in
                ["RÉSUMÉ", "RESUME", "SUMMARY", "POINTS", "ACTEURS", "ACTORS", "TYPE"]):
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
