# -*- coding: utf-8 -*-
"""Tests de la mémoire thématique (core/memory) — sans réseau.

Le chemin de stockage est redirigé vers un fichier temporaire AVANT l'import
du module (car _MEM_PATH est résolu à l'import)."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_TMP = os.path.join(tempfile.gettempdir(), "veille_test_memory.json")
os.environ["VEILLE_MEMORY_PATH"] = _TMP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import memory  # noqa: E402


def setup_function(_=None):
    if os.path.exists(_TMP):
        os.remove(_TMP)


def _seed(profile, snapshots):
    """snapshots : liste de (jours_avant, {sujet: poids})."""
    now = datetime.now(timezone.utc)
    runs = [{"date": (now - timedelta(days=d)).isoformat(), "topics": t} for d, t in snapshots]
    memory._save({profile: runs})


# ── topics_from_articles ───────────────────────────────────────

def test_topics_word_boundary_and_case():
    arts = [{"title": "New RAG technique", "content": ""},
            {"title": "Cheap storage tips", "content": "drag and drop"},
            {"title": "gpt-5 rumor", "content": "about LLM agents"}]
    topics = memory.topics_from_articles(arts, ["RAG", "GPT", "LLM"])
    assert topics == {"RAG": 1, "GPT": 1, "LLM": 1}   # "storage"/"drag" ne comptent PAS pour RAG


def test_topics_omits_absent():
    arts = [{"title": "kubernetes stuff", "content": ""}]
    assert memory.topics_from_articles(arts, ["LLM", "RAG"]) == {}


# ── record_run / recall_context ────────────────────────────────

def test_recall_empty_without_history():
    assert memory.recall_context("ia") == ""


def test_record_then_recall_mentions_dominant_topic():
    arts = [{"title": "LLM agents everywhere", "content": "LLM"},
            {"title": "More on LLM", "content": ""}]
    memory.record_run("ia", arts, ["LLM", "RAG"])
    ctx = memory.recall_context("ia")
    assert ctx != ""
    assert "LLM" in ctx


def test_memory_is_namespaced_per_profile():
    memory.record_run("ia", [{"title": "LLM", "content": ""}], ["LLM"])
    assert "LLM" in memory.recall_context("ia")
    assert memory.recall_context("devops") == ""   # autre profil = mémoire vierge


# ── diff_topics (nouveaux / hausse / baisse) ───────────────────

def test_diff_new_rising_fading():
    _seed("ia", [
        (1, {"LLM": 1, "Blockchain": 2}),
        (3, {"LLM": 1, "Blockchain": 2}),
    ])  # moyennes : LLM 1.0, Blockchain 2.0
    diff = memory.diff_topics({"LLM": 2, "Agent": 3}, "ia")
    assert diff["new"] == ["Agent"]           # absent de la mémoire
    assert "LLM" in diff["rising"]            # 2 ≥ 1.0×1.5 et ≥ 2
    assert "Blockchain" in diff["fading"]     # présent avant, absent maintenant


def test_diff_empty_without_history():
    assert memory.diff_topics({"LLM": 3}, "ia") == {"new": [], "rising": [], "fading": []}


def test_diff_ignores_runs_outside_window():
    _seed("ia", [(90, {"LLM": 5})])           # trop ancien (>14 j)
    diff = memory.diff_topics({"LLM": 1}, "ia", days=14)
    assert diff == {"new": [], "rising": [], "fading": []}


# ── robustesse ─────────────────────────────────────────────────

def test_snapshots_capped():
    now = datetime.now(timezone.utc)
    memory._save({"ia": [{"date": now.isoformat(), "topics": {"X": 1}} for _ in range(80)]})
    memory.record_run("ia", [{"title": "X", "content": ""}], ["X"])
    runs = memory._load()["ia"]
    assert len(runs) <= memory._MAX_SNAPSHOTS


def test_corrupt_memory_is_failopen():
    with open(_TMP, "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    assert memory.recall_context("ia") == ""
    assert memory.diff_topics({"LLM": 1}, "ia") == {"new": [], "rising": [], "fading": []}
