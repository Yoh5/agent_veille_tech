"""Chargement et validation de la config YAML."""
import yaml
from typing import Dict, Any


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
