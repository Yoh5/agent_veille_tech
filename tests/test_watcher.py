# -*- coding: utf-8 -*-
"""Tests du mode veille continue (flux live, breaking news)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import watcher

WATCH_CFG = {
    "breaking_sources": ["OpenAI News", "Anthropic News"],
    "breaking_hn_points": 300,
}


def test_breaking_source_officielle():
    assert watcher._is_breaking({"source": "Anthropic News"}, WATCH_CFG) is True
    assert watcher._is_breaking({"source": "Dev.to"}, WATCH_CFG) is False


def test_breaking_engagement_fort():
    assert watcher._is_breaking({"source": "Hacker News", "hn_points": 450}, WATCH_CFG) is True
    assert watcher._is_breaking({"source": "Hacker News", "hn_points": 120}, WATCH_CFG) is False
    assert watcher._is_breaking({"source": "Reddit", "reddit_score": 350}, WATCH_CFG) is True


def test_feed_append_et_plafond(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "LIVE_FEED_FILE", str(tmp_path / "live.json"))
    monkeypatch.setattr(watcher, "LIVE_FEED_MAX", 3)
    watcher._append_to_feed([{"title": "a"}, {"title": "b"}])
    watcher._append_to_feed([{"title": "c"}, {"title": "d"}])
    feed = watcher.load_feed()
    # les plus récents d'abord, plafonné à 3
    assert [x["title"] for x in feed] == ["c", "d", "a"]


def test_delete_from_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "LIVE_FEED_FILE", str(tmp_path / "live.json"))
    a = {"title": "à supprimer", "url": "https://x.com/1"}
    b = {"title": "à garder", "url": "https://x.com/2"}
    a["id"], b["id"] = watcher._item_id(a), watcher._item_id(b)
    watcher._append_to_feed([a, b])

    assert watcher.delete_from_feed(a["id"]) is True
    assert [x["title"] for x in watcher.load_feed()] == ["à garder"]
    assert watcher.delete_from_feed("000000000000") is False


def test_load_feed_retrocompat_id(tmp_path, monkeypatch):
    """Les anciens articles sans id en reçoivent un au chargement."""
    import json
    f = tmp_path / "live.json"
    f.write_text(json.dumps([{"title": "vieux", "url": "https://x.com/v"}]), encoding="utf-8")
    monkeypatch.setattr(watcher, "LIVE_FEED_FILE", str(f))
    feed = watcher.load_feed()
    assert feed[0]["id"]


def test_daily_brief_sans_articles(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "LIVE_FEED_FILE", str(tmp_path / "live.json"))
    cfg = {"keywords": ["llm"], "max_articles": 12, "profile_name": "T",
           "profile_icon": "x", "profile_description": "", "llm": {}}
    assert watcher.generate_daily_brief(cfg, str(tmp_path)) is None
