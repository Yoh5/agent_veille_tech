# -*- coding: utf-8 -*-
"""Tests de la boucle d'apprentissage (core/preferences) — sans réseau.

Stockage redirigé AVANT import ; l'appel LLM (`preferences.llm.complete`) est
monkeypatché."""
import os
import sys
import tempfile

_TMP = os.path.join(tempfile.gettempdir(), "veille_test_prefs.json")
os.environ["VEILLE_PREFS_PATH"] = _TMP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import preferences  # noqa: E402

_CFG = {"language": "fr", "llm": {"model": "gpt-4o-mini"}}


def setup_function(_=None):
    if os.path.exists(_TMP):
        os.remove(_TMP)


def _fake_complete(text, err=None):
    return lambda *a, **k: (text, {"in": 10, "out": 5}, err)


# ── add_feedback / get_directive ───────────────────────────────

def test_get_directive_empty_by_default():
    assert preferences.get_directive("ia") == ""
    assert preferences.preference_block("ia") == ""


def test_add_feedback_ignores_empty_title():
    preferences.add_feedback("ia", "   ", "up")
    assert preferences._load() == {}   # rien enregistré


def test_feedback_capped():
    for i in range(80):
        preferences.add_feedback("ia", f"article {i}", "up")
    entries = preferences._bucket(preferences._load(), "ia")["entries"]
    assert len(entries) <= preferences._MAX_ENTRIES


# ── synthesize_directive ───────────────────────────────────────

def test_synth_needs_min_signal(monkeypatch):
    called = {"v": False}
    monkeypatch.setattr(preferences.llm, "complete",
                        lambda *a, **k: called.__setitem__("v", True) or ("x", {}, None))
    preferences.add_feedback("ia", "un seul article", "up")   # 1 < 3
    assert preferences.synthesize_directive("ia", _CFG) == ""
    assert called["v"] is False   # pas d'appel LLM sous le seuil


def test_synth_builds_and_persists_directive(monkeypatch):
    monkeypatch.setattr(preferences.llm, "complete",
                        _fake_complete("Priorise les articles sur les agents LLM et le RAG."))
    for t in ["Agents LLM en prod", "RAG avancé", "Framboise à la crème"]:
        preferences.add_feedback("ia", t, "up" if "LLM" in t or "RAG" in t else "down")
    directive = preferences.synthesize_directive("ia", _CFG)
    assert "agents LLM" in directive
    assert preferences.get_directive("ia") == directive
    assert "Préférences apprises" in preferences.preference_block("ia")


def test_synth_failopen_keeps_existing(monkeypatch):
    # 1) une première synthèse réussie pose une directive
    monkeypatch.setattr(preferences.llm, "complete", _fake_complete("Directive initiale."))
    for i in range(3):
        preferences.add_feedback("ia", f"a{i}", "up")
    preferences.synthesize_directive("ia", _CFG)
    # 2) une synthèse en erreur ne l'écrase pas
    monkeypatch.setattr(preferences.llm, "complete", _fake_complete("", err="pas de clé"))
    assert preferences.synthesize_directive("ia", _CFG) == "Directive initiale."


def test_namespaced_per_profile(monkeypatch):
    monkeypatch.setattr(preferences.llm, "complete", _fake_complete("Directive IA."))
    for i in range(3):
        preferences.add_feedback("ia", f"a{i}", "up")
    preferences.synthesize_directive("ia", _CFG)
    assert preferences.get_directive("ia") == "Directive IA."
    assert preferences.get_directive("devops") == ""
