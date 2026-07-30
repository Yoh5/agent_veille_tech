# -*- coding: utf-8 -*-
"""Tests de l'outil de fetch : garde-fou SSRF et extraction texte (sans réseau)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import tools


# ── Classification IP ──────────────────────────────────────────

def test_ip_public_vs_prive():
    assert tools._ip_is_public("8.8.8.8") is True
    assert tools._ip_is_public("1.1.1.1") is True
    assert tools._ip_is_public("127.0.0.1") is False       # loopback
    assert tools._ip_is_public("10.0.0.5") is False         # privé
    assert tools._ip_is_public("192.168.1.1") is False      # privé
    assert tools._ip_is_public("172.16.0.1") is False       # privé
    assert tools._ip_is_public("169.254.169.254") is False  # link-local (métadonnées cloud)
    assert tools._ip_is_public("pas-une-ip") is False


# ── URL sûre / SSRF ────────────────────────────────────────────

def test_url_schema_non_http_refuse():
    assert tools._is_safe_url("ftp://exemple.com/x") is False
    assert tools._is_safe_url("file:///etc/passwd") is False
    assert tools._is_safe_url("javascript:alert(1)") is False


def test_url_ip_interne_refusee_sans_reseau():
    # une IP littérale interne est classée directement, aucune résolution réseau
    assert tools._is_safe_url("http://169.254.169.254/latest/meta-data/") is False
    assert tools._is_safe_url("http://127.0.0.1:8000/admin") is False
    assert tools._is_safe_url("http://10.1.2.3/interne") is False


def test_url_publique_acceptee(monkeypatch):
    # on simule la résolution DNS vers une IP publique (pas de vrai réseau)
    monkeypatch.setattr(tools.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert tools._is_safe_url("https://exemple.com/article") is True


def test_url_host_resolvant_en_prive_refuse(monkeypatch):
    """Un domaine public qui résout vers une IP interne (DNS rebinding) est bloqué."""
    monkeypatch.setattr(tools.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("192.168.0.10", 0))])
    assert tools._is_safe_url("https://piege.exemple.com/x") is False


def test_fetch_url_non_sure_retourne_vide():
    # URL interne → aucune requête, chaîne vide (pas de réseau requis)
    assert tools.fetch_article_text("http://169.254.169.254/latest/") == ""


# ── Extraction texte ───────────────────────────────────────────

def test_html_to_text_retire_script_style_et_balises():
    html = ("<html><head><style>.x{color:red}</style></head><body>"
            "<script>steal()</script><h1>Titre</h1><p>Bonjour <b>le monde</b> &amp; co.</p>"
            "</body></html>")
    txt = tools._html_to_text(html)
    assert "steal" not in txt
    assert "color:red" not in txt
    assert txt == "Titre Bonjour le monde & co."


def test_html_to_text_vide():
    assert tools._html_to_text("") == ""
    assert tools._html_to_text(None) == ""
