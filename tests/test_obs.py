# -*- coding: utf-8 -*-
"""Tests de l'observabilité : estimation de coût LLM et logger."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import obs


def test_estimate_cost_modele_connu():
    # gpt-4o-mini : 0.15 in / 0.60 out par 1M tokens
    cost = obs.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert round(cost, 2) == round(0.15 + 0.60, 2)


def test_estimate_cost_suffixe_de_version():
    """Un nom de modèle versionné matche la clé de prix en sous-chaîne."""
    assert obs.estimate_cost("gpt-4o-mini-2024-07-18", 1_000_000, 0) > 0


def test_estimate_cost_modele_inconnu_zero():
    assert obs.estimate_cost("modele-inexistant-xyz", 1_000_000, 1_000_000) == 0.0


def test_estimate_cost_ne_leve_jamais():
    # entrées aberrantes → 0.0 sans exception
    assert obs.estimate_cost(None, None, None) == 0.0


def test_estimate_cost_correspondance_plus_longue():
    """claude-3-5-sonnet doit primer sur une éventuelle clé plus courte."""
    cost = obs.estimate_cost("claude-3-5-sonnet-20241022", 1_000_000, 0)
    assert round(cost, 2) == 3.00


def test_get_logger_nomme():
    log = obs.get_logger("test")
    assert log.name == "veille.test"
