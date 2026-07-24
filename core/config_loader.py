"""Chargement et validation de la config YAML."""
import os
import tempfile
import yaml
from typing import Dict, Any


def save_atomic(path: str, data: Dict[str, Any]) -> None:
    """Écrit la config YAML de façon atomique : un fichier temporaire dans le
    même dossier puis os.replace() — jamais de config.yaml à moitié écrite si
    le process meurt en cours d'écriture."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config_", suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load(path: str = "config.yaml") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    active = raw.get("active_profile", "intelligence_artificielle")
    profiles = raw.get("profiles", {})

    if active not in profiles:
        raise ValueError(
            f"Profil '{active}' inconnu. Disponibles : {list(profiles.keys())}"
        )

    profile = profiles[active]

    config = {
        "profile_name": profile["name"],
        "profile_icon": profile.get("icon", "📡"),
        "profile_description": profile.get("description", ""),
        "keywords": profile["keywords"],
        "sources": profile["sources"],
        "max_articles": raw.get("max_articles", 12),
        "dedup_window_days": raw.get("dedup_window_days", 3),
        "llm": raw.get("llm", {
            "model": "claude-sonnet-4-6",
            "temperature": 0.3,
            "max_tokens": 600,
        }),
        "watch": raw.get("watch", {}),
        "language": raw.get("language", "fr"),
        "all_profiles": {
            k: {
                "name": v["name"],
                "icon": v.get("icon", ""),
                "description": v.get("description", ""),
            }
            for k, v in profiles.items()
        },
        "active_profile_key": active,
    }

    return config
