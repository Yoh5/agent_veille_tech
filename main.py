#!/usr/bin/env python3
"""
Agent de Veille Tech v3
========================
Pipeline : Fetch → Dédup → Filtre mots-clés → Résumé LLM → Brief Markdown
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Utilise le magasin de certificats Windows/macOS : indispensable derrière un
# antivirus ou proxy d'entreprise qui intercepte le TLS (sinon toutes les
# requêtes HTTPS échouent en CERTIFICATE_VERIFY_FAILED)
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import config_loader, fetcher, article_filter, summarize, brief_generator, agent, obs


def run(config_path: str = "config.yaml"):
    print("=" * 55)
    print("🚀 Agent de Veille Tech v3")
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
    raw_articles, source_stats = fetcher.fetch_all(config)
    print(f"\n📥 Total brut : {len(raw_articles)} articles")

    if not raw_articles:
        print("❌ Aucun article récupéré.")
        return

    print(f"\n[3/5] Déduplication + filtrage mots-clés...")
    filtered, meta = article_filter.filter_articles(
        raw_articles,
        keywords,
        dedup_window_days=config.get("dedup_window_days", 7),
    )
    print(f"🎯 Articles retenus : {meta['passed_filter']} / {meta['fresh_fetched']} nouveaux")

    if meta.get("trends"):
        top = list(meta["trends"].items())[:3]
        print(f"📈 Top tendances : {', '.join(f'{k}({v})' for k, v in top)}")

    if not filtered:
        print("❌ Aucun article ne contient les mots-clés du profil.")
        return

    # Agent — jugement de pertinence : le LLM sélectionne/classe par importance
    judged, u_judge = agent.judge_relevance(filtered, config)
    top_articles = judged[:max_articles]
    # Agent — deep dive : texte complet des articles jugés majeurs (usage d'outil)
    agent.deep_dive(top_articles, config)
    print(f"   → {len(top_articles)} articles envoyés au LLM")

    print(f"\n[4/5] Résumé par LLM...")
    summarized = summarize.summarize_batch(top_articles, config)
    u_sum = summarize.get_last_usage()

    # Agent — synthèse trans-articles (tendances de fond)
    synthesis, u_synth = agent.synthesize(summarized, config)

    print("\n[5/5] Génération du brief...")
    meta["sources_stats"] = source_stats
    meta["synthesis"] = synthesis
    usage = obs.merge_usage(llm_cfg.get("model", ""), u_judge, u_sum, u_synth)
    meta["llm_usage"] = usage
    if usage.get("cost_usd"):
        print(f"   💰 {usage['in']} tk in / {usage['out']} tk out · ~${usage['cost_usd']:.4f} (jugement+résumés+synthèse)")
    brief_path = brief_generator.generate(
        summarized,
        config=config,
        meta=meta,
        output_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "briefs"),
    )

    # Ne marquer « vus » QUE les articles réellement publiés dans le brief :
    # les autres restent éligibles pour les prochains runs
    article_filter.mark_seen(summarized, config.get("dedup_window_days", 7))

    # Notification e-mail (désactivée par défaut — notifications.email de config.yaml)
    from core import notifier
    notifier.send_brief(brief_path, config_path)

    print("\n" + "=" * 55)
    print(f"✅ Terminé ! Brief : {brief_path}")
    print("=" * 55)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent de Veille Tech v2")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(args.config)
