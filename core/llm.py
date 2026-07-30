"""Primitives LLM partagées (OpenAI / Anthropic).

Construction du client, appel unitaire avec remontée d'usage tokens, détection
de rate limit, et `complete()` (client + retries + parsing optionnel JSON).
Utilisé par core/summarize.py (appels par article, en parallèle) et
core/agent.py (jugement de pertinence, synthèse — appels ponctuels).
"""
import json
import os
import time
from typing import Optional, Tuple

from core import obs

_log = obs.get_logger("llm")

DEFAULT_MAX_TOKENS = 1200


def is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return any(kw in s for kw in ("rate_limit", "rate limit", "overloaded", "529", "too many requests"))


def build_client(provider: str, llm_cfg: dict):
    """Retourne (client, erreur). client=None si clé absente ou package manquant."""
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY") or llm_cfg.get("openai_api_key", "")
        if not api_key:
            return None, "Clé OPENAI_API_KEY introuvable"
        try:
            from openai import OpenAI
            return OpenAI(api_key=api_key), None
        except ImportError:
            return None, "Package 'openai' non installé — pip install openai"

    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY") or llm_cfg.get("anthropic_api_key", "")
        if not api_key:
            return None, "Clé ANTHROPIC_API_KEY introuvable"
        try:
            import anthropic
            return anthropic.Anthropic(api_key=api_key), None
        except ImportError:
            return None, "Package 'anthropic' non installé — pip install anthropic"

    return None, f"Provider inconnu : '{provider}' (valeurs acceptées : openai | anthropic)"


def call(client, provider: str, model: str, max_tokens: int, temperature: float,
         prompt: str, json_mode: bool = True) -> Tuple[str, dict]:
    """Un appel LLM (sans retry). Retourne (texte, usage={'in','out'}).

    json_mode=True active le mode JSON natif d'OpenAI ; Anthropic n'a pas de
    mode JSON (le format est demandé dans le prompt)."""
    if provider == "openai":
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        u = getattr(resp, "usage", None)
        usage = {"in": getattr(u, "prompt_tokens", 0), "out": getattr(u, "completion_tokens", 0)} if u else {"in": 0, "out": 0}
        return resp.choices[0].message.content.strip(), usage

    # anthropic
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    u = getattr(resp, "usage", None)
    usage = {"in": getattr(u, "input_tokens", 0), "out": getattr(u, "output_tokens", 0)} if u else {"in": 0, "out": 0}
    return resp.content[0].text.strip(), usage


def complete(config: dict, prompt: str, json_mode: bool = True,
             max_tokens: Optional[int] = None, temperature: Optional[float] = None,
             retries: int = 3) -> Tuple[str, dict, Optional[str]]:
    """Construit le client depuis config['llm'], appelle le LLM avec retries sur
    rate limit. Retourne (texte, usage, erreur). Sur échec : ("", {...0}, err).

    Convenience mono-appel pour l'agent (jugement/synthèse). summarize garde sa
    propre boucle parallèle via build_client + call."""
    llm_cfg     = config.get("llm", {})
    provider    = llm_cfg.get("provider", "openai")
    model       = llm_cfg.get("model", "gpt-4o-mini")
    temp        = temperature if temperature is not None else llm_cfg.get("temperature", 0.3)
    mtok        = max_tokens if max_tokens is not None else llm_cfg.get("max_tokens", DEFAULT_MAX_TOKENS)

    client, err = build_client(provider, llm_cfg)
    if client is None:
        return "", {"in": 0, "out": 0}, err

    for attempt in range(retries):
        try:
            text, usage = call(client, provider, model, mtok, temp, prompt, json_mode=json_mode)
            return text, usage, None
        except Exception as e:
            if is_rate_limit(e) and attempt < retries - 1:
                wait = 10 * (2 ** attempt)
                _log.warning("⏳ Rate limit — attente %ss (tentative %d/%d)…", wait, attempt + 1, retries)
                time.sleep(wait)
            else:
                return "", {"in": 0, "out": 0}, str(e)
    return "", {"in": 0, "out": 0}, "échec après retries"


def parse_json_lenient(raw: str):
    """json.loads tolérant : accepte un objet JSON éventuellement entouré de
    texte ou de balises ```json. Retourne l'objet, ou None si introuvable."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    # extraire le premier objet/array JSON de la chaîne
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = raw.find(opener), raw.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(raw[i:j + 1])
            except Exception:
                continue
    return None
