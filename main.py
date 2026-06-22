#!/usr/bin/env python3
"""
Agent de Veille Tech v2
========================
Pipeline : Fetch → Dédup → Filtre mots-clés → Résumé LLM → Brief Markdown
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config_loader, fetcher, filter, summarize, brief_generator


def run(config_path: str = "config.yaml"):
    print("=" * 55)
    print("🚀 Agent de Veille Tech v2")
    print("=" * 55)

    print("\n[1/5] Chargement configuration...")
    config = config_loader.load(config_path)
    keywords = config["keywords"]
    max_articles = config["max_articles"]
    llm_cfg = config["llm"]

    print(f"   → Profil  : {config['profile_icon']} {config['profile_name']}")
    print(f"   → Modèle  : {llm_cfg.get('model')}")
    print(f"   → Mots-clés : {len(keywords)}")

    print("\n[2/5] Récupération des sources...")
    raw_articles = fetcher.fetch_all(config)
    print(f"\n📥 Total brut : {len(raw_articles)} articles")

    if not raw_articles:
        print("❌ Aucun article récupéré.")
        return

    print(f"\n[3/5] Déduplication + filtrage mots-clés...")
    filtered, meta = filter.filter_articles(
        raw_articles,
        keywords,
        dedup_window_days=config.get("dedup_window_days", 3),
    )
    print(f"🎯 Articles retenus : {meta['passed_filter']} / {meta['fresh_fetched']} nouveaux")

    if meta.get("trends"):
        top = list(meta["trends"].items())[:3]
        print(f"📈 Top tendances : {', '.join(f'{k}({v})' for k, v in top)}")

    if not filtered:
        print("❌ Aucun article ne contient les mots-clés du profil.")
        return

    top_articles = filtered[:max_articles]
    print(f"   → {len(top_articles)} articles envoyés au LLM")

    print(f"\n[4/5] Résumé par LLM...")
    summarized = summarize.summarize_batch(top_articles, config)

    print("\n[5/5] Génération du brief...")
    brief_path = brief_generator.generate(
        summarized,
        config=config,
        meta=meta,
        output_dir=os.path.join(os.path.dirname(config_path), "output", "briefs"),
    )

    print("\n" + "=" * 55)
    print(f"✅ Terminé ! Brief : {brief_path}")
    print("=" * 55)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent de Veille Tech v2")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
