# -*- coding: utf-8 -*-
"""Tests du chargement de configuration."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import config_loader

YAML = """
active_profile: ia
llm:
  provider: openai
  model: gpt-4o-mini
max_articles: 5
dedup_window_days: 3
profiles:
  ia:
    name: IA
    icon: "🤖"
    description: test
    keywords: [llm, rag]
    sources:
      hackernews: {enabled: true}
  autre:
    name: Autre
    keywords: [x]
    sources: {}
"""


def _write(tmp_path, content=YAML, active=None):
    if active:
        content = content.replace("active_profile: ia", f"active_profile: {active}")
    p = tmp_path / "config.yaml"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_profil_actif_resolu(tmp_path):
    cfg = config_loader.load(_write(tmp_path))
    assert cfg["profile_name"] == "IA"
    assert cfg["keywords"] == ["llm", "rag"]
    assert cfg["max_articles"] == 5
    assert cfg["dedup_window_days"] == 3
    assert cfg["llm"]["model"] == "gpt-4o-mini"
    assert cfg["active_profile_key"] == "ia"
    assert set(cfg["all_profiles"]) == {"ia", "autre"}


def test_profil_inconnu_leve_valueerror(tmp_path):
    with pytest.raises(ValueError):
        config_loader.load(_write(tmp_path, active="inexistant"))


# ── save_atomic ────────────────────────────────────────────────

def test_save_atomic_ecrit_yaml_valide(tmp_path):
    """Le fichier écrit est un YAML valide, relu à l'identique."""
    import yaml
    p = str(tmp_path / "config.yaml")
    data = {"language": "fr", "active_profile": "ia", "watch": {"enabled": True},
            "accents": "veille été à jour"}
    config_loader.save_atomic(p, data)
    with open(p, "r", encoding="utf-8") as f:
        reloaded = yaml.safe_load(f)
    assert reloaded == data


def test_save_atomic_remplace_sans_temp_residuel(tmp_path):
    """Après écriture, aucun fichier temporaire .config_*.tmp ne subsiste."""
    p = str(tmp_path / "config.yaml")
    config_loader.save_atomic(p, {"a": 1})
    config_loader.save_atomic(p, {"a": 2})   # écrase
    with open(p, "r", encoding="utf-8") as f:
        import yaml
        assert yaml.safe_load(f) == {"a": 2}
    residuels = [n for n in os.listdir(tmp_path) if n.startswith(".config_")]
    assert residuels == []
