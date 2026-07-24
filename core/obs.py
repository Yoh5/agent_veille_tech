"""Observabilité : logging structuré et estimation du coût LLM.

`get_logger()` fournit un logger configuré une seule fois (niveau via
VEILLE_LOG_LEVEL). `estimate_cost()` convertit un nombre de tokens en coût USD
à partir d'une petite table de prix — un modèle inconnu renvoie 0.0 sans jamais
lever d'exception.
"""
import logging
import os

_CONFIGURED = False


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("VEILLE_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger("veille")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Logger nommé sous l'espace 'veille' (ex : veille.summarize)."""
    _configure_root()
    return logging.getLogger(f"veille.{name}")


# ── Coût LLM ───────────────────────────────────────────────────
# Prix en USD par million de tokens (in, out). Sources : tarifs publics.
# Les clés sont testées en sous-chaîne (insensible à la casse) pour couvrir les
# suffixes de version (ex. « gpt-4o-mini-2024-… »).
_PRICING = {
    "gpt-4o-mini":            (0.15, 0.60),
    "gpt-4o":                 (2.50, 10.00),
    "gpt-4.1-mini":           (0.40, 1.60),
    "gpt-4.1":                (2.00, 8.00),
    "claude-3-5-haiku":       (0.80, 4.00),
    "claude-3-5-sonnet":      (3.00, 15.00),
    "claude-sonnet-4":        (3.00, 15.00),
    "claude-opus-4":          (15.00, 75.00),
    "claude-haiku-4":         (1.00, 5.00),
}


def _lookup_pricing(model: str):
    m = (model or "").lower()
    # correspondance sur la clé la plus longue contenue dans le nom du modèle
    best = None
    for key, price in _PRICING.items():
        if key in m and (best is None or len(key) > len(best[0])):
            best = (key, price)
    return best[1] if best else None


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Coût estimé en USD. Modèle inconnu → 0.0. Ne lève jamais."""
    try:
        price = _lookup_pricing(model)
        if not price:
            return 0.0
        in_rate, out_rate = price
        return (in_tokens / 1_000_000.0) * in_rate + (out_tokens / 1_000_000.0) * out_rate
    except Exception:
        return 0.0
