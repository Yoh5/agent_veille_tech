"""Boucle d'apprentissage — l'agent apprend les préférences du lecteur (👍/👎).

Le lecteur note les articles du flux live (👍 pertinent / 👎 hors-sujet). À partir
de ces retours, l'agent **synthétise une directive de préférence** (LLM) qui est
injectée dans le jugement de pertinence des prochains runs → il apprend ce qui
intéresse vraiment, au-delà des mots-clés.

Stockage par profil dans `output/agent_preferences.json` (`VEILLE_PREFS_PATH` pour
les tests). **Fail-open** : sans clé LLM, erreur, ou pas assez de signal → la
directive reste inchangée / vide et n'a aucun effet. Le pipeline continue.
"""
import json
import os
from datetime import datetime, timezone
from typing import List

from core import llm

_PREFS_PATH = os.getenv(
    "VEILLE_PREFS_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "agent_preferences.json"),
)
_MAX_ENTRIES = 60          # retours conservés par profil
_MIN_TO_SYNTH = 3          # pas de synthèse sous ce seuil (bruit)
_MAX_DIRECTIVE = 500


def _load() -> dict:
    try:
        with open(_PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save(store: dict) -> None:
    os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
    tmp = _PREFS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PREFS_PATH)   # écriture atomique


def _bucket(store: dict, profile_key: str) -> dict:
    b = store.get(profile_key)
    if not isinstance(b, dict):
        b = {"entries": [], "directive": ""}
    b.setdefault("entries", [])
    b.setdefault("directive", "")
    return b


def add_feedback(profile_key: str, title: str, rating) -> None:
    """Enregistre un retour 👍/👎 sur un article (par son titre). No-op silencieux
    en cas d'échec d'écriture."""
    title = (title or "").strip()
    if not title:
        return
    up = str(rating).strip().lower() in ("up", "1", "+", "like", "yes", "👍", "true")
    try:
        store = _load()
        b = _bucket(store, profile_key)
        b["entries"].append({"title": title[:200], "rating": "up" if up else "down",
                             "ts": datetime.now(timezone.utc).isoformat()})
        b["entries"] = b["entries"][-_MAX_ENTRIES:]
        store[profile_key] = b
        _save(store)
    except OSError:
        pass


def get_directive(profile_key: str) -> str:
    """Directive de préférence apprise ("" si aucune)."""
    return (_bucket(_load(), profile_key).get("directive") or "").strip()


def _titles(entries: List[dict], rating: str, cap: int = 15) -> List[str]:
    return [e.get("title", "") for e in entries if e.get("rating") == rating][-cap:]


def synthesize_directive(profile_key: str, config: dict) -> str:
    """Synthétise (LLM) une directive de préférence depuis les 👍/👎 récents et la
    persiste. Renvoie la directive courante inchangée si trop peu de signal, sans
    clé, ou en cas d'erreur (fail-open)."""
    store = _load()
    b = _bucket(store, profile_key)
    entries = b["entries"]
    if len(entries) < _MIN_TO_SYNTH:
        return b.get("directive", "")

    liked = _titles(entries, "up")
    disliked = _titles(entries, "down")
    lang = config.get("language", "fr")
    if lang == "en":
        prompt = (
            "A reader rated tech-watch articles. From the titles they found RELEVANT (👍) "
            "and OFF-TOPIC (👎), write ONE short directive (1-2 sentences) to steer future "
            "article selection toward their taste. Imperative, concrete, no preamble.\n\n"
            f"👍 Relevant: {liked}\n👎 Off-topic: {disliked}"
        )
    else:
        prompt = (
            "Un lecteur a noté des articles de veille. À partir des titres jugés PERTINENTS "
            "(👍) et HORS-SUJET (👎), écris UNE directive courte (1-2 phrases) pour orienter "
            "la sélection future vers ses goûts. À l'impératif, concret, sans préambule.\n\n"
            f"👍 Pertinents : {liked}\n👎 Hors-sujet : {disliked}"
        )
    raw, _usage, err = llm.complete(config, prompt, json_mode=False, max_tokens=200, temperature=0.3)
    if err or not (raw or "").strip():
        return b.get("directive", "")

    b["directive"] = raw.strip()[:_MAX_DIRECTIVE]
    store[profile_key] = b
    try:
        _save(store)
    except OSError:
        pass
    return b["directive"]


def preference_block(profile_key: str, lang: str = "fr") -> str:
    """Bloc texte à injecter dans le prompt de jugement ("" si aucune directive)."""
    d = get_directive(profile_key)
    if not d:
        return ""
    if lang == "en":
        return f"Learned reader preferences (from 👍/👎 feedback): {d}"
    return f"Préférences apprises du lecteur (retours 👍/👎) : {d}"
