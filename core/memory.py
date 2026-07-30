"""Mémoire thématique long terme de l'agent de veille.

L'agent ne repart plus de zéro à chaque run : il enregistre le « profil
thématique » de chaque brief (poids par sujet + date). Cela lui permet de :

1. **Rappeler** le contexte récent au LLM (jugement de pertinence + synthèse)
   → privilégier les développements VRAIMENT nouveaux, sous-pondérer le déjà-vu.
2. **Raisonner sur la continuité / l'évolution** → section « 📈 Évolution » du
   brief : sujets nouveaux / en hausse / en baisse vs la période précédente.

Stockage par profil dans `output/agent_memory.json` (chemin surchargé par
`VEILLE_MEMORY_PATH` pour les tests). Aucun réseau. Tout est **fail-open** :
une mémoire absente ou corrompue = comportement historique, jamais d'erreur.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

_MEM_PATH = os.getenv(
    "VEILLE_MEMORY_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "agent_memory.json"),
)
_MAX_SNAPSHOTS = 60      # runs conservés par profil (auto-purge des plus anciens)


def _load() -> dict:
    try:
        with open(_MEM_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save(store: dict) -> None:
    os.makedirs(os.path.dirname(_MEM_PATH), exist_ok=True)
    tmp = _MEM_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _MEM_PATH)   # écriture atomique


def topics_from_articles(articles: List[Dict], keywords: List[str]) -> Dict[str, int]:
    """Profil thématique d'un lot d'articles : pour chaque mot-clé du profil,
    le nombre d'articles qui le mentionnent (titre + contenu, frontières de mot,
    insensible à la casse). Renvoie {sujet: nb_articles}, sujets absents omis."""
    counts: Dict[str, int] = {}
    for kw in keywords or []:
        k = (kw or "").strip()
        if not k:
            continue
        pat = re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE)
        hits = sum(1 for a in articles
                   if pat.search(f"{a.get('title', '')} {a.get('content', '')}"))
        if hits:
            counts[k] = hits
    return counts


def record_run(profile_key: str, articles: List[Dict], keywords: List[str]) -> dict:
    """Enregistre le profil thématique du brief publié (topics + date UTC).
    Renvoie le snapshot. No-op silencieux si l'écriture échoue."""
    snap = {"date": datetime.now(timezone.utc).isoformat(),
            "topics": topics_from_articles(articles, keywords)}
    try:
        store = _load()
        runs = store.get(profile_key) or []
        runs.append(snap)
        store[profile_key] = runs[-_MAX_SNAPSHOTS:]
        _save(store)
    except OSError:
        pass
    return snap


def _recent_runs(profile_key: str, days: int) -> List[dict]:
    runs = _load().get(profile_key) or []
    if not days:
        return runs
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for r in runs:
        try:
            if datetime.fromisoformat(r["date"]) >= cutoff:
                out.append(r)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _aggregate(runs: List[dict]) -> Dict[str, int]:
    agg: Dict[str, int] = {}
    for r in runs:
        for t, w in (r.get("topics") or {}).items():
            agg[t] = agg.get(t, 0) + int(w or 0)
    return agg


def recall_context(profile_key: str, lang: str = "fr", days: int = 14, top: int = 8) -> str:
    """Bloc texte des sujets dominants récents, injecté dans les prompts LLM
    (jugement + synthèse). "" si aucun historique."""
    runs = _recent_runs(profile_key, days)
    agg = _aggregate(runs)
    if not agg:
        return ""
    listed = ", ".join(f"{t} ({w})" for t, w in
                       sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:top])
    if lang == "en":
        return (f"Recent watch memory (last {days} days, {len(runs)} briefs) — dominant topics: "
                f"{listed}. Favour genuinely NEW developments and follow-ups; down-weight "
                "what has already been heavily covered.")
    return (f"Mémoire de veille récente ({days} derniers jours, {len(runs)} briefs) — sujets "
            f"dominants : {listed}. Privilégie les développements VRAIMENT nouveaux et les suites ; "
            "sous-pondère ce qui a déjà été très couvert.")


def diff_topics(current_topics: Dict[str, int], profile_key: str, days: int = 14) -> Dict[str, List[str]]:
    """Compare les sujets du run courant à la mémoire récente (le run courant
    n'est PAS encore enregistré au moment de l'appel). Renvoie
    {"new": [...], "rising": [...], "fading": [...]} (max 5 chacun)."""
    runs = _recent_runs(profile_key, days)
    n = len(runs)
    if not n:
        return {"new": [], "rising": [], "fading": []}
    past = _aggregate(runs)
    past_avg = {t: past[t] / n for t in past}

    new, rising = [], []
    for t, w in current_topics.items():
        avg = past_avg.get(t)
        if avg is None:
            new.append((t, w))
        elif w >= avg * 1.5 and w >= 2:
            rising.append((t, w))

    fading = [(t, avg) for t, avg in past_avg.items()
              if avg >= 1.0 and current_topics.get(t, 0) <= avg * 0.4]

    new.sort(key=lambda x: x[1], reverse=True)
    rising.sort(key=lambda x: x[1], reverse=True)
    fading.sort(key=lambda x: x[1], reverse=True)
    return {
        "new":    [t for t, _ in new[:5]],
        "rising": [t for t, _ in rising[:5]],
        "fading": [t for t, _ in fading[:5]],
    }
