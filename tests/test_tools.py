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


# ── Redirections : le saut que la garde doit revalider ─────────
#
# C'est le chemin par lequel un SSRF passe en pratique. L'URL de départ est
# publique et passe la garde ; c'est la *cible* de la redirection qui vise
# l'intérieur. La docstring promettait la revalidation, rien ne la vérifiait.

class _FakeResponse:
    def __init__(self, status=200, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    def iter_content(self, chunk_size=16384):
        yield self._body

    def close(self):
        self.closed = True


def _route(monkeypatch, pages, public_hosts):
    """Un faux réseau : `pages` mappe une URL à une réponse, `public_hosts` dit
    quels noms résolvent en IP publique."""
    asked = []

    def fake_get(url, **kwargs):
        asked.append(url)
        return pages[url]

    monkeypatch.setattr(tools.requests, "get", fake_get)
    monkeypatch.setattr(tools, "_host_is_safe", lambda host: host in public_hosts)
    return asked


def test_une_redirection_vers_une_adresse_interne_est_refusee(monkeypatch):
    pages = {
        "https://blog.example.net/a": _FakeResponse(
            302, {"Location": "http://169.254.169.254/latest/meta-data/"}),
    }
    asked = _route(monkeypatch, pages, public_hosts={"blog.example.net"})

    assert tools.fetch_article_text("https://blog.example.net/a") == ""
    # La cible interne n'a jamais été demandée : refusée avant la requête.
    assert asked == ["https://blog.example.net/a"]


def test_une_redirection_vers_une_cible_publique_est_suivie(monkeypatch):
    pages = {
        "https://blog.example.net/a": _FakeResponse(301, {"Location": "https://cdn.example.org/b"}),
        "https://cdn.example.org/b": _FakeResponse(
            200, {"Content-Type": "text/html"}, b"<p>Bonjour</p>"),
    }
    _route(monkeypatch, pages, public_hosts={"blog.example.net", "cdn.example.org"})

    assert "Bonjour" in tools.fetch_article_text("https://blog.example.net/a")


def test_une_boucle_de_redirections_s_arrete(monkeypatch):
    pages = {
        "https://a.example.net/": _FakeResponse(302, {"Location": "https://b.example.net/"}),
        "https://b.example.net/": _FakeResponse(302, {"Location": "https://a.example.net/"}),
    }
    asked = _route(monkeypatch, pages, public_hosts={"a.example.net", "b.example.net"})

    assert tools.fetch_article_text("https://a.example.net/") == ""
    assert len(asked) <= tools._MAX_REDIRECTS + 1


def test_une_redirection_relative_est_resolue_avant_la_garde(monkeypatch):
    """`Location: /interne` ne doit pas contourner la revalidation."""
    pages = {
        "https://blog.example.net/a": _FakeResponse(302, {"Location": "/autre"}),
        "https://blog.example.net/autre": _FakeResponse(
            200, {"Content-Type": "text/html"}, b"<p>Suite</p>"),
    }
    _route(monkeypatch, pages, public_hosts={"blog.example.net"})

    assert "Suite" in tools.fetch_article_text("https://blog.example.net/a")


def test_une_reponse_non_html_est_ignoree(monkeypatch):
    pages = {"https://blog.example.net/a": _FakeResponse(
        200, {"Content-Type": "application/pdf"}, b"%PDF-1.7")}
    _route(monkeypatch, pages, public_hosts={"blog.example.net"})

    assert tools.fetch_article_text("https://blog.example.net/a") == ""
