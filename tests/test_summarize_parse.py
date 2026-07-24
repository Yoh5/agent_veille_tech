# -*- coding: utf-8 -*-
"""Tests du parsing des réponses LLM (format structuré FR/EN)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.summarize import _parse, _parse_json


FR = """RÉSUMÉ: **OpenAI** publie un nouveau modèle avec **40 %** de gains.
POINTS_CLÉS:
- Lancement le **12 mai 2026**
- Contexte de **1M** de tokens
- Prix divisé par **2**
À_RETENIR: La course au contexte long s'accélère.
ACTEURS: OpenAI, Google
TYPE: Innovation"""


def test_parse_fr_complet():
    r = _parse(FR)
    assert r["summary"].startswith("**OpenAI** publie")
    assert len(r["highlights"]) == 3
    assert r["takeaway"] == "La course au contexte long s'accélère."
    assert r["actors"] == ["OpenAI", "Google"]
    assert r["article_type"] == "Innovation"


def test_parse_en_types_traduits():
    en = "SUMMARY: A new zero-day.\nKEY_POINTS:\n- CVE-2026-1234\nTAKEAWAY: Patch now.\nACTORS: CISA\nTYPE: Security"
    r = _parse(en)
    assert r["article_type"] == "Sécurité"
    assert r["takeaway"] == "Patch now."


def test_parse_type_invalide_retombe_sur_actualite():
    r = _parse("RÉSUMÉ: x\nTYPE: Opinion")
    assert r["article_type"] == "Actualité"


def test_parse_resume_multiligne():
    raw = "RÉSUMÉ: Première ligne.\nDeuxième ligne collée.\nPOINTS_CLÉS:\n- a"
    r = _parse(raw)
    assert "Deuxième ligne collée." in r["summary"]


def test_parse_acteurs_vides_filtres():
    r = _parse("RÉSUMÉ: x\nACTEURS: aucun\nTYPE: Analyse")
    assert r["actors"] == []
    assert r["article_type"] == "Analyse"


def test_parse_degrade_sans_format():
    raw = "Texte libre sans aucun champ structuré."
    r = _parse(raw)
    assert r["summary"]          # fallback : début du texte brut
    assert r["article_type"] == "Actualité"


# ── _parse_json (format structuré principal) ───────────────────

def test_parse_json_fr_complet():
    import json
    raw = json.dumps({
        "summary": "**OpenAI** publie un modèle avec **40 %** de gains.",
        "key_points": ["Lancement le **12 mai**", "Contexte **1M** tokens", "Prix ÷ **2**"],
        "takeaway": "La course au contexte long s'accélère.",
        "actors": ["OpenAI", "Google"],
        "type": "Innovation",
    })
    r = _parse_json(raw)
    assert r["summary"].startswith("**OpenAI**")
    assert len(r["highlights"]) == 3
    assert r["takeaway"] == "La course au contexte long s'accélère."
    assert r["actors"] == ["OpenAI", "Google"]
    assert r["article_type"] == "Innovation"


def test_parse_json_en_type_traduit():
    import json
    raw = json.dumps({"summary": "A zero-day.", "key_points": ["CVE-2026-1"],
                      "takeaway": "Patch now.", "actors": ["CISA"], "type": "Security"})
    r = _parse_json(raw)
    assert r["article_type"] == "Sécurité"
    assert r["actors"] == ["CISA"]


def test_parse_json_type_invalide_retombe_sur_actualite():
    r = _parse_json('{"summary": "x", "type": "Opinion"}')
    assert r["article_type"] == "Actualité"


def test_parse_json_acteurs_vides_filtres():
    r = _parse_json('{"summary": "x", "actors": ["aucun", "", "OpenAI"], "type": "Analyse"}')
    assert r["actors"] == ["OpenAI"]


def test_parse_json_cap_4_acteurs_et_highlights():
    import json
    raw = json.dumps({
        "summary": "x",
        "key_points": ["a", "b", "c", "d", "e"],
        "actors": ["A", "B", "C", "D", "E"],
        "type": "Analyse",
    })
    r = _parse_json(raw)
    assert len(r["highlights"]) == 4
    assert len(r["actors"]) == 4


def test_parse_json_invalide_fallback_sur_parse_texte():
    """JSON cassé → le parser texte _parse() prend le relais (zéro régression)."""
    raw = "RÉSUMÉ: texte structuré mais pas du JSON\nTYPE: Analyse"
    r = _parse_json(raw)
    assert r["article_type"] == "Analyse"
    assert "texte structuré" in r["summary"]


def test_parse_json_liste_au_lieu_dobjet_fallback():
    """Un JSON valide mais qui n'est pas un objet retombe sur _parse."""
    r = _parse_json('["a", "b"]')
    assert r["article_type"] == "Actualité"   # _parse ne trouve pas de champ
