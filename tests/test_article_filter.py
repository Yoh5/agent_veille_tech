# -*- coding: utf-8 -*-
"""Tests du filtrage, de la déduplication et du scoring."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import article_filter


@pytest.fixture
def seen_file(tmp_path, monkeypatch):
    f = tmp_path / "seen_articles.json"
    monkeypatch.setattr(article_filter, "SEEN_FILE", str(f))
    return f


def _art(title, url="", **extra):
    d = {"title": title, "url": url or f"https://ex.com/{title}", "content": "", "raw_weight": 1.0}
    d.update(extra)
    return d


def test_filter_ne_persiste_pas(seen_file):
    """Le filtrage ne doit RIEN écrire dans seen_articles.json :
    seuls les articles publiés (mark_seen) sont mémorisés."""
    arts = [_art("un LLM open source"), _art("recette de cuisine")]
    filtered, meta = article_filter.filter_articles(arts, ["llm"])
    assert len(filtered) == 1
    assert not seen_file.exists() or json.loads(seen_file.read_text()) == {}


def test_mark_seen_puis_skip(seen_file):
    """Un article marqué vu est écarté au run suivant ; les autres restent éligibles."""
    a1, a2 = _art("un LLM open source"), _art("agents LLM en production")
    filtered, _ = article_filter.filter_articles([a1, a2], ["llm"])
    assert len(filtered) == 2

    article_filter.mark_seen([a1])  # seul a1 est « publié »

    filtered2, meta2 = article_filter.filter_articles(
        [_art("un LLM open source"), _art("agents LLM en production")], ["llm"]
    )
    titles = [a["title"] for a in filtered2]
    assert titles == ["agents LLM en production"]
    assert meta2["deduped_skipped"] == 1


def test_dedup_intra_batch_titre_et_url(seen_file):
    arts = [
        _art("même titre", url="https://a.com/1"),
        _art("même titre", url="https://b.com/2"),          # doublon de titre
        _art("autre titre", url="https://a.com/1"),         # doublon d'URL
    ]
    filtered, meta = article_filter.filter_articles(arts, ["titre"])
    assert len(filtered) == 1
    assert meta["deduped_skipped"] == 2


def test_score_bonus_pertinence(seen_file):
    """À poids et engagement égaux, plus de mots-clés matchés = mieux classé."""
    faible = _art("article sur les LLM", url="https://x.com/a")
    fort = _art("LLM, RAG et agents", url="https://x.com/b",
                content="fine-tuning embedding")
    filtered, _ = article_filter.filter_articles(
        [faible, fort], ["llm", "rag", "agents", "fine-tuning", "embedding"]
    )
    assert filtered[0]["title"] == "LLM, RAG et agents"
    assert filtered[0]["kw_matches"] > filtered[1]["kw_matches"]
    assert filtered[0]["score"] > filtered[1]["score"]


def test_score_bonus_social(seen_file):
    populaire = _art("news LLM populaire", url="https://x.com/p", hn_points=400)
    discret = _art("news LLM discrète", url="https://x.com/d")
    filtered, _ = article_filter.filter_articles([discret, populaire], ["llm"])
    assert filtered[0]["title"] == "news LLM populaire"


def test_score_bonus_fraicheur(seen_file):
    """À poids égal, un article publié aujourd'hui bat un article ancien."""
    from datetime import datetime, timedelta, timezone
    frais = _art("annonce LLM du jour", url="https://x.com/frais",
                 published=datetime.now(timezone.utc).isoformat())
    vieux = _art("annonce LLM ancienne", url="https://x.com/vieux",
                 published=(datetime.now(timezone.utc) - timedelta(days=6)).isoformat())
    filtered, _ = article_filter.filter_articles([vieux, frais], ["llm"])
    assert filtered[0]["title"] == "annonce LLM du jour"


def test_parse_published_formats(seen_file):
    """RFC 822 (RSS) et ISO 8601 (HN/ArXiv) sont compris ; l'inconnu donne None."""
    assert article_filter._parse_published("Fri, 10 Jul 2026 08:00:00 GMT") is not None
    assert article_filter._parse_published("2026-07-10T08:00:00Z") is not None
    assert article_filter._parse_published("") is None
    assert article_filter._parse_published("n'importe quoi") is None


def test_normalize_title_accents_ponctuation():
    """Accents, ponctuation, casse et espaces convergent vers une forme canonique."""
    assert article_filter._normalize_title("GPT-5 lancé !") == \
           article_filter._normalize_title("GPT 5 lance")


def test_normalize_title_retire_suffixe_site():
    """Les suffixes de site (Google News, HN…) sont retirés."""
    a = article_filter._normalize_title("OpenAI launches GPT-5 | Hacker News")
    b = article_filter._normalize_title("OpenAI launches GPT-5 - TechCrunch")
    assert a == b == "openai launches gpt 5"


def test_normalize_title_garde_fou_tiret_ponctuation():
    """Un tiret de ponctuation n'est pas raboté si ça laisse < 3 mots."""
    assert article_filter._normalize_title("Rust - une introduction") == "rust une introduction"


def test_dedup_titres_quasi_identiques(seen_file):
    """« GPT-5 lancé ! » et « GPT 5 lance » = même actu (hash normalisé)."""
    arts = [
        _art("GPT-5 lancé !", url="https://a.com/1"),
        _art("GPT 5 lance", url="https://b.com/2"),
    ]
    filtered, meta = article_filter.filter_articles(arts, ["gpt"])
    assert len(filtered) == 1
    assert meta["deduped_skipped"] == 1


def test_dedup_quasi_doublon_jaccard(seen_file):
    """Même actu reformulée par une autre source (fort recouvrement de mots :
    ici un seul mot d'écart → Jaccard ≥ 0.85)."""
    arts = [
        _art("OpenAI annonce officiellement GPT-5 avec un contexte massif",
             url="https://a.com/1"),
        _art("OpenAI annonce GPT-5 avec un contexte massif",
             url="https://b.com/2"),
        _art("Mistral publie un tout nouveau modèle open source",
             url="https://c.com/3"),
    ]
    filtered, meta = article_filter.filter_articles(arts, ["openai", "mistral"])
    titles = [a["title"] for a in filtered]
    assert "Mistral publie un tout nouveau modèle open source" in titles
    assert len(filtered) == 2   # les deux OpenAI fusionnent, Mistral reste


def test_fenetre_dedup_expire(seen_file):
    """Un hash plus vieux que la fenêtre est purgé et l'article redevient éligible."""
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=10)).isoformat()
    h = article_filter._article_hash({"title": "vieux LLM article"})
    seen_file.write_text(json.dumps({h: old}))

    filtered, meta = article_filter.filter_articles(
        [_art("vieux LLM article")], ["llm"], dedup_window_days=7
    )
    assert len(filtered) == 1
    assert meta["deduped_skipped"] == 0
