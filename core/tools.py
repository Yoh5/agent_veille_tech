"""Outils de l'agent — récupération du texte complet d'un article.

`fetch_article_text(url)` va chercher le contenu réel d'une page pour donner au
résumeur de la matière (le flux ne fournit souvent qu'un titre ou un extrait
tronqué). Comme on récupère des URLs issues de sources publiques (donc
attaquant-contrôlables), un **garde-fou SSRF** bloque les adresses internes
(loopback, IP privées, link-local — dont 169.254.169.254, les métadonnées cloud)
et revalide chaque redirection. Sans quoi un article piégé ferait scanner le
réseau interne par le serveur.
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse, urljoin

import requests

from core import obs

_log = obs.get_logger("tools")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_MAX_BYTES = 500_000        # lecture plafonnée
_MAX_REDIRECTS = 3
_TIMEOUT = 12


# ── Garde-fou SSRF ─────────────────────────────────────────────
#
# Ce qu'il couvre : le schéma (http/https seulement), toutes les IP résolues
# du host — une seule adresse privée suffit à refuser — et chaque saut de
# redirection, revalidé avant d'être suivi, y compris quand `Location` est
# relatif. Des tests le vérifient sans toucher au réseau.
#
# Ce qu'il ne couvre PAS, et c'est écrit ici parce qu'un lecteur mérite de le
# savoir : le **DNS rebinding**. On résout le nom pour le vérifier, puis
# `requests` le résout une seconde fois pour se connecter. Qui contrôle la
# zone DNS peut répondre une IP publique à la première question et 127.0.0.1
# à la seconde. Fermer ça demande de se connecter à l'IP validée en portant
# le nom d'hôte dans l'en-tête Host et dans le SNI — ce n'est pas fait.
#
# La bonne réponse à cette limite n'est pas de la taire : « fetch anti-SSRF »
# décrit une garde réelle et testée, pas une garantie.

def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _host_is_safe(host: str) -> bool:
    """True seulement si TOUTES les IP résolues du host sont publiques."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(_ip_is_public(a) for a in addrs)


def _is_safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    return _host_is_safe(p.hostname or "")


# ── Extraction texte ───────────────────────────────────────────

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|template)[^>]*>.*?</\1>",
                              re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Extraction texte légère (sans dépendance) : retire script/style puis les
    balises, décode quelques entités, compacte les espaces."""
    if not html:
        return ""
    txt = _SCRIPT_STYLE_RE.sub(" ", html)
    txt = _TAG_RE.sub(" ", txt)
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        txt = txt.replace(ent, ch)
    return _WS_RE.sub(" ", txt).strip()


# ── Fetch sécurisé ─────────────────────────────────────────────

def fetch_article_text(url: str, max_chars: int = 8000) -> str:
    """Retourne le texte principal de la page, ou "" si l'URL est jugée non sûre
    (SSRF), inaccessible, ou non-HTML. Suit les redirections en revalidant
    chaque saut contre le garde-fou SSRF."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _is_safe_url(current):
            _log.warning("URL refusée (SSRF/non-http) : %s", current[:80])
            return ""
        try:
            resp = requests.get(
                current, timeout=_TIMEOUT,
                headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
                allow_redirects=False, stream=True,
            )
        except Exception as e:
            _log.warning("Fetch échoué (%s) : %s", type(e).__name__, current[:80])
            return ""

        # redirection : revalider la cible avant de suivre
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "")
            resp.close()
            if not loc:
                return ""
            current = urljoin(current, loc)
            continue

        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            resp.close()
            return ""

        chunk = b""
        for c in resp.iter_content(chunk_size=16384):
            chunk += c
            if len(chunk) >= _MAX_BYTES:
                break
        resp.close()
        text = _html_to_text(chunk.decode("utf-8", errors="ignore"))
        return text[:max_chars]

    _log.warning("Trop de redirections : %s", url[:80])
    return ""
