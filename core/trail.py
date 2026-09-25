"""Piste de décision : ce que l'agent a lu avant de choisir.

Le jugement de pertinence et le deep-dive lisent des pages publiques, puis
décident. Quand une sélection surprend — un article hors sujet retenu, un
article évident écarté — la seule question utile est « sur quoi reposait cette
décision ». Les journaux d'appels modèle ne répondent pas : ils gardent le
prompt, pas la page qui l'a rempli, et rien n'empêche de les réécrire après.

Ce module branche `glassbox` sur le pipeline : chaque jugement et chaque
deep-dive devient un enregistrement chaîné qui cite, par empreinte, le texte
exact que le modèle a lu. Désactivé par défaut (`agent.trail: true` dans
config.yaml), et sans glassbox installé tout se dégrade en no-op — comme le
reste de l'agent, aucun ajout ne doit pouvoir faire échouer le pipeline.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from core import obs

_log = obs.get_logger("trail")

try:  # dégradation propre : glassbox est un supplément, jamais une dépendance dure
    from glassbox.recorder import Recorder as _GLASSBOX
except Exception:  # pragma: no cover - dépend de l'environnement
    _GLASSBOX = None


#: Variables qui portent une clé de modèle. Elles sont rédigées à la frontière,
#: avant écriture : le journal est chaîné, donc rien ne peut en être retiré
#: après coup sans casser la chaîne.
_SECRET_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NEBIUS_API_KEY", "GITHUB_TOKEN")


class _NoTrail:
    """Ce que reçoit le pipeline quand la piste est éteinte : rien ne se passe."""

    ledger = None

    def judgement(self, **_kwargs) -> None:
        return None

    def deep_dive(self, **_kwargs) -> None:
        return None

    def verify(self) -> List[str]:
        return []


class Trail:
    def __init__(self, root: Path, version: str) -> None:
        self._rec = _GLASSBOX(
            root,
            agent_version=version,
            secrets=[os.getenv(name) for name in _SECRET_ENV],
        )
        self.ledger = self._rec.ledger

    def judgement(self, *, articles: Sequence[Dict], selected: Sequence[Dict], prompt: str) -> None:
        """Le modèle a choisi. On garde ce qu'il a lu, et ce qu'il en a fait.

        La preuve citée est le prompt réellement envoyé, pas la liste d'articles :
        c'est le texte exact, extraits non fiables compris, et c'est là que se
        cacherait une injection.
        """
        with self._rec.decision("judge-relevance") as d:
            d.evidence(source="prompt:judge-relevance", payload=prompt.encode("utf-8"))
            kept = [a.get("url", "") for a in selected]
            for url in kept:
                d.act("select", url=url)
            d.outcome(
                action="select" if kept else "none",
                reason=f"{len(kept)} retenu(s) sur {len(articles)} candidat(s)",
            )

    def deep_dive(self, *, url: str, text: str, ok: bool) -> None:
        """Le texte rapporté est la matière la moins fiable du pipeline : une page
        entière, choisie par le modèle, injectée dans le contenu à résumer."""
        with self._rec.decision("deep-dive") as d:
            if ok and text:
                d.evidence(source=url, payload=text.encode("utf-8"), media_type="text/html")
                d.act("deep-dive", url=url, chars=len(text))
            else:
                d.refuse(f"refusé ou vide : {url[:120]}")

    def verify(self) -> List[str]:
        return self._rec.verify()


def open_trail(config: dict, root: Optional[Path] = None, version: str = "veille") -> object:
    """Ouvre la piste si `agent.trail` est vrai ET que glassbox est là.

    Toute erreur d'ouverture rend une piste éteinte plutôt que de propager :
    une trace absente est un manque, une exception est une panne.
    """
    if not config.get("agent", {}).get("trail", False):
        return _NoTrail()
    if _GLASSBOX is None:
        _log.info("Piste de décision demandée mais glassbox n'est pas installé — ignorée")
        return _NoTrail()
    try:
        return Trail(Path(root or "output/trail"), version)
    except Exception as error:  # pragma: no cover - défensif
        _log.warning("Piste de décision indisponible (%s) — le pipeline continue", error)
        return _NoTrail()
